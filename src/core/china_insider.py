"""
CSRC/HKEx Insider Disclosure Monitoring for Pythia.

HKEx requires directors to disclose trades within 3 business days.
This module scrapes HKEx SDI (Securities Disclosure of Interests) data.
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
}

_cache: dict[str, tuple] = {}


def _cache_get(key: str, ttl: int = 3600):
    entry = _cache.get(key)
    if entry and entry[1] > time.time():
        return entry[0]
    return None


def _cache_set(key: str, data, ttl: int = 3600):
    _cache[key] = (data, time.time() + ttl)


# ---------------------------------------------------------------------------
# Key China/HK tickers to monitor
# ---------------------------------------------------------------------------

WATCHED_TICKERS = {
    "9988": {"name": "Alibaba", "keywords": ["alibaba", "tech regulation", "antitrust"]},
    "0700": {"name": "Tencent", "keywords": ["tencent", "tech regulation", "gaming"]},
    "1211": {"name": "BYD", "keywords": ["byd", "ev", "electric vehicle"]},
    "0981": {"name": "SMIC", "keywords": ["smic", "semiconductor", "chip"]},
    "2007": {"name": "Country Garden", "keywords": ["property", "real estate"]},
    "2202": {"name": "China Vanke", "keywords": ["property", "real estate"]},
    "1810": {"name": "Xiaomi", "keywords": ["xiaomi", "tech", "ev"]},
    "3690": {"name": "Meituan", "keywords": ["meituan", "tech regulation"]},
    "9618": {"name": "JD.com", "keywords": ["jd", "ecommerce"]},
    "9999": {"name": "NetEase", "keywords": ["netease", "gaming"]},
}


# ---------------------------------------------------------------------------
# HKEx insider deals
# ---------------------------------------------------------------------------

def fetch_hkex_insider_deals(days_back: int = 7) -> list[dict]:
    """Fetch director/insider dealings from HKEx disclosure system."""
    cache_key = f"hkex_insider:{days_back}"
    cached = _cache_get(cache_key, 3600)
    if cached:
        return cached

    deals: list[dict] = []

    # Try HKEx SDI search
    try:
        deals = _fetch_hkex_sdi(days_back)
    except Exception as e:
        logger.warning("HKEx SDI fetch failed: %s", e)

    # Try HKEX news as backup
    if not deals:
        try:
            deals = _fetch_hkex_news(days_back)
        except Exception as e:
            logger.warning("HKEx news fetch failed: %s", e)

    _cache_set(cache_key, deals, 3600)
    return deals


def _fetch_hkex_sdi(days_back: int) -> list[dict]:
    """Scrape from HKEx Securities Disclosure of Interests."""
    deals = []
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days_back)

    # HKEx SDI search page
    try:
        resp = httpx.get(
            "https://www.hkexnews.hk/sdw/search/searchsdw.aspx",
            headers=_HEADERS, timeout=15, follow_redirects=True,
        )
        if resp.status_code != 200:
            return deals

        # The SDI system uses ASP.NET postback forms - complex to automate
        # Instead try the RSS/listing approach
        resp = httpx.get(
            "https://www.hkexnews.hk/listedco/listconews/advancedsearch/search_active_main.aspx",
            params={
                "searchtype": 0,
                "t1code": 2,  # Category: Director dealings
                "t2Gcode": -2,
                "LangCode": "en",
            },
            headers=_HEADERS, timeout=15, follow_redirects=True,
        )

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.select("table tr"):
                cells = row.select("td")
                if len(cells) < 4:
                    continue

                text = " ".join(c.get_text(strip=True) for c in cells)
                if "director" in text.lower() or "dealing" in text.lower():
                    ticker_m = re.search(r"(\d{4,5})", cells[0].get_text())
                    deal = {
                        "company": cells[1].get_text(strip=True) if len(cells) > 1 else None,
                        "ticker": ticker_m.group(1) if ticker_m else None,
                        "director": None,
                        "transaction_type": None,
                        "shares": None,
                        "value_hkd": None,
                        "date": cells[0].get_text(strip=True),
                        "raw_text": text[:200],
                    }
                    deals.append(deal)

    except Exception as e:
        logger.debug("HKEx SDI search: %s", e)

    return deals


def _fetch_hkex_news(days_back: int) -> list[dict]:
    """Fetch from HKEx news filings."""
    deals = []
    try:
        # Search for director dealings in recent filings
        resp = httpx.get(
            "https://www.hkexnews.hk/listedco/listconews/advancedsearch/search_active_main.aspx",
            headers=_HEADERS, timeout=15, follow_redirects=True,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a[href*='sdi']"):
                text = link.get_text(strip=True)
                if any(kw in text.lower() for kw in ["director", "dealing", "disclosure", "interest"]):
                    deals.append({
                        "company": text[:50],
                        "ticker": None,
                        "director": None,
                        "transaction_type": "unknown",
                        "shares": None,
                        "value_hkd": None,
                        "date": None,
                        "url": link.get("href", ""),
                    })
    except Exception as e:
        logger.debug("HKEx news: %s", e)

    return deals[:20]


# ---------------------------------------------------------------------------
# Market matching
# ---------------------------------------------------------------------------

def match_insider_to_markets(
    deals: list[dict], active_markets: list[dict]
) -> list[dict]:
    """Cross-reference insider deals with prediction markets."""
    if not deals or not active_markets:
        return []

    matches = []
    for deal in deals:
        ticker = deal.get("ticker", "")
        company_info = WATCHED_TICKERS.get(ticker)
        if not company_info:
            # Try matching by company name
            company = (deal.get("company") or "").lower()
            for tk, info in WATCHED_TICKERS.items():
                if info["name"].lower() in company:
                    company_info = info
                    break

        if not company_info:
            continue

        for market in active_markets:
            title_lower = (market.get("title", "") + " " + market.get("question", "")).lower()
            if any(kw in title_lower for kw in company_info["keywords"]):
                matches.append({
                    "deal": deal,
                    "market": market,
                    "company": company_info["name"],
                    "relevance": "direct",
                    "signal_type": "insider_activity",
                })

    return matches


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_insider_alert(signal: dict) -> str:
    """Format insider deal signal for Telegram."""
    deal = signal.get("deal", {})
    market = signal.get("market", {})

    parts = ["🇨🇳 **HKEx Insider Activity**\n"]
    parts.append(f"🏢 {signal.get('company', deal.get('company', 'Unknown'))}")

    if deal.get("ticker"):
        parts.append(f"📈 Ticker: {deal['ticker']}.HK")
    if deal.get("director"):
        parts.append(f"👤 Director: {deal['director']}")
    if deal.get("transaction_type"):
        tx = deal["transaction_type"].upper()
        emoji = "🟢" if "buy" in tx.lower() or "acquire" in tx.lower() else "🔴"
        parts.append(f"{emoji} Type: {tx}")
    if deal.get("shares"):
        parts.append(f"📊 Shares: {deal['shares']:,}" if isinstance(deal["shares"], (int, float)) else f"📊 Shares: {deal['shares']}")
    if deal.get("value_hkd"):
        parts.append(f"💰 Value: HK${deal['value_hkd']:,.0f}" if isinstance(deal["value_hkd"], (int, float)) else f"💰 Value: {deal['value_hkd']}")
    if deal.get("date"):
        parts.append(f"📅 Date: {deal['date']}")

    if market:
        parts.append(f"\n🎯 Related market: {market.get('title', '?')}")

    return "\n".join(parts)
