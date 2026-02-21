"""
Equities Correlation Layer — Cross-references prediction market spikes with equity price movements.
"""
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except ImportError:
    yf = None
    logger.warning("yfinance not installed — equity correlation disabled")

# ---------------------------------------------------------------------------
# Ticker Mapping
# ---------------------------------------------------------------------------

CATEGORY_TICKERS = {
    "fed_rate": [
        {"ticker": "TLT", "name": "20+ Year Treasury Bond", "relation": "inverse_rate"},
        {"ticker": "IEF", "name": "7-10 Year Treasury Bond", "relation": "inverse_rate"},
        {"ticker": "SPY", "name": "S&P 500", "relation": "risk_sentiment"},
        {"ticker": "QQQ", "name": "Nasdaq 100", "relation": "rate_sensitive"},
        {"ticker": "DX-Y.NYB", "name": "US Dollar Index", "relation": "dollar_strength"},
    ],
    "inflation": [
        {"ticker": "TIP", "name": "TIPS Bond ETF", "relation": "inflation_hedge"},
        {"ticker": "GLD", "name": "Gold ETF", "relation": "inflation_hedge"},
        {"ticker": "TLT", "name": "20+ Year Treasury Bond", "relation": "real_rates"},
        {"ticker": "SPY", "name": "S&P 500", "relation": "risk_sentiment"},
    ],
    "trade_war": [
        {"ticker": "EEM", "name": "Emerging Markets ETF", "relation": "trade_exposure"},
        {"ticker": "FXI", "name": "China Large-Cap ETF", "relation": "china_exposure"},
        {"ticker": "KWEB", "name": "China Internet ETF", "relation": "china_tech"},
        {"ticker": "SMH", "name": "Semiconductor ETF", "relation": "supply_chain"},
        {"ticker": "NVDA", "name": "NVIDIA", "relation": "chip_exposure"},
    ],
    "crypto": [
        {"ticker": "BTC-USD", "name": "Bitcoin", "relation": "direct"},
        {"ticker": "ETH-USD", "name": "Ethereum", "relation": "direct"},
        {"ticker": "COIN", "name": "Coinbase", "relation": "crypto_proxy"},
        {"ticker": "MARA", "name": "Marathon Digital", "relation": "btc_miner"},
        {"ticker": "MSTR", "name": "MicroStrategy", "relation": "btc_holder"},
    ],
    "tech": [
        {"ticker": "GOOGL", "name": "Alphabet", "relation": "big_tech"},
        {"ticker": "META", "name": "Meta", "relation": "big_tech"},
        {"ticker": "MSFT", "name": "Microsoft", "relation": "big_tech"},
        {"ticker": "AAPL", "name": "Apple", "relation": "big_tech"},
        {"ticker": "QQQ", "name": "Nasdaq 100", "relation": "tech_broad"},
    ],
    "energy": [
        {"ticker": "USO", "name": "US Oil Fund", "relation": "oil_direct"},
        {"ticker": "XLE", "name": "Energy Select SPDR", "relation": "energy_sector"},
        {"ticker": "OXY", "name": "Occidental Petroleum", "relation": "oil_producer"},
        {"ticker": "XOM", "name": "ExxonMobil", "relation": "oil_major"},
    ],
    "election": [
        {"ticker": "SPY", "name": "S&P 500", "relation": "broad_market"},
        {"ticker": "IWM", "name": "Russell 2000", "relation": "domestic_exposure"},
        {"ticker": "DX-Y.NYB", "name": "US Dollar Index", "relation": "policy_uncertainty"},
        {"ticker": "TLT", "name": "20+ Year Treasury Bond", "relation": "fiscal_policy"},
    ],
    "geopolitical": [
        {"ticker": "SPY", "name": "S&P 500", "relation": "risk_sentiment"},
        {"ticker": "GLD", "name": "Gold ETF", "relation": "safe_haven"},
        {"ticker": "USO", "name": "US Oil Fund", "relation": "supply_risk"},
        {"ticker": "VIX", "name": "Volatility Index", "relation": "fear_gauge"},
    ],
    "recession": [
        {"ticker": "SPY", "name": "S&P 500", "relation": "broad_market"},
        {"ticker": "TLT", "name": "20+ Year Treasury Bond", "relation": "flight_to_safety"},
        {"ticker": "XLF", "name": "Financial Select SPDR", "relation": "bank_exposure"},
        {"ticker": "HYG", "name": "High Yield Corp Bond", "relation": "credit_risk"},
    ],
}


def get_related_tickers(market_title: str, category: str) -> List[Dict]:
    """Map prediction market category to relevant equity tickers."""
    if category in CATEGORY_TICKERS:
        return CATEGORY_TICKERS[category]

    # Try to infer from title keywords
    title_lower = market_title.lower()
    for cat, keywords_map in [
        ("fed_rate", ["fed", "rate", "fomc", "powell"]),
        ("crypto", ["bitcoin", "btc", "ethereum", "crypto"]),
        ("trade_war", ["tariff", "trade war", "sanctions"]),
        ("energy", ["oil", "opec", "energy"]),
        ("tech", ["google", "apple", "meta", "ai regulation"]),
        ("election", ["election", "president", "vote"]),
    ]:
        if any(kw in title_lower for kw in keywords_map):
            return CATEGORY_TICKERS[cat]

    # LLM fallback for unknown categories
    return _llm_ticker_fallback(market_title)


def _llm_ticker_fallback(market_title: str) -> List[Dict]:
    """Use LLM to suggest related tickers for unknown categories."""
    prompt = (
        f"Given this prediction market: '{market_title}', "
        "suggest 3-5 stock/ETF tickers that would be most affected. "
        "Return ONLY a JSON array like: "
        '[{"ticker": "SPY", "name": "S&P 500", "relation": "broad_market"}]'
    )
    try:
        result = subprocess.run(
            ['claude', '--print', '--model', 'sonnet', prompt],
            capture_output=True, text=True, timeout=30,
        )
        import re
        match = re.search(r'\[.*\]', result.stdout, re.DOTALL)
        if match:
            tickers = json.loads(match.group())
            if isinstance(tickers, list) and tickers:
                return tickers
    except Exception as e:
        logger.warning("LLM ticker fallback failed: %s", e)

    # Ultimate fallback: broad market
    return [
        {"ticker": "SPY", "name": "S&P 500", "relation": "broad_market"},
        {"ticker": "QQQ", "name": "Nasdaq 100", "relation": "tech_broad"},
        {"ticker": "TLT", "name": "20+ Year Treasury Bond", "relation": "bonds"},
    ]


# ---------------------------------------------------------------------------
# Price Retrieval
# ---------------------------------------------------------------------------

def get_price_around_spike(ticker: str, spike_time: str, window_hours: int = 4) -> Optional[Dict]:
    """Get price data around a spike time using yfinance."""
    if yf is None:
        logger.error("yfinance not available")
        return None

    try:
        spike_dt = datetime.fromisoformat(spike_time.replace("Z", "+00:00")).replace(tzinfo=None)
    except:
        spike_dt = datetime.fromisoformat(spike_time)

    # Download intraday data (1h interval, need 5 days max for yfinance)
    start = spike_dt - timedelta(hours=window_hours + 2)
    end = spike_dt + timedelta(hours=window_hours + 2)

    try:
        data = yf.download(
            ticker, start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1h", progress=False, auto_adjust=True,
        )
        if data.empty:
            # Try daily data as fallback
            data = yf.download(
                ticker, start=start.strftime("%Y-%m-%d"),
                end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                interval="1d", progress=False, auto_adjust=True,
            )
        if data.empty:
            logger.warning("No data for %s around %s", ticker, spike_time)
            return None

        # Flatten multi-level columns if present
        if hasattr(data.columns, 'levels') and len(data.columns.levels) > 1:
            data.columns = data.columns.get_level_values(0)

        # Find closest price to spike time
        data.index = data.index.tz_localize(None) if data.index.tz else data.index

        def _closest_price(target_dt):
            if data.empty:
                return None
            idx = data.index.get_indexer([target_dt], method="nearest")[0]
            if 0 <= idx < len(data):
                return float(data["Close"].iloc[idx])
            return None

        price_at_spike = _closest_price(spike_dt)
        price_1h_before = _closest_price(spike_dt - timedelta(hours=1))
        price_1h_after = _closest_price(spike_dt + timedelta(hours=1))
        price_4h_after = _closest_price(spike_dt + timedelta(hours=window_hours))

        if price_at_spike is None:
            return None

        def _pct(before, after):
            if before and after and before != 0:
                return round((after - before) / before * 100, 3)
            return 0.0

        pct_1h = _pct(price_1h_before, price_1h_after)
        pct_4h = _pct(price_at_spike, price_4h_after)

        direction = "up" if pct_4h > 0.05 else ("down" if pct_4h < -0.05 else "flat")

        return {
            "ticker": ticker,
            "price_at_spike": price_at_spike,
            "price_1h_before": price_1h_before,
            "price_1h_after": price_1h_after,
            "price_4h_after": price_4h_after,
            "pct_change_1h": pct_1h,
            "pct_change_4h": pct_4h,
            "direction": direction,
        }

    except Exception as e:
        logger.warning("Failed to get price for %s: %s", ticker, e)
        return None


# ---------------------------------------------------------------------------
# Correlation Engine
# ---------------------------------------------------------------------------

def correlate_spike(market_title: str, category: str, spike_time: str,
                    spike_direction: str) -> Dict:
    """Orchestrate cross-asset correlation for a prediction market spike."""
    tickers = get_related_tickers(market_title, category)
    correlated_moves = []

    for t in tickers:
        price_data = get_price_around_spike(t["ticker"], spike_time)
        if price_data is None:
            continue

        # Determine if equity move confirms the prediction market spike
        confirms = _move_confirms_spike(
            spike_direction, price_data["direction"],
            t.get("relation", ""), price_data["pct_change_4h"]
        )

        correlated_moves.append({
            "ticker": t["ticker"],
            "name": t.get("name", t["ticker"]),
            "relation": t.get("relation", ""),
            "pct_change_1h": price_data["pct_change_1h"],
            "pct_change_4h": price_data["pct_change_4h"],
            "direction": price_data["direction"],
            "confirms_spike": confirms,
            "price_at_spike": price_data["price_at_spike"],
        })

    # Calculate confidence
    if not correlated_moves:
        confidence = "NONE"
    else:
        confirming = sum(1 for m in correlated_moves if m["confirms_spike"])
        ratio = confirming / len(correlated_moves)
        significant = sum(1 for m in correlated_moves if abs(m["pct_change_4h"]) > 0.3)
        if ratio >= 0.6 and significant >= 2:
            confidence = "HIGH"
        elif ratio >= 0.4 or significant >= 1:
            confidence = "MEDIUM"
        elif confirming > 0:
            confidence = "LOW"
        else:
            confidence = "NONE"

    summary = _build_summary(correlated_moves, confidence, spike_direction)

    return {
        "market_title": market_title,
        "category": category,
        "spike_time": spike_time,
        "spike_direction": spike_direction,
        "correlated_moves": correlated_moves,
        "cross_asset_confidence": confidence,
        "summary": summary,
    }


def _move_confirms_spike(spike_dir: str, equity_dir: str, relation: str,
                          pct_change: float) -> bool:
    """Determine if an equity move confirms a prediction market spike direction."""
    if abs(pct_change) < 0.05:  # Too small to be meaningful
        return False

    # Inverse relations: bonds go up when rates expected to drop
    inverse_relations = {"inverse_rate", "flight_to_safety", "safe_haven", "inflation_hedge"}
    if relation in inverse_relations:
        return (spike_dir == "up" and equity_dir == "up") or \
               (spike_dir == "down" and equity_dir == "down")

    # Fear/vol: goes up on negative events
    if relation in {"fear_gauge"}:
        return (spike_dir == "down" and equity_dir == "up") or \
               (spike_dir == "up" and equity_dir == "down")

    # Direct/risk relations: same direction
    return spike_dir == equity_dir


def _build_summary(moves: List[Dict], confidence: str, spike_dir: str) -> str:
    """Build a human-readable summary of cross-asset correlation."""
    if not moves:
        return "No equity data available for correlation."

    significant = [m for m in moves if abs(m["pct_change_4h"]) > 0.1]
    if not significant:
        return f"Equity markets showed minimal reaction. Confidence: {confidence}"

    parts = []
    for m in sorted(significant, key=lambda x: abs(x["pct_change_4h"]), reverse=True)[:3]:
        sign = "+" if m["pct_change_4h"] > 0 else ""
        confirm_str = "confirms" if m["confirms_spike"] else "diverges from"
        parts.append(f"{m['ticker']} {sign}{m['pct_change_4h']:.1f}% ({confirm_str} {spike_dir} spike)")

    return f"{'; '.join(parts)}. Cross-asset confidence: {confidence}"


# ---------------------------------------------------------------------------
# Alert Formatting
# ---------------------------------------------------------------------------

def format_correlation_alert(correlation: Dict) -> str:
    """Format cross-asset correlation for Telegram alert."""
    moves = correlation.get("correlated_moves", [])
    confidence = correlation.get("cross_asset_confidence", "NONE")

    if not moves or confidence == "NONE":
        return ""

    lines = ["📊 CROSS-ASSET:"]
    spike_dir = correlation.get("spike_direction", "?")

    # Show top 4 most significant moves
    significant = sorted(moves, key=lambda x: abs(x["pct_change_4h"]), reverse=True)[:4]
    for m in significant:
        if abs(m["pct_change_4h"]) < 0.05:
            continue
        sign = "+" if m["pct_change_4h"] > 0 else ""
        if m["confirms_spike"]:
            note = f"confirms {spike_dir} spike"
        else:
            note = "diverges"

        # Add context for known relations
        relation = m.get("relation", "")
        if relation == "flight_to_safety" and m["direction"] == "up":
            note = "flight to safety"
        elif relation == "safe_haven" and m["direction"] == "up":
            note = "safe haven bid"
        elif relation == "fear_gauge" and m["direction"] == "up":
            note = "fear rising"

        lines.append(f"• {m['ticker']} {sign}{m['pct_change_4h']:.1f}% ({note})")

    lines.append(f"• Confidence: {confidence}")
    return "\n".join(lines)
