"""
Weibo Velocity Signal Detector for Pythia — China's Twitter equivalent.

Uses m.weibo.cn mobile API (no auth needed for search) to detect
social velocity spikes on China-related prediction market topics.
"""

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bilingual term mappings
# ---------------------------------------------------------------------------

TERM_MAP: dict[str, str] = {
    "tariffs": "关税",
    "tariff": "关税",
    "Fed": "美联储",
    "Federal Reserve": "美联储",
    "rate cut": "降息",
    "rate hike": "加息",
    "interest rate": "利率",
    "trade war": "贸易战",
    "Taiwan": "台湾",
    "Xi Jinping": "习近平",
    "Xi": "习近平",
    "tech regulation": "科技监管",
    "Huawei": "华为",
    "semiconductor": "半导体",
    "chip": "芯片",
    "PBOC": "央行",
    "central bank": "央行",
    "real estate": "房地产",
    "property": "房地产",
    "Evergrande": "恒大",
    "BYD": "比亚迪",
    "defense": "国防",
    "military": "军事",
    "South China Sea": "南海",
    "sanctions": "制裁",
    "stimulus": "刺激",
    "GDP": "GDP",
    "inflation": "通胀",
    "deflation": "通缩",
    "unemployment": "失业",
    "export": "出口",
    "import": "进口",
    "stock market": "股市",
    "A-shares": "A股",
    "Hong Kong": "香港",
    "Alibaba": "阿里巴巴",
    "Tencent": "腾讯",
    "Tesla": "特斯拉",
    "Trump": "特朗普",
    "Biden": "拜登",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://m.weibo.cn/",
}

# Simple TTL cache: {key: (data, expiry_ts)}
_cache: dict[str, tuple] = {}
_CACHE_TTL = 300  # 5 minutes


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and entry[1] > time.time():
        return entry[0]
    return None


def _cache_set(key: str, data, ttl: int = _CACHE_TTL):
    _cache[key] = (data, time.time() + ttl)


# ---------------------------------------------------------------------------
# Weibo search
# ---------------------------------------------------------------------------

def search_weibo(query: str, hours_back: int = 4) -> list[dict]:
    """Search Weibo via m.weibo.cn mobile API. No auth needed."""
    cache_key = f"weibo:{query}:{hours_back}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    posts: list[dict] = []

    try:
        url = f"https://m.weibo.cn/api/container/getIndex"
        params = {
            "containerid": f"100103type=1&q={quote_plus(query)}",
            "page_type": "searchall",
            "page": 1,
        }
        with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
            for page in range(1, 4):  # Max 3 pages
                params["page"] = page
                resp = client.get(url, params=params)
                if resp.status_code != 200:
                    logger.warning("Weibo search returned %d for '%s'", resp.status_code, query)
                    break

                data = resp.json()
                cards = data.get("data", {}).get("cards", [])
                if not cards:
                    break

                for card in cards:
                    if card.get("card_type") != 9:
                        # card_group sometimes nests results
                        for sub in card.get("card_group", []):
                            if sub.get("card_type") == 9:
                                _parse_weibo_card(sub, posts, cutoff)
                        continue
                    _parse_weibo_card(card, posts, cutoff)

                time.sleep(0.5)  # Rate limiting

    except Exception as e:
        logger.error("Weibo search failed for '%s': %s", query, e)

    _cache_set(cache_key, posts)
    return posts


def _parse_weibo_card(card: dict, posts: list[dict], cutoff: datetime):
    """Parse a single Weibo card into a post dict."""
    mblog = card.get("mblog", {})
    if not mblog:
        return

    # Parse timestamp
    created = mblog.get("created_at", "")
    ts = _parse_weibo_time(created)
    if ts and ts < cutoff:
        return

    # Strip HTML from text
    text = re.sub(r"<[^>]+>", "", mblog.get("text", ""))

    user = mblog.get("user", {})
    mid = mblog.get("mid", mblog.get("id", ""))

    posts.append({
        "author": user.get("screen_name", "unknown"),
        "author_followers": user.get("followers_count", 0),
        "text": text,
        "timestamp": ts.isoformat() if ts else created,
        "reposts": mblog.get("reposts_count", 0),
        "comments": mblog.get("comments_count", 0),
        "likes": mblog.get("attitudes_count", 0),
        "url": f"https://m.weibo.cn/detail/{mid}",
    })


def _parse_weibo_time(s: str) -> Optional[datetime]:
    """Parse Weibo's various time formats."""
    if not s:
        return None
    now = datetime.now(timezone.utc)

    # "刚刚" = just now
    if "刚刚" in s:
        return now
    # "X分钟前" = X minutes ago
    m = re.search(r"(\d+)\s*分钟前", s)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    # "X小时前" = X hours ago
    m = re.search(r"(\d+)\s*小时前", s)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    # "今天 HH:MM"
    m = re.search(r"今天\s*(\d{2}):(\d{2})", s)
    if m:
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0) - timedelta(hours=8)  # CST→UTC
    # Standard formats
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Bilingual search
# ---------------------------------------------------------------------------

def search_weibo_bilingual(market_title: str) -> list[dict]:
    """Search Weibo using both English and Chinese terms from market title."""
    queries = _extract_bilingual_queries(market_title)
    all_posts: list[dict] = []
    seen_urls: set[str] = set()

    for q in queries[:4]:  # Limit to 4 queries
        posts = search_weibo(q)
        for p in posts:
            if p["url"] not in seen_urls:
                seen_urls.add(p["url"])
                all_posts.append(p)

    # Sort by engagement
    all_posts.sort(key=lambda p: p.get("reposts", 0) + p.get("comments", 0), reverse=True)
    return all_posts


def _extract_bilingual_queries(title: str) -> list[str]:
    """Extract search queries in both English and Chinese from a market title."""
    queries: list[str] = []
    title_lower = title.lower()

    # Find matching Chinese terms
    for eng, chn in TERM_MAP.items():
        if eng.lower() in title_lower:
            queries.append(chn)

    # Also search key English terms
    # Strip common stop words
    stop = {"will", "the", "be", "in", "on", "at", "by", "of", "to", "a", "an",
            "is", "are", "before", "after", "what", "when", "how", "yes", "no"}
    words = [w for w in re.findall(r"[A-Z][a-z]+|[A-Z]{2,}", title) if w.lower() not in stop]
    if words:
        queries.append(" ".join(words[:3]))

    # Deduplicate
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique if unique else [title[:30]]


# ---------------------------------------------------------------------------
# Velocity calculation
# ---------------------------------------------------------------------------

def calculate_weibo_velocity(posts: list[dict], window_minutes: int = 30) -> dict:
    """Calculate post velocity within a time window, same pattern as twitter_signals.py."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_minutes)
    baseline_start = now - timedelta(minutes=window_minutes * 4)

    recent = []
    baseline = []

    for p in posts:
        ts = p.get("timestamp", "")
        if isinstance(ts, str):
            try:
                t = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                continue
        else:
            t = ts

        if not t:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)

        if t >= window_start:
            recent.append(p)
        elif t >= baseline_start:
            baseline.append(p)

    recent_count = len(recent)
    baseline_rate = len(baseline) / 3.0 if baseline else 0  # per window

    velocity_ratio = (recent_count / max(baseline_rate, 0.5)) if baseline_rate > 0 else recent_count

    # Engagement-weighted velocity
    recent_engagement = sum(p.get("reposts", 0) + p.get("comments", 0) for p in recent)
    baseline_engagement = sum(p.get("reposts", 0) + p.get("comments", 0) for p in baseline)
    baseline_eng_rate = baseline_engagement / 3.0 if baseline_engagement else 0
    engagement_ratio = (recent_engagement / max(baseline_eng_rate, 1.0)) if baseline_eng_rate > 0 else 0

    return {
        "recent_count": recent_count,
        "baseline_rate": round(baseline_rate, 2),
        "velocity_ratio": round(velocity_ratio, 2),
        "engagement_ratio": round(engagement_ratio, 2),
        "recent_engagement": recent_engagement,
        "total_posts": len(posts),
        "window_minutes": window_minutes,
        "is_spike": velocity_ratio >= 3.0 or (velocity_ratio >= 2.0 and engagement_ratio >= 3.0),
    }


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def detect_weibo_signal(market_title: str) -> dict:
    """Full pipeline: bilingual search → velocity → signal detection."""
    posts = search_weibo_bilingual(market_title)
    velocity = calculate_weibo_velocity(posts)

    signal = {
        "source": "weibo",
        "market_title": market_title,
        "total_posts": len(posts),
        "velocity": velocity,
        "is_signal": velocity.get("is_spike", False),
        "top_posts": posts[:5],
        "queries_used": _extract_bilingual_queries(market_title),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if velocity.get("is_spike"):
        signal["confidence"] = min(0.9, 0.5 + velocity["velocity_ratio"] * 0.1)
        signal["description"] = (
            f"Weibo velocity spike: {velocity['velocity_ratio']}x normal rate "
            f"({velocity['recent_count']} posts in {velocity['window_minutes']}min)"
        )
        logger.info("🇨🇳 Weibo signal for '%s': %s", market_title, signal["description"])

    return signal
