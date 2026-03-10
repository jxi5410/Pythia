#!/usr/bin/env python3
"""
Pythia Causal Analysis v2 — 5-layer attribution pipeline with governance.

Layer 1: Context Builder (free)
Layer 2: News Retrieval (free APIs)
Layer 3: Candidate Filter (Sonnet — fast relevance scoring)
Layer 4: Causal Reasoning (Opus — deep analysis)
Layer 5: Store & Learn (local DB)

Governance (Singapore IMDA + UC Berkeley):
- Confidence scoring at each layer
- Validation checkpoints between agents
- Audit trail for all actions
- Circuit breaker for cost control
- Human approval gates for low-confidence signals
"""

import json
import logging
import re
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from urllib.parse import quote_plus, urlparse, unquote

import requests
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

# Governance layer imports
try:
    from .governance import (
        AgentRole, AgentAction, AuditTrail,
        get_governance, init_governance, GovernanceConfig
    )
    GOVERNANCE_AVAILABLE = True
except ImportError:
    GOVERNANCE_AVAILABLE = False
    logger.warning("Governance module not available - running without compliance layer")

logger = logging.getLogger(__name__)

NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")

# ---------------------------------------------------------------------------
# Layer 1: Context Builder
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS = {
    "fed_rate": ["fed", "federal reserve", "fomc", "interest rate", "powell", "rate cut", "rate hike", "monetary policy"],
    "inflation": ["inflation", "cpi", "pce", "consumer price", "deflation"],
    "election": ["election", "president", "vote", "candidate", "ballot", "republican", "democrat", "trump", "biden"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "defi", "token"],
    "trade_war": ["tariff", "trade war", "sanctions", "import duty", "trade deal", "embargo"],
    "geopolitical": ["war", "ceasefire", "nato", "invasion", "military", "peace deal", "nuclear"],
    "tech": ["openai", "gpt", "google", "apple", "ai regulation", "antitrust", "tiktok"],
    "recession": ["recession", "gdp", "unemployment", "yield curve", "layoffs", "economic growth"],
    "energy": ["oil", "opec", "natural gas", "energy", "petroleum", "barrel"],
}


def classify_market(title: str) -> str:
    """Classify a market into a category based on title keywords."""
    title_lower = title.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in title_lower)
        if score > 0:
            scores[cat] = score
    return max(scores, key=scores.get) if scores else "general"


def extract_entities_simple(title: str) -> List[str]:
    """Extract key entities from market title without LLM (fast fallback)."""
    stop_words = {"will", "the", "be", "in", "by", "of", "a", "an", "to", "for", "on", "is", "at", "this", "that", "it"}
    words = re.sub(r'[?!.,]', '', title).split()
    entities = [w for w in words if w.lower() not in stop_words and len(w) > 2]
    return entities[:5]


ENTITY_PROMPT = """Extract the key searchable entities from this prediction market title.
Return ONLY a JSON array of 3-5 specific search terms that would find news causing price moves in this market.

Title: {title}

Examples:
- "Will the Fed cut rates by June 2025?" → ["Federal Reserve rate cut", "FOMC June 2025", "Jerome Powell dovish"]
- "Bitcoin above 100K by June?" → ["Bitcoin price 100000", "BTC rally", "crypto market surge"]

Return ONLY the JSON array, nothing else."""


def extract_entities_llm(title: str, llm_call=None) -> List[str]:
    """Extract entities using LLM for better search queries."""
    if not llm_call:
        return extract_entities_simple(title)

    try:
        response = llm_call(ENTITY_PROMPT.format(title=title))
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            entities = json.loads(match.group())
            if isinstance(entities, list) and entities:
                return [str(e) for e in entities[:5]]
    except Exception as e:
        logger.warning("LLM entity extraction failed: %s", e)

    return extract_entities_simple(title)


def find_concurrent_spikes(target_spike, all_spikes, window_hours: float = 2.0) -> List[Dict]:
    """Find other spikes that occurred within the time window."""
    concurrent = []
    target_ts = target_spike.timestamp
    if isinstance(target_ts, str):
        target_ts = datetime.fromisoformat(target_ts)

    for spike in all_spikes:
        if spike.id == target_spike.id:
            continue
        spike_ts = spike.timestamp
        if isinstance(spike_ts, str):
            spike_ts = datetime.fromisoformat(spike_ts)
        diff = abs((spike_ts - target_ts).total_seconds())
        if diff <= window_hours * 3600:
            concurrent.append({
                "market_title": spike.market_title[:60],
                "direction": spike.direction,
                "magnitude": spike.magnitude,
                "time_diff_min": int(diff / 60),
            })
    return concurrent


def build_spike_context(spike, all_recent_spikes=None, entity_llm=None) -> Dict:
    """Build full context for a spike before attribution."""
    ts = spike.timestamp
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)

    correlated = find_concurrent_spikes(spike, all_recent_spikes or [], window_hours=2)

    # Use LLM for entity extraction if available, else simple fallback
    entities = extract_entities_llm(spike.market_title, llm_call=entity_llm)

    return {
        "market_title": spike.market_title,
        "category": classify_market(spike.market_title),
        "entities": entities,
        "spike": {
            "direction": spike.direction,
            "magnitude": spike.magnitude,
            "timestamp": ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
            "price_before": spike.price_before,
            "price_after": spike.price_after,
            "volume": spike.volume_at_spike,
        },
        "temporal_window": {
            "start": (ts - timedelta(hours=2)).isoformat(),
            "end": (ts + timedelta(minutes=30)).isoformat(),
        },
        "correlated_spikes": correlated,
        "is_macro": len(correlated) >= 2,
    }


# ---------------------------------------------------------------------------
# Layer 2: News Retrieval (free sources, temporally filtered)
# ---------------------------------------------------------------------------

def newsapi_search(query: str, from_date: str = None, to_date: str = None, max_results: int = 10) -> List[Dict]:
    """Search NewsAPI.org (free tier: 100 req/day). Best temporal filtering."""
    if not NEWSAPI_KEY:
        return []

    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "apiKey": NEWSAPI_KEY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": max_results,
        }
        if from_date:
            params["from"] = from_date[:19]  # ISO format
        if to_date:
            params["to"] = to_date[:19]

        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        articles = []
        for art in data.get("articles", []):
            articles.append({
                "headline": (art.get("title") or "")[:200],
                "url": art.get("url", ""),
                "source": art.get("source", {}).get("name", ""),
                "snippet": (art.get("description") or "")[:200],
                "published": art.get("publishedAt", ""),
                "retrieval_source": "newsapi",
            })
        return articles

    except Exception as e:
        logger.warning("NewsAPI search failed: %s", e)
        return []


def _parse_published_date(date_str: str) -> Optional[datetime]:
    """Try to parse various date formats from news sources."""
    if not date_str:
        return None
    try:
        # ISO format (NewsAPI, Reddit)
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except:
        pass
    try:
        # RFC 2822 (RSS feeds)
        return parsedate_to_datetime(date_str).replace(tzinfo=None)
    except:
        pass
    return None


def filter_by_temporal_window(articles: List[Dict], window_start: str, window_end: str) -> List[Dict]:
    """Keep only articles published within the temporal window."""
    try:
        ws = datetime.fromisoformat(window_start)
        we = datetime.fromisoformat(window_end)
    except:
        return articles  # Can't parse window, return all

    filtered = []
    for art in articles:
        pub_date = _parse_published_date(art.get("published", ""))
        if pub_date is None:
            # No publish date — keep it but mark as unverified
            art["temporal_verified"] = False
            filtered.append(art)
        elif ws <= pub_date <= we:
            art["temporal_verified"] = True
            filtered.append(art)
        # else: outside window, discard

    return filtered


def google_news_rss(query: str, max_results: int = 10) -> List[Dict]:
    """Search Google News RSS (free, no API key)."""
    try:
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PythiaLive/2.0)"
        })
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "xml")
        articles = []

        for item in soup.find_all("item")[:max_results]:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            source = item.find("source")

            articles.append({
                "headline": title.get_text(strip=True) if title else "",
                "url": link.get_text(strip=True) if link else "",
                "source": source.get_text(strip=True) if source else "",
                "published": pub_date.get_text(strip=True) if pub_date else "",
                "retrieval_source": "google_news_rss",
            })

        return articles

    except Exception as e:
        logger.warning("Google News RSS failed: %s", e)
        return []


def brave_search(query: str, max_results: int = 5) -> List[Dict]:
    """Use Brave Search API (already configured in OpenClaw)."""
    # This is called via the web_search tool at the orchestrator level
    # For standalone use, fall back to DuckDuckGo
    return duckduckgo_search(query, max_results)


def duckduckgo_search(query: str, max_results: int = 5) -> List[Dict]:
    """DuckDuckGo HTML scraping (fallback)."""
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        resp = requests.get(url, timeout=5, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PythiaLive/2.0)"
        })
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []

        for result in soup.select(".result__body")[:max_results]:
            title_el = result.select_one(".result__a")
            snippet_el = result.select_one(".result__snippet")

            if not title_el:
                continue

            headline = title_el.get_text(strip=True)
            link = title_el.get("href", "")

            if "/l/?uddg=" in link:
                match = re.search(r"uddg=([^&]+)", link)
                if match:
                    link = unquote(match.group(1))

            domain = ""
            try:
                domain = urlparse(link).netloc.replace("www.", "")
            except:
                pass

            articles.append({
                "headline": headline[:200],
                "url": link,
                "source": domain,
                "snippet": snippet_el.get_text(strip=True)[:200] if snippet_el else "",
                "retrieval_source": "duckduckgo",
            })

        return articles

    except Exception as e:
        logger.warning("DuckDuckGo search failed: %s", e)
        return []


def reddit_search(query: str, subreddit: str = "news", max_results: int = 5) -> List[Dict]:
    """Search Reddit for relevant posts (free, no auth needed for search)."""
    try:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {
            "q": query,
            "sort": "new",
            "limit": max_results,
            "restrict_sr": "true",
            "t": "day",
        }
        resp = requests.get(url, params=params, timeout=10, headers={
            "User-Agent": "PythiaLive/2.0"
        })
        resp.raise_for_status()

        data = resp.json()
        articles = []

        for post in data.get("data", {}).get("children", []):
            d = post.get("data", {})
            articles.append({
                "headline": d.get("title", "")[:200],
                "url": f"https://reddit.com{d.get('permalink', '')}",
                "source": f"r/{subreddit}",
                "snippet": d.get("selftext", "")[:200],
                "score": d.get("score", 0),
                "retrieval_source": "reddit",
            })

        return articles

    except Exception as e:
        logger.warning("Reddit search failed: %s", e)
        return []


SUBREDDIT_MAP = {
    "fed_rate": "economics+finance+investing",
    "inflation": "economics+finance",
    "election": "politics+news",
    "crypto": "cryptocurrency+bitcoin+ethtrader",
    "trade_war": "economics+worldnews",
    "geopolitical": "worldnews+geopolitics",
    "tech": "technology+artificial",
    "recession": "economics+finance",
    "energy": "energy+oil",
    "general": "news",
}


def retrieve_candidate_news(context: Dict) -> List[Dict]:
    """
    Fetch news from multiple free sources.
    Searches using extracted entities for better relevance.
    Applies temporal filtering to keep only articles within spike window.
    """
    entities = context["entities"]
    category = context["category"]
    window = context["temporal_window"]

    # Build targeted search queries
    entity_query = " ".join(entities[:3])
    category_query = f"{entity_query} {category.replace('_', ' ')}"

    candidates = []

    # Source 1: NewsAPI (best temporal filtering, 100 req/day free)
    candidates += newsapi_search(
        entity_query,
        from_date=window["start"],
        to_date=window["end"],
        max_results=10,
    )

    # Source 2: Google News RSS
    candidates += google_news_rss(entity_query, max_results=8)

    # Source 3: DuckDuckGo (broader search)
    candidates += duckduckgo_search(category_query, max_results=5)

    # Source 4: Reddit (discussion/sentiment)
    subreddit = SUBREDDIT_MAP.get(category, "news")
    candidates += reddit_search(entity_query, subreddit=subreddit, max_results=5)

    # Temporal filtering: keep only articles within 2h window
    candidates = filter_by_temporal_window(candidates, window["start"], window["end"])

    # Deduplicate by headline similarity
    seen_headlines = set()
    unique = []
    for article in candidates:
        headline_key = article["headline"][:50].lower()
        if headline_key not in seen_headlines:
            seen_headlines.add(headline_key)
            unique.append(article)

    return unique


# ---------------------------------------------------------------------------
# Layer 3: Candidate Filter (LLM — Sonnet for speed)
# ---------------------------------------------------------------------------

FILTER_PROMPT = """You are filtering news articles for relevance to a prediction market spike.

MARKET: {market_title}
CATEGORY: {category}
SPIKE: {direction} {magnitude:.1%} at {timestamp}

ARTICLES:
{articles_text}

For each article, give:
- Number
- Score (0-10, where 10 = clearly caused this spike, 0 = completely unrelated)
- One-line reason

Respond as JSON array:
[{{"article": 1, "score": 8, "reason": "Direct Fed rate announcement"}}, ...]

Only score. Do not explain anything else."""


def format_articles_for_filter(articles: List[Dict]) -> str:
    """Format articles for the filter prompt."""
    lines = []
    for i, art in enumerate(articles, 1):
        source = art.get("source", "unknown")
        headline = art.get("headline", "")
        snippet = art.get("snippet", "")
        lines.append(f"{i}. [{source}] {headline}")
        if snippet:
            lines.append(f"   {snippet[:100]}")
    return "\n".join(lines)


def filter_candidates(context: Dict, articles: List[Dict], llm_call=None) -> List[Dict]:
    """
    Score articles on relevance using an LLM.
    Returns articles with score >= 5, sorted by relevance.
    
    llm_call: function(prompt) -> str (injected, so we're not tied to a specific LLM SDK)
    """
    if not articles:
        return []

    if not llm_call:
        # No LLM available — return all articles with default score
        for art in articles:
            art["relevance_score"] = 5
        return articles

    prompt = FILTER_PROMPT.format(
        market_title=context["market_title"],
        category=context["category"],
        direction=context["spike"]["direction"],
        magnitude=context["spike"]["magnitude"],
        timestamp=context["spike"]["timestamp"],
        articles_text=format_articles_for_filter(articles),
    )

    try:
        response = llm_call(prompt)

        # Parse JSON from response
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if json_match:
            scores = json.loads(json_match.group())
            for score_entry in scores:
                idx = score_entry.get("article", 0) - 1
                if 0 <= idx < len(articles):
                    articles[idx]["relevance_score"] = score_entry.get("score", 0)
                    articles[idx]["relevance_reason"] = score_entry.get("reason", "")

        # Filter and sort
        filtered = [a for a in articles if a.get("relevance_score", 0) >= 5]
        filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return filtered[:5]

    except Exception as e:
        logger.warning("Candidate filter failed: %s", e)
        return articles[:5]


# ---------------------------------------------------------------------------
# Layer 4: Causal Reasoning (LLM — Opus for depth)
# ---------------------------------------------------------------------------

CAUSAL_PROMPT = """You are a prediction market analyst determining what caused a specific price spike.

MARKET: {market_title}
CATEGORY: {category}
SPIKE: {direction} {magnitude:.1%} move
  Price: {price_before:.2f} → {price_after:.2f}
  Time: {timestamp}
  Volume: ${volume:,.0f}

STATISTICAL VALIDATION:
{statistical_evidence}

CONCURRENT MARKET MOVES ({n_correlated} markets moved within 2 hours):
{correlated_text}

TOP CANDIDATE CAUSES (relevance-filtered):
{candidates_text}

Analyze and respond in this exact JSON format:
{{
  "most_likely_cause": "One sentence describing the most likely cause",
  "causal_chain": "Event → Mechanism → Market Impact (e.g., 'CPI print at 3.8% → exceeded consensus of 3.5% → traders repriced Fed rate cut probability down')",
  "confidence": "HIGH|MEDIUM|LOW",
  "confidence_reasoning": "Why this confidence level",
  "macro_or_idiosyncratic": "MACRO|IDIOSYNCRATIC",
  "macro_reasoning": "Why macro or idiosyncratic",
  "expected_duration": "SUSTAINED|TEMPORARY|UNKNOWN",
  "duration_reasoning": "Why this duration expectation",
  "trading_implication": "What a trader should consider",
  "alternative_explanations": ["Other possible causes if confidence is not HIGH"]
}}

Be precise. If evidence is weak, say so. Do not fabricate causal links."""


def format_correlated(correlated: List[Dict]) -> str:
    if not correlated:
        return "  None — this appears to be an isolated move."
    lines = []
    for c in correlated:
        lines.append(f"  • {c['market_title']}... — {c['direction']} {c['magnitude']:.1%} ({c['time_diff_min']:+d} min)")
    return "\n".join(lines)


def format_candidates(candidates: List[Dict]) -> str:
    if not candidates:
        return "  No relevant news articles found."
    lines = []
    for i, c in enumerate(candidates, 1):
        score = c.get("relevance_score", "?")
        reason = c.get("relevance_reason", "")
        lines.append(f"  {i}. [{score}/10] {c['headline']}")
        lines.append(f"     Source: {c.get('source', 'unknown')}")
        if reason:
            lines.append(f"     Relevance: {reason}")
    return "\n".join(lines)


def reason_about_cause(context: Dict, candidates: List[Dict], llm_call=None,
                       extra_context: str = "") -> Dict:
    """
    Deep causal reasoning using Opus.
    
    Returns structured attribution dict.
    """
    if not llm_call:
        return {
            "most_likely_cause": candidates[0]["headline"] if candidates else "Unknown",
            "confidence": "LOW",
            "confidence_reasoning": "No LLM available for causal reasoning",
            "causal_chain": "Unknown",
            "macro_or_idiosyncratic": "UNKNOWN",
            "expected_duration": "UNKNOWN",
            "trading_implication": "Insufficient analysis",
        }

    spike = context["spike"]
    causal_prompt = CAUSAL_PROMPT
    if extra_context:
        causal_prompt = CAUSAL_PROMPT + extra_context

    # Format statistical evidence for the prompt
    stat_val = context.get("statistical_validation")
    if stat_val:
        stat_lines = [
            f"  Method: {stat_val.get('method', 'N/A')}",
            f"  Statistically significant: {stat_val.get('is_significant', 'N/A')}",
            f"  P-value: {stat_val.get('p_value', 'N/A')}",
        ]
        if stat_val.get("z_score") is not None:
            stat_lines.append(f"  Z-score: {stat_val['z_score']}")
        if stat_val.get("n_controls"):
            stat_lines.append(f"  Control markets used: {stat_val['n_controls']}")
        if stat_val.get("relative_effect_pct") is not None:
            stat_lines.append(f"  Relative effect: {stat_val['relative_effect_pct']}%")
        statistical_evidence = "\n".join(stat_lines)
    else:
        statistical_evidence = "  Not available (insufficient data for counterfactual analysis)"

    prompt = causal_prompt.format(
        market_title=context["market_title"],
        category=context["category"],
        direction=spike["direction"],
        magnitude=spike["magnitude"],
        price_before=spike["price_before"],
        price_after=spike["price_after"],
        timestamp=spike["timestamp"],
        volume=spike["volume"],
        statistical_evidence=statistical_evidence,
        n_correlated=len(context["correlated_spikes"]),
        correlated_text=format_correlated(context["correlated_spikes"]),
        candidates_text=format_candidates(candidates),
    )

    try:
        response = llm_call(prompt)

        # Parse JSON from response
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            attribution = json.loads(json_match.group())
            attribution["raw_reasoning"] = response
            return attribution

    except Exception as e:
        logger.warning("Causal reasoning failed: %s", e)

    return {
        "most_likely_cause": "Attribution failed",
        "confidence": "LOW",
        "causal_chain": "Error in analysis",
    }


# ---------------------------------------------------------------------------
# Layer 5: Store, Learn & Feedback
# ---------------------------------------------------------------------------

FEEDBACK_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "causal_feedback.jsonl")


def save_attribution_to_db(db, spike_id: int, result: Dict):
    """Save full attribution result to the spike record in DB."""
    try:
        attr = result.get("attribution", {})
        # Update the spike's attributed_events with v2 data
        attributed_events = []
        for c in result.get("top_candidates", []):
            attributed_events.append({
                "headline": c.get("headline", ""),
                "source": c.get("source", ""),
                "url": c.get("url", ""),
                "relevance_score": c.get("relevance_score", 0),
                "relevance_reason": c.get("relevance_reason", ""),
                "temporal_verified": c.get("temporal_verified", False),
            })

        # Build enriched record
        enriched = {
            "v2_attribution": {
                "most_likely_cause": attr.get("most_likely_cause", ""),
                "causal_chain": attr.get("causal_chain", ""),
                "confidence": attr.get("confidence", "LOW"),
                "confidence_reasoning": attr.get("confidence_reasoning", ""),
                "macro_or_idiosyncratic": attr.get("macro_or_idiosyncratic", "UNKNOWN"),
                "expected_duration": attr.get("expected_duration", "UNKNOWN"),
                "trading_implication": attr.get("trading_implication", ""),
                "alternative_explanations": attr.get("alternative_explanations", []),
            },
            "candidates_retrieved": result.get("candidates_retrieved", 0),
            "candidates_filtered": result.get("candidates_filtered", 0),
            "attributed_events": attributed_events,
        }

        conn = db._get_conn()
        conn.execute(
            "UPDATE spike_events SET attributed_events = ? WHERE id = ?",
            (json.dumps(enriched), spike_id)
        )
        conn.commit()
        conn.close()
        logger.info("Attribution saved to DB for spike %d", spike_id)

    except Exception as e:
        logger.warning("Failed to save attribution to DB: %s", e)


def check_outcome(db, spike_id: int, hours_later: int = 1) -> Optional[Dict]:
    """
    Check what happened to the price after the spike.
    Call this 1h and 24h after attribution for outcome tracking.
    """
    try:
        conn = db._get_conn()
        row = conn.execute(
            "SELECT market_id, price_after, timestamp FROM spike_events WHERE id = ?",
            (spike_id,)
        ).fetchone()
        conn.close()

        if not row:
            return None

        market_id, price_at_spike, spike_ts = row

        # Get the latest price for this market
        import pandas as pd
        history = db.get_market_history(market_id, hours=hours_later + 1)
        if history.empty:
            return None

        latest_price = history["yes_price"].iloc[-1]
        price_change = latest_price - price_at_spike

        outcome = {
            "spike_id": spike_id,
            "hours_later": hours_later,
            "price_at_spike": price_at_spike,
            "price_now": latest_price,
            "price_change": price_change,
            "sustained": abs(price_change) < 0.02,  # Move held if < 2% reversal
            "reversed": price_change < -0.03 if price_at_spike > 0 else price_change > 0.03,
            "checked_at": datetime.utcnow().isoformat(),
        }

        # Save outcome to DB
        conn = db._get_conn()
        reaction_key = f"price_{hours_later}h_later"
        conn.execute(
            "UPDATE spike_events SET asset_reaction = json_set(COALESCE(asset_reaction, '{}'), ?, ?) WHERE id = ?",
            (f"$.{reaction_key}", latest_price, spike_id)
        )
        conn.commit()
        conn.close()

        return outcome

    except Exception as e:
        logger.warning("Outcome check failed for spike %d: %s", spike_id, e)
        return None


def log_feedback(spike_id: int, feedback_type: str, details: str):
    """
    Log human feedback on an attribution.
    
    feedback_type: "correct", "wrong", "partial", "irrelevant"
    details: free text explanation
    """
    entry = {
        "spike_id": spike_id,
        "feedback_type": feedback_type,
        "details": details,
        "timestamp": datetime.utcnow().isoformat(),
    }

    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    logger.info("Feedback logged for spike %d: %s", spike_id, feedback_type)


def load_feedback_corrections() -> List[Dict]:
    """Load all feedback for use in improving future prompts."""
    if not os.path.exists(FEEDBACK_FILE):
        return []

    entries = []
    with open(FEEDBACK_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def get_feedback_summary() -> str:
    """Summarize feedback patterns for injection into prompts."""
    entries = load_feedback_corrections()
    if not entries:
        return ""

    wrong = [e for e in entries if e["feedback_type"] == "wrong"]
    correct = [e for e in entries if e["feedback_type"] == "correct"]

    if not wrong:
        return ""

    # Build correction hints from wrong attributions
    corrections = []
    for w in wrong[-5:]:  # Last 5 corrections
        corrections.append(f"- Spike #{w['spike_id']}: {w['details']}")

    return (
        "\nIMPORTANT CORRECTIONS FROM PAST MISTAKES:\n"
        + "\n".join(corrections)
        + "\nAvoid repeating these attribution errors.\n"
    )


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

def attribute_spike_v2(spike, all_recent_spikes=None,
                       entity_llm=None, filter_llm=None, reasoning_llm=None,
                       db=None) -> Dict:
    """
    Full 5-layer causal attribution pipeline.

    Args:
        spike: SpikeEvent to attribute
        all_recent_spikes: List of recent spikes for correlation detection
        entity_llm: function(prompt) -> str for Layer 1 entity extraction (Sonnet)
        filter_llm: function(prompt) -> str for Layer 3 (Sonnet)
        reasoning_llm: function(prompt) -> str for Layer 4 (Opus)
        db: PythiaDB instance for Layer 5 storage

    Returns:
        Structured attribution dict with cause, confidence, reasoning.
    """
    # Layer 1: Context (with LLM entity extraction)
    context = build_spike_context(spike, all_recent_spikes or [], entity_llm=entity_llm)
    logger.info("Context built: category=%s, entities=%s, correlated=%d",
                context["category"], context["entities"], len(context["correlated_spikes"]))

    # Layer 1.5: Counterfactual Validation (CausalImpact / z-score)
    # Tests whether spike is statistically significant before burning LLM credits
    statistical_validation = None
    try:
        from .counterfactual import validate_spike
        if db:
            statistical_validation = validate_spike(
                db=db,
                market_id=spike.market_id,
                spike_timestamp=spike.timestamp,
                spike_magnitude=spike.magnitude,
            )
            context["statistical_validation"] = statistical_validation

            if statistical_validation and not statistical_validation.get("is_significant", True):
                logger.info(
                    "Spike failed statistical validation (p=%.4f, method=%s) — skipping LLM attribution",
                    statistical_validation.get("p_value", 1.0),
                    statistical_validation.get("method", "unknown"),
                )
                return {
                    "spike_id": spike.id,
                    "context": context,
                    "statistical_validation": statistical_validation,
                    "attribution": {
                        "most_likely_cause": "Spike not statistically significant — within normal variance",
                        "confidence": "LOW",
                        "confidence_reasoning": f"CausalImpact p-value={statistical_validation.get('p_value', 'N/A')}, "
                                               f"method={statistical_validation.get('method', 'N/A')}",
                    },
                    "candidates_retrieved": 0,
                    "candidates_filtered": 0,
                    "top_candidates": [],
                    "filtered_by": "counterfactual_validation",
                    "timestamp": datetime.utcnow().isoformat(),
                }
    except ImportError:
        logger.debug("counterfactual module not available — skipping statistical validation")
    except Exception as e:
        logger.warning("Statistical validation failed (non-fatal): %s", e)

    # Layer 2: News Retrieval (NewsAPI + Google News + DDG + Reddit, temporally filtered)
    candidates = retrieve_candidate_news(context)
    logger.info("Retrieved %d candidate articles (temporally filtered)", len(candidates))

    # Layer 3: Filter (Sonnet)
    filtered = filter_candidates(context, candidates, llm_call=filter_llm)
    logger.info("Filtered to %d relevant articles", len(filtered))

    # Inject feedback corrections into reasoning prompt if available
    feedback_hint = get_feedback_summary()

    # Layer 4: Causal Reasoning (Opus)
    attribution = reason_about_cause(context, filtered, llm_call=reasoning_llm,
                                     extra_context=feedback_hint)
    logger.info("Attribution: %s (confidence: %s)",
                attribution.get("most_likely_cause", "?")[:60],
                attribution.get("confidence", "?"))

    # Layer 4.5: DoWhy Refutation (formal causal graph validation)
    dowhy_result = None
    try:
        from .causal_dag import estimate_causal_effect
        dowhy_result = estimate_causal_effect(context, db=db)
        if dowhy_result and dowhy_result.get("estimated_effect") is not None:
            logger.info(
                "DoWhy: effect=%.4f refutation=%s (category=%s)",
                dowhy_result["estimated_effect"],
                "PASSED" if dowhy_result.get("refutation_passed") else "FAILED",
                dowhy_result.get("dag_category", "?"),
            )
            # If refutation fails, downgrade confidence
            if not dowhy_result.get("refutation_passed", True):
                if attribution.get("confidence") == "HIGH":
                    attribution["confidence"] = "MEDIUM"
                    attribution["confidence_reasoning"] = (
                        (attribution.get("confidence_reasoning", "") +
                         " [DoWhy refutation test failed — downgraded from HIGH]")
                    )
    except ImportError:
        logger.debug("causal_dag module not available — skipping DoWhy validation")
    except Exception as e:
        logger.warning("DoWhy validation failed (non-fatal): %s", e)

    # Layer 4.6: Heterogeneous Effect Prediction (EconML)
    het_effect = None
    try:
        from .heterogeneous_effects import predict_effect
        het_effect = predict_effect(context)
        if het_effect and het_effect.get("predicted_effect") is not None:
            logger.info(
                "EconML: predicted=%.4f observed=%.4f anomaly=%s",
                het_effect["predicted_effect"],
                het_effect.get("observed_magnitude", 0),
                het_effect.get("anomaly_flag", "N/A"),
            )
            # Flag anomalous spike sizes in the attribution
            anomaly = het_effect.get("anomaly_flag", "")
            if anomaly in ("MUCH_LARGER_THAN_EXPECTED", "MUCH_SMALLER_THAN_EXPECTED"):
                attribution["size_anomaly"] = anomaly
                attribution["predicted_effect"] = het_effect["predicted_effect"]
    except ImportError:
        logger.debug("heterogeneous_effects module not available — skipping EconML")
    except Exception as e:
        logger.warning("EconML prediction failed (non-fatal): %s", e)

    # Layer 5: Package and store
    result = {
        "spike_id": spike.id,
        "context": context,
        "candidates_retrieved": len(candidates),
        "candidates_filtered": len(filtered),
        "top_candidates": filtered[:3],
        "attribution": attribution,
        "statistical_validation": context.get("statistical_validation"),
        "dowhy_validation": dowhy_result,
        "heterogeneous_effect": het_effect,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Save to DB if available
    if db:
        save_attribution_to_db(db, spike.id, result)

    return result


def attribute_spike_with_governance(spike, all_recent_spikes=None,
                                    entity_llm=None, filter_llm=None, reasoning_llm=None,
                                    db=None) -> Tuple[Dict, Optional[AuditTrail]]:
    """
    Governance-wrapped causal attribution pipeline.
    
    Implements:
    - Circuit breaker (cost limits, emergency shutdown)
    - Agent validation checkpoints
    - Confidence scoring at each layer
    - Audit trail generation
    - Final decision gate (AUTO_RELAY / FLAG_REVIEW / REJECT)
    
    Returns:
        (result_dict, audit_trail)
    """
    
    if not GOVERNANCE_AVAILABLE:
        logger.warning("Governance not available - running without compliance layer")
        result = attribute_spike_v2(spike, all_recent_spikes, entity_llm, filter_llm, reasoning_llm, db)
        return result, None
    
    # Initialize governance if not already done
    try:
        config, breaker, validator, exporter = get_governance()
    except RuntimeError:
        # Auto-initialize with defaults
        init_governance()
        config, breaker, validator, exporter = get_governance()
    
    # Create audit trail
    run_id = str(uuid.uuid4())
    trail = AuditTrail(
        run_id=run_id,
        market_id=spike.market_id,
        market_title=spike.market_title,
        start_time=datetime.now().isoformat()
    )
    
    try:
        # Circuit breaker check
        estimated_cost = 0.50  # Estimated cost per attribution run (Sonnet + Opus)
        allowed, reason = breaker.check_before_run(estimated_cost)
        if not allowed:
            logger.error("Attribution blocked by circuit breaker: %s", reason)
            trail.failed_checkpoint = "circuit_breaker"
            trail.finalize(0.0, "REJECT")
            if exporter:
                exporter.save_trail(trail)
            return {"error": reason, "decision": "REJECT"}, trail
        
        # Layer 1: Context Builder
        layer_start = time.time()
        context = build_spike_context(spike, all_recent_spikes or [], entity_llm=entity_llm)
        
        trail.add_action(AgentAction(
            timestamp=datetime.now().isoformat(),
            agent_role=AgentRole.CONTEXT_BUILDER.value,
            action_type="context_build",
            input_summary=f"Market: {spike.market_title[:50]}...",
            output_summary=f"Category: {context['category']}, Entities: {len(context['entities'])}",
            confidence_score=1.0,  # Deterministic keyword matching
            duration_ms=int((time.time() - layer_start) * 1000)
        ))
        
        logger.info("✓ Layer 1: Context built (category=%s, entities=%d)", 
                   context["category"], len(context["entities"]))
        
        # Layer 2: News Retrieval
        layer_start = time.time()
        candidates = retrieve_candidate_news(context)
        
        trail.add_action(AgentAction(
            timestamp=datetime.now().isoformat(),
            agent_role=AgentRole.NEWS_RETRIEVER.value,
            action_type="api_calls",
            input_summary=f"Entities: {context['entities'][:3]}",
            output_summary=f"Retrieved {len(candidates)} articles",
            confidence_score=0.9 if candidates else 0.3,  # High if articles found
            duration_ms=int((time.time() - layer_start) * 1000)
        ))
        
        # Validate news retrieval
        passed, failure = validator.validate_agent_output(
            AgentRole.NEWS_RETRIEVER,
            {'articles': candidates},
            0.9 if candidates else 0.3
        )
        if not passed:
            logger.warning("✗ Layer 2 validation failed: %s", failure)
            trail.failed_checkpoint = "news_retrieval"
            trail.finalize(0.0, "REJECT")
            if exporter:
                exporter.save_trail(trail)
            return {"error": failure, "decision": "REJECT"}, trail
        
        logger.info("✓ Layer 2: Retrieved %d candidates", len(candidates))
        
        # Layer 3: Candidate Filter (Sonnet)
        layer_start = time.time()
        filtered = filter_candidates(context, candidates, llm_call=filter_llm)
        
        # Extract filter confidence (if LLM provides it)
        filter_confidence = 0.8 if filtered else 0.5
        
        trail.add_action(AgentAction(
            timestamp=datetime.now().isoformat(),
            agent_role=AgentRole.CANDIDATE_FILTER.value,
            action_type="llm_call",
            input_summary=f"{len(candidates)} candidates",
            output_summary=f"{len(filtered)} filtered",
            confidence_score=filter_confidence,
            cost_usd=0.01,  # Approx Sonnet cost
            tokens_used=5000,  # Approx
            duration_ms=int((time.time() - layer_start) * 1000)
        ))
        
        # Validate filter output
        passed, failure = validator.validate_agent_output(
            AgentRole.CANDIDATE_FILTER,
            {'filtered_candidates': filtered},
            filter_confidence
        )
        if not passed:
            logger.warning("✗ Layer 3 validation failed: %s", failure)
            trail.failed_checkpoint = "candidate_filter"
            trail.finalize(filter_confidence, "REJECT")
            if exporter:
                exporter.save_trail(trail)
            return {"error": failure, "decision": "REJECT", "confidence": filter_confidence}, trail
        
        logger.info("✓ Layer 3: Filtered to %d articles (confidence: %.2f)", 
                   len(filtered), filter_confidence)
        
        # Layer 4: Causal Reasoning (Opus)
        layer_start = time.time()
        feedback_hint = get_feedback_summary()
        attribution = reason_about_cause(context, filtered, llm_call=reasoning_llm,
                                        extra_context=feedback_hint)
        
        # Extract reasoner confidence
        reasoner_confidence = attribution.get("confidence_score", 0.75)
        if isinstance(reasoner_confidence, str):
            # Parse "High (0.85)" or "85%" format
            import re
            match = re.search(r'(\d+\.?\d*)', reasoner_confidence)
            if match:
                reasoner_confidence = float(match.group(1))
                if reasoner_confidence > 1:
                    reasoner_confidence /= 100  # Convert 85 -> 0.85
        
        trail.add_action(AgentAction(
            timestamp=datetime.now().isoformat(),
            agent_role=AgentRole.CAUSAL_REASONER.value,
            action_type="llm_call",
            input_summary=f"{len(filtered)} candidates",
            output_summary=attribution.get("most_likely_cause", "")[:100],
            confidence_score=reasoner_confidence,
            cost_usd=0.15,  # Approx Opus cost
            tokens_used=15000,  # Approx
            duration_ms=int((time.time() - layer_start) * 1000)
        ))
        
        # Validate reasoning output
        passed, failure = validator.validate_agent_output(
            AgentRole.CAUSAL_REASONER,
            attribution,
            reasoner_confidence
        )
        if not passed:
            logger.warning("✗ Layer 4 validation failed: %s", failure)
            trail.failed_checkpoint = "causal_reasoning"
            trail.finalize(reasoner_confidence, "REJECT")
            if exporter:
                exporter.save_trail(trail)
            return {"error": failure, "decision": "REJECT", "confidence": reasoner_confidence}, trail
        
        logger.info("✓ Layer 4: Reasoning complete (confidence: %.2f)", reasoner_confidence)
        
        # Layer 5: Store & Learn
        layer_start = time.time()
        result = {
            "spike_id": spike.id,
            "context": context,
            "candidates_retrieved": len(candidates),
            "candidates_filtered": len(filtered),
            "top_candidates": filtered[:3],
            "attribution": attribution,
            "timestamp": datetime.utcnow().isoformat(),
            "filter_confidence": filter_confidence,
            "reasoner_confidence": reasoner_confidence,
            "governance": {
                "run_id": run_id,
                "total_cost": trail.total_cost_usd,
                "total_tokens": trail.total_tokens,
            }
        }
        
        if db:
            save_attribution_to_db(db, spike.id, result)
        
        trail.add_action(AgentAction(
            timestamp=datetime.now().isoformat(),
            agent_role=AgentRole.STORAGE_LEARNER.value,
            action_type="db_write",
            input_summary="Attribution result",
            output_summary="Saved to DB",
            confidence_score=1.0,
            duration_ms=int((time.time() - layer_start) * 1000)
        ))
        
        logger.info("✓ Layer 5: Stored to database")
        
        # Final decision gate
        final_confidence = reasoner_confidence  # Use reasoner as primary
        decision, reason = validator.validate_final_output(
            final_confidence,
            filter_confidence,
            reasoner_confidence
        )
        
        result["decision"] = decision
        result["decision_reason"] = reason
        result["final_confidence"] = final_confidence
        
        # Finalize audit trail
        trail.finalize(final_confidence, decision)
        trail.passed_all_checkpoints = (decision != "REJECT")
        
        # Record cost in circuit breaker
        breaker.record_run(trail.total_cost_usd)
        
        # Save audit trail
        if exporter:
            exporter.save_trail(trail)
        
        logger.info("═" * 60)
        logger.info("FINAL DECISION: %s (confidence: %.2f)", decision, final_confidence)
        logger.info("Reason: %s", reason)
        logger.info("Cost: $%.4f | Tokens: %d | Duration: %.1fs",
                   trail.total_cost_usd, trail.total_tokens, trail.total_duration_ms / 1000)
        logger.info("═" * 60)
        
        return result, trail
        
    except Exception as e:
        logger.error("Attribution failed with error: %s", e, exc_info=True)
        trail.failed_checkpoint = "exception"
        trail.finalize(0.0, "REJECT")
        if exporter:
            exporter.save_trail(trail)
        return {"error": str(e), "decision": "REJECT"}, trail


# ---------------------------------------------------------------------------
# CLI for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Pythia Causal Analysis v2")
    parser.add_argument("--test", action="store_true", help="Run test attribution")
    parser.add_argument("--market", default="Will the Fed raise rates in March 2025?")
    args = parser.parse_args()

    if args.test:
        # Create a mock spike for testing
        from dataclasses import dataclass
        
        @dataclass
        class MockSpike:
            id: int = 1
            market_id: str = "test"
            market_title: str = ""
            timestamp: str = ""
            direction: str = "up"
            magnitude: float = 0.12
            price_before: float = 0.45
            price_after: float = 0.57
            volume_at_spike: float = 50000
            asset_class: str = ""
            attributed_events: list = field(default_factory=list)
            manual_tag: str = ""
            asset_reaction: dict = field(default_factory=dict)

        spike = MockSpike(
            market_title=args.market,
            timestamp=datetime.utcnow().isoformat(),
        )

        print(f"Testing causal analysis for: {spike.market_title}")
        print(f"Spike: {spike.direction} {spike.magnitude:.1%}")
        print()

        # Run without LLM (news retrieval only)
        result = attribute_spike_v2(spike)

        print(f"Candidates retrieved: {result['candidates_retrieved']}")
        print(f"Candidates after filter: {result['candidates_filtered']}")
        print()
        print("Top candidates:")
        for c in result["top_candidates"][:5]:
            print(f"  • [{c.get('source', '?')}] {c['headline'][:80]}")
        print()
        print(f"Attribution: {result['attribution'].get('most_likely_cause', 'N/A')}")
        print(f"Confidence: {result['attribution'].get('confidence', 'N/A')}")
