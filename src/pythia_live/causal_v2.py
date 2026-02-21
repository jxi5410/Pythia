#!/usr/bin/env python3
"""
Pythia Causal Analysis v2 — 5-layer attribution pipeline.

Layer 1: Context Builder (free)
Layer 2: News Retrieval (free APIs)
Layer 3: Candidate Filter (Sonnet — fast relevance scoring)
Layer 4: Causal Reasoning (Opus — deep analysis)
Layer 5: Store & Learn (local DB)
"""

import json
import logging
import re
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote_plus, urlparse, unquote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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
    # Remove common filler
    stop_words = {"will", "the", "be", "in", "by", "of", "a", "an", "to", "for", "on", "is", "at", "this", "that", "it"}
    words = re.sub(r'[?!.,]', '', title).split()
    entities = [w for w in words if w.lower() not in stop_words and len(w) > 2]
    return entities[:5]


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


def build_spike_context(spike, all_recent_spikes=None) -> Dict:
    """Build full context for a spike before attribution."""
    ts = spike.timestamp
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)

    correlated = find_concurrent_spikes(spike, all_recent_spikes or [], window_hours=2)

    return {
        "market_title": spike.market_title,
        "category": classify_market(spike.market_title),
        "entities": extract_entities_simple(spike.market_title),
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
    """
    entities = context["entities"]
    category = context["category"]

    # Build targeted search queries
    entity_query = " ".join(entities[:3])
    category_query = f"{entity_query} {category.replace('_', ' ')}"

    candidates = []

    # Source 1: Google News RSS
    candidates += google_news_rss(entity_query, max_results=8)

    # Source 2: DuckDuckGo (broader search)
    candidates += duckduckgo_search(category_query, max_results=5)

    # Source 3: Reddit (discussion/sentiment)
    subreddit = SUBREDDIT_MAP.get(category, "news")
    candidates += reddit_search(entity_query, subreddit=subreddit, max_results=5)

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


def reason_about_cause(context: Dict, candidates: List[Dict], llm_call=None) -> Dict:
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
    prompt = CAUSAL_PROMPT.format(
        market_title=context["market_title"],
        category=context["category"],
        direction=spike["direction"],
        magnitude=spike["magnitude"],
        price_before=spike["price_before"],
        price_after=spike["price_after"],
        timestamp=spike["timestamp"],
        volume=spike["volume"],
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
# Layer 5: Full Pipeline
# ---------------------------------------------------------------------------

def attribute_spike_v2(spike, all_recent_spikes=None, 
                       filter_llm=None, reasoning_llm=None) -> Dict:
    """
    Full 5-layer causal attribution pipeline.
    
    Args:
        spike: SpikeEvent to attribute
        all_recent_spikes: List of recent spikes for correlation detection
        filter_llm: function(prompt) -> str for Layer 3 (Sonnet)
        reasoning_llm: function(prompt) -> str for Layer 4 (Opus)
    
    Returns:
        Structured attribution dict with cause, confidence, reasoning.
    """
    # Layer 1: Context
    context = build_spike_context(spike, all_recent_spikes or [])
    logger.info("Context built: category=%s, entities=%s, correlated=%d",
                context["category"], context["entities"], len(context["correlated_spikes"]))

    # Layer 2: News Retrieval
    candidates = retrieve_candidate_news(context)
    logger.info("Retrieved %d candidate articles", len(candidates))

    # Layer 3: Filter (Sonnet)
    filtered = filter_candidates(context, candidates, llm_call=filter_llm)
    logger.info("Filtered to %d relevant articles", len(filtered))

    # Layer 4: Causal Reasoning (Opus)
    attribution = reason_about_cause(context, filtered, llm_call=reasoning_llm)
    logger.info("Attribution: %s (confidence: %s)",
                attribution.get("most_likely_cause", "?")[:60],
                attribution.get("confidence", "?"))

    # Layer 5: Package result
    result = {
        "spike_id": spike.id,
        "context": context,
        "candidates_retrieved": len(candidates),
        "candidates_filtered": len(filtered),
        "top_candidates": filtered[:3],
        "attribution": attribution,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return result


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
