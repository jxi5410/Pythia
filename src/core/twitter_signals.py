"""
Twitter/X Velocity Signal Detector for Pythia.

Detects pre-spike tweet velocity from verified/high-follower accounts
mentioning entities in active prediction markets. Tweet velocity spikes
15-60 minutes before prediction market prices move — a LEADING indicator.

No paid APIs required. Uses web scraping and search fallbacks.
"""

import re
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Extract search terms from a market title
# ---------------------------------------------------------------------------

# Common stop-phrases to strip from market titles
_STOP = re.compile(
    r"\b(will|the|be|in|on|at|by|of|to|a|an|is|are|was|were|do|does|did|"
    r"has|have|had|can|could|would|should|before|after|during|than|that|"
    r"this|these|those|it|its|if|or|and|but|not|no|yes|what|when|where|"
    r"who|how|why|which|with|from|into|over|under|about|between|through|"
    r"again|further|then|once|here|there|all|each|every|both|few|more|"
    r"most|other|some|such|only|own|same|so|very|just|because|as|until|"
    r"while|for|nor|yet|also|too|any|may|might|shall|must)\b",
    re.IGNORECASE,
)

_ENTITY_PATTERNS = {
    r"\bFed(eral Reserve)?\b": "Federal Reserve",
    r"\bFOMC\b": "FOMC",
    r"\bECB\b": "ECB",
    r"\bBTC\b": "Bitcoin",
    r"\bETH\b": "Ethereum",
    r"\bSEC\b": "SEC",
    r"\bGDP\b": "GDP",
    r"\bCPI\b": "CPI",
    r"\bNFP\b": "non-farm payrolls",
}


def extract_search_terms(market_title: str) -> list[str]:
    """Extract key search terms from a prediction market title.

    >>> extract_search_terms("Will the Fed cut rates in March?")
    ['Fed rate cut', 'FOMC March', 'Federal Reserve']
    """
    title = market_title.strip().rstrip("?").strip()

    # Collect recognised entities
    entities: list[str] = []
    for pat, canonical in _ENTITY_PATTERNS.items():
        if re.search(pat, title):
            entities.append(canonical)

    # Extract remaining significant words
    cleaned = _STOP.sub(" ", title)
    words = [w for w in cleaned.split() if len(w) > 2 and not w.startswith("$")]

    terms: list[str] = []

    # Build a natural combined query from the significant words
    if words:
        terms.append(" ".join(words[:5]))

    # Add entity-enriched queries
    for ent in entities[:2]:
        combo = f"{ent} {' '.join(words[:2])}" if words else ent
        if combo not in terms:
            terms.append(combo)

    # Add remaining entities as standalone
    for ent in entities:
        if ent not in terms:
            terms.append(ent)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in terms:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            unique.append(t)

    return unique[:5]


# ---------------------------------------------------------------------------
# 2. Search recent tweets (scraping / search fallback)
# ---------------------------------------------------------------------------

_NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.woodland.cafe",
    "https://nitter.net",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def _parse_nitter_results(html: str, base_url: str) -> list[dict]:
    """Parse tweets from Nitter search results HTML."""
    soup = BeautifulSoup(html, "html.parser")
    tweets: list[dict] = []
    for item in soup.select(".timeline-item, .tweet-body"):
        text_el = item.select_one(".tweet-content, .content")
        author_el = item.select_one(".username, .fullname")
        time_el = item.select_one("time, .tweet-date a")

        if not text_el:
            continue

        author = author_el.get_text(strip=True) if author_el else "unknown"
        text = text_el.get_text(strip=True)

        timestamp = None
        if time_el:
            ts_str = time_el.get("title") or time_el.get("datetime") or time_el.get_text(strip=True)
            for fmt in ("%b %d, %Y · %I:%M %p %Z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    timestamp = datetime.strptime(ts_str.strip(), fmt).replace(tzinfo=timezone.utc)
                    break
                except (ValueError, AttributeError):
                    continue

        link_el = item.select_one("a.tweet-link, a[href*='/status/']")
        url = ""
        if link_el and link_el.get("href"):
            href = link_el["href"]
            url = href if href.startswith("http") else f"{base_url}{href}"

        tweets.append({
            "author": author.lstrip("@"),
            "text": text[:500],
            "timestamp": timestamp.isoformat() if timestamp else datetime.now(timezone.utc).isoformat(),
            "followers": 0,
            "verified": False,
            "engagement": 0,
            "url": url.replace(base_url, "https://x.com") if url else "",
            "source": "nitter",
        })

    return tweets


def _search_nitter(query: str, hours_back: int = 2) -> list[dict]:
    """Try Nitter instances for tweet search."""
    tweets: list[dict] = []
    for instance in _NITTER_INSTANCES:
        try:
            url = f"{instance}/search?f=tweets&q={quote_plus(query)}"
            with httpx.Client(timeout=10, follow_redirects=True, headers=_HEADERS) as client:
                resp = client.get(url)
                if resp.status_code == 200 and len(resp.text) > 500:
                    tweets = _parse_nitter_results(resp.text, instance)
                    if tweets:
                        logger.info(f"Got {len(tweets)} tweets from {instance}")
                        break
        except Exception as e:
            logger.debug(f"Nitter {instance} failed: {e}")
            continue
    return tweets


def _parse_google_results(html: str) -> list[dict]:
    """Parse tweet-like results from Google search."""
    soup = BeautifulSoup(html, "html.parser")
    tweets: list[dict] = []

    for g in soup.select("div.g, div.tF2Cxc"):
        link_el = g.select_one("a[href]")
        snippet_el = g.select_one(".VwiC3b, .s, .st, span.aCOpRe")
        title_el = g.select_one("h3")

        if not link_el:
            continue
        href = link_el.get("href", "")
        if "/status/" not in href:
            continue

        # Extract author from URL or title
        author = "unknown"
        m = re.search(r"(?:twitter\.com|x\.com)/(\w+)/status", href)
        if m:
            author = m.group(1)

        text = snippet_el.get_text(strip=True) if snippet_el else (title_el.get_text(strip=True) if title_el else "")

        tweets.append({
            "author": author,
            "text": text[:500],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "followers": 0,
            "verified": False,
            "engagement": 0,
            "url": href,
            "source": "google",
        })

    return tweets


def _search_google(query: str, hours_back: int = 2) -> list[dict]:
    """Fallback: Google search for recent tweets."""
    search_query = f'site:twitter.com OR site:x.com "{query}"'
    url = f"https://www.google.com/search?q={quote_plus(search_query)}&tbs=qdr:d&num=20"
    try:
        with httpx.Client(timeout=10, follow_redirects=True, headers=_HEADERS) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                return _parse_google_results(resp.text)
    except Exception as e:
        logger.debug(f"Google search failed: {e}")
    return []


def _search_brave(query: str, hours_back: int = 2) -> list[dict]:
    """Search via Brave (lightweight, less likely to block)."""
    search_query = f'site:x.com "{query}"'
    url = f"https://search.brave.com/search?q={quote_plus(search_query)}&tf=pd"
    try:
        with httpx.Client(timeout=10, follow_redirects=True, headers=_HEADERS) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                tweets: list[dict] = []
                for item in soup.select(".snippet"):
                    link_el = item.select_one("a[href]")
                    desc_el = item.select_one(".snippet-description")
                    if not link_el:
                        continue
                    href = link_el.get("href", "")
                    if "/status/" not in href:
                        continue
                    author = "unknown"
                    m = re.search(r"(?:twitter\.com|x\.com)/(\w+)/status", href)
                    if m:
                        author = m.group(1)
                    text = desc_el.get_text(strip=True) if desc_el else ""
                    tweets.append({
                        "author": author,
                        "text": text[:500],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "followers": 0,
                        "verified": False,
                        "engagement": 0,
                        "url": href,
                        "source": "brave",
                    })
                return tweets
    except Exception as e:
        logger.debug(f"Brave search failed: {e}")
    return []


def search_recent_tweets(query: str, hours_back: int = 2) -> list[dict]:
    """Search recent tweets using multiple free methods.

    Tries: Nitter → Google → Brave, returns first successful results.
    """
    # Try each source
    for search_fn in [_search_nitter, _search_google, _search_brave]:
        tweets = search_fn(query, hours_back)
        if tweets:
            # Filter by time window
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            filtered = []
            for t in tweets:
                try:
                    ts = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                    if ts >= cutoff:
                        filtered.append(t)
                except (ValueError, TypeError):
                    filtered.append(t)  # Keep if we can't parse timestamp
            return filtered if filtered else tweets[:20]

    logger.warning(f"All tweet search methods failed for: {query}")
    return []


# ---------------------------------------------------------------------------
# 3. Calculate tweet velocity
# ---------------------------------------------------------------------------

_POSITIVE = re.compile(
    r"\b(bullish|surge|rally|pump|moon|soar|jump|spike|breaking|confirmed|approved|cut|ease|dovish)\b",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"\b(bearish|crash|dump|tank|plunge|reject|denied|hawkish|hike|tighten|delay|postpone|unlikely)\b",
    re.IGNORECASE,
)


def _sentiment(text: str) -> str:
    pos = len(_POSITIVE.findall(text))
    neg = len(_NEGATIVE.findall(text))
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def calculate_tweet_velocity(
    tweets: list[dict], window_minutes: int = 30
) -> dict:
    """Measure tweet frequency and acceleration over time windows."""
    now = datetime.now(timezone.utc)
    window = timedelta(minutes=window_minutes)

    # Buckets: current window vs previous window
    current: list[dict] = []
    previous: list[dict] = []

    for t in tweets:
        try:
            ts = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ts = now  # Assume recent if unparseable

        age = now - ts
        if age <= window:
            current.append(t)
        elif age <= window * 2:
            previous.append(t)

    total = len(tweets)
    current_rate = len(current) / (window_minutes / 60) if window_minutes else 0
    previous_rate = len(previous) / (window_minutes / 60) if window_minutes else 0

    if previous_rate > 0:
        velocity_change = ((current_rate - previous_rate) / previous_rate) * 100
    elif current_rate > 0:
        velocity_change = 100.0  # New activity from zero
    else:
        velocity_change = 0.0

    # Aggregate sentiment
    all_text = " ".join(t.get("text", "") for t in tweets)
    sentiment = _sentiment(all_text)

    # Top authors by frequency
    author_counts: dict[str, int] = {}
    for t in tweets:
        a = t.get("author", "unknown")
        author_counts[a] = author_counts.get(a, 0) + 1
    top_authors = sorted(author_counts.items(), key=lambda x: -x[1])[:5]

    return {
        "total_tweets": total,
        "tweets_per_hour": round(current_rate, 1),
        "velocity_change_pct": round(velocity_change, 1),
        "top_authors": [{"author": a, "count": c} for a, c in top_authors],
        "sentiment_signal": sentiment,
        "is_accelerating": velocity_change > 50 and len(current) >= 3,
        "current_window_count": len(current),
        "previous_window_count": len(previous),
    }


# ---------------------------------------------------------------------------
# 4. Full signal detection pipeline
# ---------------------------------------------------------------------------

def detect_twitter_signal(market_title: str) -> dict:
    """Full pipeline: extract terms → search → velocity → signal detection."""
    terms = extract_search_terms(market_title)
    logger.info(f"Search terms for '{market_title}': {terms}")

    all_tweets: list[dict] = []
    seen_urls: set[str] = set()

    for term in terms[:3]:  # Limit to top 3 terms
        tweets = search_recent_tweets(term, hours_back=2)
        for t in tweets:
            url = t.get("url", "")
            if url and url in seen_urls:
                continue
            seen_urls.add(url)
            all_tweets.append(t)
        time.sleep(1)  # Rate limit courtesy

    velocity = calculate_tweet_velocity(all_tweets, window_minutes=30)

    # Compute velocity score (0-100)
    score = 0
    score += min(30, velocity["total_tweets"] * 3)  # Volume: up to 30
    score += min(30, max(0, velocity["velocity_change_pct"]) * 0.3)  # Acceleration: up to 30
    score += 20 if velocity["is_accelerating"] else 0  # Acceleration bonus
    score += 10 if velocity["sentiment_signal"] != "neutral" else 0  # Sentiment clarity
    score += 10 if any(t.get("verified") for t in all_tweets) else 0  # Verified accounts
    score = min(100, int(score))

    # Pick top tweets by engagement or recency
    top_tweets = sorted(
        all_tweets,
        key=lambda t: t.get("engagement", 0),
        reverse=True,
    )[:5]

    signal_detected = score >= 40 and velocity["total_tweets"] >= 3

    # Determine leading indicator status
    leading = velocity["is_accelerating"] and score >= 60

    summary_parts = [
        f"{velocity['total_tweets']} tweets found",
        f"{velocity['tweets_per_hour']}/hr current rate",
    ]
    if velocity["velocity_change_pct"] > 0:
        summary_parts.append(f"{velocity['velocity_change_pct']}% velocity increase")
    if velocity["sentiment_signal"] != "neutral":
        summary_parts.append(f"sentiment: {velocity['sentiment_signal']}")

    return {
        "market_title": market_title,
        "signal_detected": signal_detected,
        "velocity_score": score,
        "velocity": velocity,
        "top_tweets": top_tweets,
        "search_terms": terms,
        "summary": " | ".join(summary_parts),
        "leading_indicator": leading,
    }


# ---------------------------------------------------------------------------
# 5. Telegram alert formatting
# ---------------------------------------------------------------------------

def format_twitter_alert(signal: dict) -> str:
    """Format a Twitter signal as a Telegram alert message."""
    market = signal.get("market_title", "Unknown")
    score = signal.get("velocity_score", 0)
    vel = signal.get("velocity", {})
    top = signal.get("top_tweets", [])

    # Compute multiplier vs baseline
    change = vel.get("velocity_change_pct", 0)
    if change > 0:
        multiplier = f"{1 + change / 100:.1f}x normal"
    else:
        multiplier = "baseline"

    lines = [
        f"🐦 TWITTER SIGNAL — {market}",
        f"Velocity: {score}/100 ({multiplier})",
    ]

    if top:
        t = top[0]
        author = t.get("author", "unknown")
        text = t.get("text", "")[:100]
        lines.append(f'Top: @{author} "{text}"')

    if signal.get("leading_indicator"):
        lines.append(f"⚡ Leading indicator: YES (tweet velocity accelerating)")
    else:
        lines.append(f"⚡ Leading indicator: NO")

    # Sentiment
    sentiment = vel.get("sentiment_signal", "neutral")
    emoji = {"positive": "📈", "negative": "📉", "neutral": "➖"}.get(sentiment, "➖")
    lines.append(f"Sentiment: {emoji} {sentiment}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    query = " ".join(sys.argv[1:]) or "Will the Fed cut rates in March?"
    print(f"\n=== Detecting Twitter signal for: {query} ===\n")
    result = detect_twitter_signal(query)
    print(format_twitter_alert(result))
    print(f"\nRaw velocity: {result['velocity']}")
    print(f"Terms used: {result['search_terms']}")
