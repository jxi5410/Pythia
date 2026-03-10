"""
Master China Signal Orchestrator for Pythia.

Coordinates all China-specific signal sources:
- Weibo social velocity
- PBOC policy stance
- NBS economic calendar
- China/HK equity correlation
- HKEx insider disclosures

China is the highest-value region for information asymmetry:
Western traders can't access Chinese-language sources.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from .china_weibo import detect_weibo_signal
from .china_pboc import detect_pboc_signal, format_pboc_alert
from .china_economic import (
    fetch_nbs_calendar,
    fetch_latest_china_data,
    match_china_events_to_markets,
    format_china_macro_alert,
)
from .china_equities import correlate_china_spike, get_china_tickers
from .china_insider import fetch_hkex_insider_deals, match_insider_to_markets, format_insider_alert

logger = logging.getLogger(__name__)

# Keywords that indicate a market is China-related
_CHINA_KEYWORDS = [
    "china", "chinese", "pboc", "renminbi", "rmb", "yuan", "cny",
    "tariff", "trade war", "xi jinping", "beijing", "stimulus",
    "real estate", "property", "evergrande", "byd", "huawei",
    "semiconductor", "taiwan", "south china sea", "hong kong",
    "alibaba", "tencent", "baidu", "nio", "xpeng",
    "smic", "country garden", "vanke",
]


def _is_china_related(market: dict) -> bool:
    """Check if a prediction market is China-related."""
    text = (
        market.get("title", "") + " " +
        market.get("question", "") + " " +
        market.get("description", "")
    ).lower()
    return any(kw in text for kw in _CHINA_KEYWORDS)


def detect_china_signals(active_markets: list[dict] = None) -> list[dict]:
    """
    Full pipeline across all China sources.

    Returns list of signal dicts, each with:
    - source: str (weibo, pboc, economic, equities, insider)
    - is_signal: bool
    - confidence: float
    - description: str
    - details: dict
    """
    signals: list[dict] = []
    active_markets = active_markets or []

    # Filter to China-related markets
    china_markets = [m for m in active_markets if _is_china_related(m)]

    # 1. Weibo velocity signals for each China market
    for market in china_markets[:5]:  # Limit to avoid rate limits
        try:
            weibo_sig = detect_weibo_signal(market.get("title", ""))
            if weibo_sig.get("is_signal"):
                signals.append({
                    "source": "weibo",
                    "is_signal": True,
                    "confidence": weibo_sig.get("confidence", 0.5),
                    "description": weibo_sig.get("description", "Weibo velocity spike"),
                    "market": market,
                    "details": weibo_sig,
                })
        except Exception as e:
            logger.error("Weibo signal failed for '%s': %s", market.get("title"), e)

    # 2. PBOC policy signals
    try:
        pboc_sig = detect_pboc_signal(active_markets)
        if pboc_sig.get("is_signal"):
            for match in pboc_sig.get("matches", []):
                signals.append({
                    "source": "pboc",
                    "is_signal": True,
                    "confidence": match.get("confidence", 0.5),
                    "description": match.get("mispricing", "PBOC policy signal"),
                    "market": {"title": match.get("market", "")},
                    "details": pboc_sig,
                })
    except Exception as e:
        logger.error("PBOC signal failed: %s", e)

    # 3. Economic calendar — upcoming high-impact releases
    try:
        calendar = fetch_nbs_calendar(days_ahead=3)
        high_impact = [e for e in calendar if e.get("importance", 0) >= 3]

        if high_impact and china_markets:
            matches = match_china_events_to_markets(high_impact, china_markets)
            for match in matches:
                signals.append({
                    "source": "economic",
                    "is_signal": True,
                    "confidence": 0.6,
                    "description": f"Upcoming: {match['event'].get('indicator')} on {match['event'].get('date')}",
                    "market": match.get("market", {}),
                    "details": match,
                })
    except Exception as e:
        logger.error("Economic calendar signal failed: %s", e)

    # 4. HKEx insider activity
    try:
        deals = fetch_hkex_insider_deals(days_back=3)
        if deals and china_markets:
            insider_matches = match_insider_to_markets(deals, china_markets)
            for match in insider_matches:
                signals.append({
                    "source": "insider",
                    "is_signal": True,
                    "confidence": 0.55,
                    "description": f"Insider activity at {match.get('company', 'unknown')}",
                    "market": match.get("market", {}),
                    "details": match,
                })
    except Exception as e:
        logger.error("Insider signal failed: %s", e)

    # Sort by confidence
    signals.sort(key=lambda s: s.get("confidence", 0), reverse=True)

    logger.info("🇨🇳 China signals: %d total (%d from %d China-related markets)",
                len(signals), len(signals), len(china_markets))
    return signals


def format_china_alert(signal: dict) -> str:
    """Format a China signal for Telegram with 🇨🇳 emoji."""
    source = signal.get("source", "unknown")
    market = signal.get("market", {})
    market_title = market.get("title", "Unknown market")

    parts = [f"🇨🇳 **China Signal — {source.upper()}**\n"]

    # Market context
    parts.append(f"🎯 {market_title}")
    if market.get("price") or market.get("last_price"):
        price = market.get("price") or market.get("last_price")
        parts.append(f"💰 Current price: {price}¢")

    parts.append("")

    # Source-specific formatting
    if source == "weibo":
        details = signal.get("details", {})
        vel = details.get("velocity", {})
        parts.append(f"📱 Weibo velocity: {vel.get('velocity_ratio', '?')}x normal")
        parts.append(f"Posts in window: {vel.get('recent_count', 0)}")
        parts.append(f"Engagement: {vel.get('recent_engagement', 0)}")
        top = details.get("top_posts", [])
        if top:
            parts.append(f"\nTop post: {top[0].get('text', '')[:100]}...")

    elif source == "pboc":
        details = signal.get("details", {})
        return format_pboc_alert(details)

    elif source == "economic":
        details = signal.get("details", {})
        event = details.get("event", {})
        return format_china_macro_alert(event)

    elif source == "insider":
        return format_insider_alert(signal.get("details", {}))

    else:
        parts.append(signal.get("description", ""))

    # Confidence
    conf = signal.get("confidence", 0)
    parts.append(f"\n{'🟢' if conf >= 0.7 else '🟡' if conf >= 0.5 else '🔴'} Confidence: {conf:.0%}")

    return "\n".join(parts)
