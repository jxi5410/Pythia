"""
China/HK Equity Cross-Referencing for Pythia.

Maps prediction market categories to China/HK tickers and correlates
price movements with market spikes. Handles HK/Shanghai timezone differences.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except ImportError:
    yf = None
    logger.warning("yfinance not installed — China equity correlation disabled")

# ---------------------------------------------------------------------------
# Ticker Mapping
# ---------------------------------------------------------------------------

CHINA_CATEGORY_TICKERS: dict[str, list[dict]] = {
    "trade_war": [
        {"ticker": "FXI", "name": "iShares China Large-Cap", "relation": "china_exposure"},
        {"ticker": "KWEB", "name": "KraneShares China Internet", "relation": "china_tech"},
        {"ticker": "BABA", "name": "Alibaba (US ADR)", "relation": "china_tech"},
        {"ticker": "JD", "name": "JD.com", "relation": "china_ecommerce"},
        {"ticker": "PDD", "name": "PDD Holdings (Temu)", "relation": "china_ecommerce"},
        {"ticker": "BIDU", "name": "Baidu", "relation": "china_tech"},
        {"ticker": "9988.HK", "name": "Alibaba (HK)", "relation": "china_tech_hk"},
        {"ticker": "0700.HK", "name": "Tencent (HK)", "relation": "china_tech_hk"},
    ],
    "tariffs": [
        {"ticker": "FXI", "name": "iShares China Large-Cap", "relation": "china_exposure"},
        {"ticker": "KWEB", "name": "KraneShares China Internet", "relation": "china_tech"},
        {"ticker": "BABA", "name": "Alibaba", "relation": "china_tech"},
        {"ticker": "JD", "name": "JD.com", "relation": "china_ecommerce"},
        {"ticker": "PDD", "name": "PDD Holdings", "relation": "china_ecommerce"},
        {"ticker": "EEM", "name": "Emerging Markets ETF", "relation": "em_exposure"},
    ],
    "tech_regulation": [
        {"ticker": "BABA", "name": "Alibaba", "relation": "direct"},
        {"ticker": "TCEHY", "name": "Tencent (OTC)", "relation": "direct"},
        {"ticker": "BIDU", "name": "Baidu", "relation": "direct"},
        {"ticker": "PDD", "name": "PDD Holdings", "relation": "direct"},
        {"ticker": "9988.HK", "name": "Alibaba (HK)", "relation": "direct_hk"},
        {"ticker": "0700.HK", "name": "Tencent (HK)", "relation": "direct_hk"},
    ],
    "property": [
        {"ticker": "2007.HK", "name": "Country Garden", "relation": "direct"},
        {"ticker": "2202.HK", "name": "China Vanke", "relation": "direct"},
        {"ticker": "FXI", "name": "China Large-Cap", "relation": "macro"},
        {"ticker": "ASHR", "name": "Xtrackers CSI 300", "relation": "a_shares"},
    ],
    "taiwan": [
        {"ticker": "TSM", "name": "TSMC", "relation": "direct"},
        {"ticker": "ASML", "name": "ASML", "relation": "chip_equipment"},
        {"ticker": "SMH", "name": "Semiconductor ETF", "relation": "sector"},
        {"ticker": "ITA", "name": "iShares US Aerospace & Defense", "relation": "defense"},
        {"ticker": "LMT", "name": "Lockheed Martin", "relation": "defense"},
        {"ticker": "FXI", "name": "China Large-Cap", "relation": "china_risk"},
    ],
    "ev_auto": [
        {"ticker": "1211.HK", "name": "BYD (HK)", "relation": "direct"},
        {"ticker": "NIO", "name": "NIO", "relation": "direct"},
        {"ticker": "XPEV", "name": "XPeng", "relation": "direct"},
        {"ticker": "LI", "name": "Li Auto", "relation": "direct"},
        {"ticker": "TSLA", "name": "Tesla", "relation": "competitor"},
    ],
    "semiconductor": [
        {"ticker": "0981.HK", "name": "SMIC (HK)", "relation": "direct"},
        {"ticker": "SMH", "name": "VanEck Semiconductor", "relation": "sector"},
        {"ticker": "ASML", "name": "ASML", "relation": "equipment"},
        {"ticker": "TSM", "name": "TSMC", "relation": "competitor"},
        {"ticker": "NVDA", "name": "NVIDIA", "relation": "export_controls"},
    ],
    "stimulus": [
        {"ticker": "FXI", "name": "iShares China Large-Cap", "relation": "direct"},
        {"ticker": "ASHR", "name": "CSI 300 China A-Shares", "relation": "a_shares"},
        {"ticker": "YINN", "name": "3x Bull China ETF", "relation": "leveraged"},
        {"ticker": "KWEB", "name": "China Internet", "relation": "growth"},
        {"ticker": "EEM", "name": "Emerging Markets", "relation": "em_exposure"},
    ],
}

# Keyword to category mapping
_KEYWORD_CATEGORIES = {
    "trade war": "trade_war", "tariff": "tariffs", "tariffs": "tariffs",
    "tech regulation": "tech_regulation", "antitrust": "tech_regulation",
    "property": "property", "real estate": "property", "housing": "property",
    "evergrande": "property",
    "taiwan": "taiwan", "defense": "taiwan",
    "ev": "ev_auto", "byd": "ev_auto", "electric vehicle": "ev_auto",
    "semiconductor": "semiconductor", "chip": "semiconductor", "smic": "semiconductor",
    "stimulus": "stimulus", "easing": "stimulus", "pboc": "stimulus",
}


def get_china_tickers(market_title: str, category: str = None) -> list[dict]:
    """Map prediction market to relevant China/HK tickers."""
    if category and category in CHINA_CATEGORY_TICKERS:
        return CHINA_CATEGORY_TICKERS[category]

    # Auto-detect category from title
    title_lower = market_title.lower()
    for keyword, cat in _KEYWORD_CATEGORIES.items():
        if keyword in title_lower:
            return CHINA_CATEGORY_TICKERS.get(cat, [])

    # Default: broad China exposure
    return CHINA_CATEGORY_TICKERS.get("stimulus", [])


def get_china_price_around_spike(
    ticker: str, spike_time: str, window_hours: int = 4
) -> Optional[Dict]:
    """Get price data around a spike time, handling HK/Shanghai timezone."""
    if yf is None:
        logger.warning("yfinance not installed")
        return None

    try:
        if isinstance(spike_time, str):
            spike_dt = datetime.fromisoformat(spike_time)
        else:
            spike_dt = spike_time

        if spike_dt.tzinfo is None:
            spike_dt = spike_dt.replace(tzinfo=timezone.utc)

        start = spike_dt - timedelta(hours=window_hours)
        end = spike_dt + timedelta(hours=window_hours)

        # Extend range for HK/Shanghai markets (UTC+8)
        is_asia = ticker.endswith(".HK") or ticker.endswith(".SS") or ticker.endswith(".SZ")
        if is_asia:
            start -= timedelta(hours=8)
            end += timedelta(hours=8)

        stock = yf.Ticker(ticker)
        hist = stock.history(start=start, end=end, interval="1h")

        if hist.empty:
            # Try daily if intraday unavailable
            hist = stock.history(start=start - timedelta(days=2), end=end + timedelta(days=2), interval="1d")

        if hist.empty:
            return None

        prices = hist["Close"].tolist()
        times = [t.isoformat() for t in hist.index]

        pre_spike = [p for t, p in zip(hist.index, prices) if t.timestamp() < spike_dt.timestamp()]
        post_spike = [p for t, p in zip(hist.index, prices) if t.timestamp() >= spike_dt.timestamp()]

        pre_price = pre_spike[-1] if pre_spike else prices[0]
        post_price = post_spike[0] if post_spike else prices[-1]
        pct_change = ((post_price - pre_price) / pre_price) * 100 if pre_price else 0

        return {
            "ticker": ticker,
            "pre_spike_price": round(pre_price, 2),
            "post_spike_price": round(post_price, 2),
            "pct_change": round(pct_change, 2),
            "price_range": [round(min(prices), 2), round(max(prices), 2)],
            "data_points": len(prices),
            "is_asia_market": is_asia,
        }

    except Exception as e:
        logger.error("Price fetch failed for %s: %s", ticker, e)
        return None


def correlate_china_spike(
    market_title: str, category: str, spike_time: str, spike_direction: str
) -> dict:
    """Full correlation: map market to China tickers and check price alignment."""
    tickers = get_china_tickers(market_title, category)
    correlations = []

    for t in tickers[:6]:  # Limit API calls
        price_data = get_china_price_around_spike(t["ticker"], spike_time)
        if not price_data:
            continue

        # Check if equity moved in expected direction
        pct = price_data["pct_change"]
        aligned = False
        if spike_direction == "up" and t.get("relation") != "inverse":
            aligned = pct > 0.5
        elif spike_direction == "down" and t.get("relation") != "inverse":
            aligned = pct < -0.5
        elif t.get("relation") == "inverse":
            aligned = (spike_direction == "up" and pct < -0.5) or (spike_direction == "down" and pct > 0.5)

        correlations.append({
            **price_data,
            "name": t["name"],
            "relation": t["relation"],
            "aligned": aligned,
        })

    aligned_count = sum(1 for c in correlations if c["aligned"])
    total = len(correlations)

    return {
        "market_title": market_title,
        "category": category,
        "spike_time": spike_time,
        "spike_direction": spike_direction,
        "correlations": correlations,
        "alignment_ratio": aligned_count / total if total else 0,
        "confidence": min(0.9, 0.3 + (aligned_count / max(total, 1)) * 0.6),
        "is_confirmed": aligned_count >= 2 and aligned_count / max(total, 1) >= 0.5,
    }
