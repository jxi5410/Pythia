"""
PBOC (People's Bank of China) Policy Signal Detector for Pythia.

Monitors MLF, LPR, RRR rates and open market operations.
The PBOC doesn't work like the Fed — no regular meetings.
Instead: monthly MLF/LPR settings, irregular RRR changes, daily reverse repos.
"""

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# Cache
_cache: dict[str, tuple] = {}


def _cache_get(key: str, ttl: int = 86400):
    entry = _cache.get(key)
    if entry and entry[1] > time.time():
        return entry[0]
    return None


def _cache_set(key: str, data, ttl: int = 86400):
    _cache[key] = (data, time.time() + ttl)


# ---------------------------------------------------------------------------
# PBOC rates
# ---------------------------------------------------------------------------

def fetch_pboc_rates() -> dict:
    """Fetch current MLF, LPR (1Y/5Y), RRR from financial data sites."""
    cached = _cache_get("pboc_rates", 86400)
    if cached:
        return cached

    rates = {
        "mlf_rate": None,
        "lpr_1y": None,
        "lpr_5y": None,
        "rrr": None,
        "last_changed": None,
        "next_lpr_date": _next_lpr_date(),
        "source": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    # Try multiple sources
    for fetcher in [_fetch_rates_eastmoney, _fetch_rates_sina, _fetch_rates_fallback]:
        try:
            result = fetcher()
            if result and any(v is not None for k, v in result.items() if k != "source"):
                rates.update({k: v for k, v in result.items() if v is not None})
                if rates["lpr_1y"] is not None:
                    break
        except Exception as e:
            logger.warning("PBOC rate fetch failed with %s: %s", fetcher.__name__, e)

    _cache_set("pboc_rates", rates, 86400)
    return rates


def _next_lpr_date() -> str:
    """LPR is published on the 20th of each month (or next business day)."""
    now = datetime.now(timezone.utc)
    if now.day < 20:
        target = now.replace(day=20)
    else:
        if now.month == 12:
            target = now.replace(year=now.year + 1, month=1, day=20)
        else:
            target = now.replace(month=now.month + 1, day=20)
    # Adjust for weekends
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return target.strftime("%Y-%m-%d")


def _fetch_rates_eastmoney() -> dict:
    """Scrape rates from eastmoney.com."""
    rates = {"source": "eastmoney"}
    try:
        # LPR page
        resp = httpx.get(
            "https://data.eastmoney.com/cjsj/globalRateLPR.html",
            headers=_HEADERS, timeout=10, follow_redirects=True,
        )
        if resp.status_code == 200:
            text = resp.text
            # Extract LPR rates from page
            m = re.search(r"1年期LPR[^0-9]*(\d+\.?\d*)\s*%", text)
            if m:
                rates["lpr_1y"] = float(m.group(1))
            m = re.search(r"5年期LPR[^0-9]*(\d+\.?\d*)\s*%", text)
            if m:
                rates["lpr_5y"] = float(m.group(1))
    except Exception as e:
        logger.debug("eastmoney LPR fetch: %s", e)

    try:
        # MLF data
        resp = httpx.get(
            "https://data.eastmoney.com/cjsj/hjlc.html",
            headers=_HEADERS, timeout=10, follow_redirects=True,
        )
        if resp.status_code == 200:
            m = re.search(r"MLF[^0-9]*(\d+\.?\d*)\s*%", resp.text)
            if m:
                rates["mlf_rate"] = float(m.group(1))
    except Exception as e:
        logger.debug("eastmoney MLF fetch: %s", e)

    return rates


def _fetch_rates_sina() -> dict:
    """Scrape rates from sina finance."""
    rates = {"source": "sina"}
    try:
        resp = httpx.get(
            "https://finance.sina.com.cn/money/bank/lpr.shtml",
            headers=_HEADERS, timeout=10, follow_redirects=True,
        )
        if resp.status_code == 200:
            text = resp.text
            m = re.search(r"1年期.*?(\d+\.?\d*)\s*%", text)
            if m:
                rates["lpr_1y"] = float(m.group(1))
            m = re.search(r"5年期.*?(\d+\.?\d*)\s*%", text)
            if m:
                rates["lpr_5y"] = float(m.group(1))
    except Exception as e:
        logger.debug("sina LPR fetch: %s", e)
    return rates


def _fetch_rates_fallback() -> dict:
    """Known recent rates as fallback (updated periodically)."""
    return {
        "mlf_rate": 2.5,
        "lpr_1y": 3.1,
        "lpr_5y": 3.6,
        "rrr": 9.5,
        "last_changed": "2024-10-21",
        "source": "fallback_hardcoded",
    }


# ---------------------------------------------------------------------------
# Open market operations
# ---------------------------------------------------------------------------

def fetch_pboc_open_market() -> list[dict]:
    """Fetch daily reverse repo operations from PBOC or financial sites."""
    cached = _cache_get("pboc_omo", 86400)
    if cached:
        return cached

    operations: list[dict] = []

    try:
        # Try PBOC open market page
        resp = httpx.get(
            "http://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/125475/index.html",
            headers=_HEADERS, timeout=15, follow_redirects=True,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "html.parser")
            for link in soup.select("a[href]")[:20]:
                text = link.get_text(strip=True)
                if "逆回购" in text or "公开市场" in text:
                    # Parse amounts from title
                    amount_m = re.search(r"(\d+)\s*亿", text)
                    rate_m = re.search(r"(\d+\.?\d*)\s*%", text)
                    date_m = re.search(r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})", text)

                    op = {
                        "date": f"{date_m.group(1)}-{date_m.group(2).zfill(2)}-{date_m.group(3).zfill(2)}" if date_m else None,
                        "operation_type": "reverse_repo",
                        "amount_billion_rmb": int(amount_m.group(1)) / 10 if amount_m else None,
                        "rate": float(rate_m.group(1)) if rate_m else None,
                        "description": text,
                        "net_injection": None,
                    }
                    operations.append(op)

    except Exception as e:
        logger.warning("PBOC OMO fetch failed: %s", e)

    # Try eastmoney as backup
    if not operations:
        try:
            resp = httpx.get(
                "https://data.eastmoney.com/cjsj/hbgms.html",
                headers=_HEADERS, timeout=10, follow_redirects=True,
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "html.parser")
                for row in soup.select("table tr")[1:10]:
                    cells = row.select("td")
                    if len(cells) >= 4:
                        operations.append({
                            "date": cells[0].get_text(strip=True),
                            "operation_type": cells[1].get_text(strip=True),
                            "amount_billion_rmb": _parse_float(cells[2].get_text(strip=True)),
                            "rate": _parse_float(cells[3].get_text(strip=True)),
                            "net_injection": None,
                        })
        except Exception as e:
            logger.debug("eastmoney OMO fetch: %s", e)

    _cache_set("pboc_omo", operations, 86400)
    return operations


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(re.sub(r"[^\d.]", "", s))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

_CHINA_KEYWORDS = [
    "china", "chinese", "pboc", "renminbi", "rmb", "yuan", "cny",
    "tariff", "trade war", "xi jinping", "beijing", "stimulus",
    "real estate", "property", "evergrande", "byd", "huawei",
    "semiconductor", "taiwan", "south china sea", "hong kong",
]


def _is_china_market(market: dict) -> bool:
    """Check if a market is China-related."""
    title = (market.get("title", "") + " " + market.get("question", "")).lower()
    return any(kw in title for kw in _CHINA_KEYWORDS)


def detect_pboc_signal(active_markets: list[dict] = None) -> dict:
    """Compare PBOC stance with prediction market pricing."""
    rates = fetch_pboc_rates()
    omo = fetch_pboc_open_market()

    signal = {
        "source": "pboc",
        "rates": rates,
        "recent_omo": omo[:5],
        "is_signal": False,
        "matches": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if not active_markets:
        return signal

    china_markets = [m for m in active_markets if _is_china_market(m)]
    if not china_markets:
        return signal

    # Detect policy stance
    stance = _assess_pboc_stance(rates, omo)
    signal["stance"] = stance

    # Match with markets
    for market in china_markets:
        title_lower = (market.get("title", "") + " " + market.get("question", "")).lower()
        price = market.get("price", market.get("last_price"))

        match = None
        if any(w in title_lower for w in ["stimulus", "stimulate", "easing"]):
            if stance["direction"] == "easing" and price and price < 0.5:
                match = {
                    "market": market.get("title", ""),
                    "price": price,
                    "mispricing": "PBOC is easing but market prices low",
                    "confidence": 0.6,
                }
        elif any(w in title_lower for w in ["rate cut", "lower rate"]):
            if stance["direction"] == "easing" and price and price < 0.5:
                match = {
                    "market": market.get("title", ""),
                    "price": price,
                    "mispricing": "PBOC trend is dovish, market underprices",
                    "confidence": 0.55,
                }
        elif any(w in title_lower for w in ["recession", "slowdown", "crash"]):
            if stance["direction"] == "easing" and price and price > 0.6:
                match = {
                    "market": market.get("title", ""),
                    "price": price,
                    "mispricing": "PBOC actively easing suggests concern, market may underprice risk",
                    "confidence": 0.5,
                }

        if match:
            signal["matches"].append(match)

    signal["is_signal"] = len(signal["matches"]) > 0
    return signal


def _assess_pboc_stance(rates: dict, omo: list[dict]) -> dict:
    """Assess current PBOC policy stance from available data."""
    direction = "neutral"
    signals = []

    # Check if rates are at historically low levels (easing)
    lpr_1y = rates.get("lpr_1y")
    if lpr_1y is not None:
        if lpr_1y <= 3.1:
            direction = "easing"
            signals.append(f"LPR 1Y at {lpr_1y}% (historically low)")
        elif lpr_1y >= 4.0:
            direction = "tightening"
            signals.append(f"LPR 1Y at {lpr_1y}% (elevated)")

    # Check net liquidity injection from OMO
    if omo:
        total_injection = sum(
            op.get("amount_billion_rmb", 0) or 0 for op in omo[:5]
        )
        if total_injection > 500:
            direction = "easing"
            signals.append(f"Large OMO injection: {total_injection}B RMB")

    return {
        "direction": direction,
        "signals": signals,
        "confidence": 0.6 if signals else 0.3,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_pboc_alert(signal: dict) -> str:
    """Format PBOC signal for Telegram."""
    parts = ["🇨🇳 **PBOC Policy Signal**\n"]

    rates = signal.get("rates", {})
    if rates.get("lpr_1y"):
        parts.append(f"• LPR 1Y: {rates['lpr_1y']}% | 5Y: {rates.get('lpr_5y', '?')}%")
    if rates.get("mlf_rate"):
        parts.append(f"• MLF: {rates['mlf_rate']}%")
    if rates.get("rrr"):
        parts.append(f"• RRR: {rates['rrr']}%")

    stance = signal.get("stance", {})
    if stance:
        parts.append(f"\nStance: **{stance.get('direction', 'unknown').upper()}**")
        for s in stance.get("signals", []):
            parts.append(f"  → {s}")

    for match in signal.get("matches", []):
        parts.append(f"\n⚡ {match['market']}")
        parts.append(f"  Price: {match['price']} | {match['mispricing']}")

    return "\n".join(parts)
