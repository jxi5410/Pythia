"""
China Economic Data / NBS Release Calendar for Pythia.

Monitors GDP, PMI, CPI, trade balance, industrial production, etc.
from National Bureau of Statistics and other sources.
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


def _cache_get(key: str, ttl: int = 21600):
    entry = _cache.get(key)
    if entry and entry[1] > time.time():
        return entry[0]
    return None


def _cache_set(key: str, data, ttl: int = 21600):
    _cache[key] = (data, time.time() + ttl)


# ---------------------------------------------------------------------------
# NBS Calendar
# ---------------------------------------------------------------------------

def fetch_nbs_calendar(days_ahead: int = 14) -> list[dict]:
    """Fetch upcoming China economic releases from Investing.com or fallback."""
    cached = _cache_get("nbs_calendar", 21600)
    if cached:
        return cached

    events: list[dict] = []

    # Try Investing.com economic calendar (China filter)
    try:
        events = _fetch_from_investing(days_ahead)
    except Exception as e:
        logger.warning("Investing.com calendar fetch failed: %s", e)

    # Try TradingEconomics as fallback
    if not events:
        try:
            events = _fetch_from_tradingeconomics_calendar(days_ahead)
        except Exception as e:
            logger.warning("TradingEconomics calendar fetch failed: %s", e)

    # Fallback: known recurring schedule
    if not events:
        events = _generate_known_schedule(days_ahead)

    _cache_set("nbs_calendar", events, 21600)
    return events


def _fetch_from_investing(days_ahead: int) -> list[dict]:
    """Scrape China economic calendar from Investing.com."""
    events = []
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)

    resp = httpx.get(
        "https://www.investing.com/economic-calendar/",
        headers={**_HEADERS, "Accept": "text/html"},
        timeout=15,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        return events

    soup = BeautifulSoup(resp.text, "html.parser")
    for row in soup.select("tr.js-event-item"):
        country = row.get("data-country", "")
        # Filter for China (country code varies)
        flag = row.select_one("td.flagCur span")
        if flag and "China" not in flag.get("title", ""):
            continue

        name_el = row.select_one("td.event a")
        time_el = row.select_one("td.time")
        cells = row.select("td")

        if not name_el:
            continue

        event = {
            "indicator": name_el.get_text(strip=True),
            "date": None,
            "time_utc": time_el.get_text(strip=True) if time_el else None,
            "previous": cells[-3].get_text(strip=True) if len(cells) >= 3 else None,
            "forecast": cells[-2].get_text(strip=True) if len(cells) >= 2 else None,
            "importance": len(row.select("i.grayFullBullishIcon")),
        }
        events.append(event)

    return events[:20]


def _fetch_from_tradingeconomics_calendar(days_ahead: int) -> list[dict]:
    """Scrape from TradingEconomics."""
    events = []
    resp = httpx.get(
        "https://tradingeconomics.com/china/calendar",
        headers=_HEADERS, timeout=15, follow_redirects=True,
    )
    if resp.status_code != 200:
        return events

    soup = BeautifulSoup(resp.text, "html.parser")
    for row in soup.select("table tr"):
        cells = row.select("td")
        if len(cells) < 4:
            continue
        event = {
            "indicator": cells[1].get_text(strip=True) if len(cells) > 1 else None,
            "date": cells[0].get_text(strip=True) if cells else None,
            "time_utc": None,
            "previous": cells[3].get_text(strip=True) if len(cells) > 3 else None,
            "forecast": cells[4].get_text(strip=True) if len(cells) > 4 else None,
            "importance": 2,
        }
        if event["indicator"]:
            events.append(event)

    return events[:20]


def _generate_known_schedule(days_ahead: int) -> list[dict]:
    """Generate known recurring China data releases as fallback."""
    now = datetime.now(timezone.utc)
    events = []

    # Key monthly releases (approximate dates)
    monthly_releases = [
        {"indicator": "NBS Manufacturing PMI", "day": 1, "importance": 3},
        {"indicator": "Caixin Manufacturing PMI", "day": 2, "importance": 3},
        {"indicator": "Caixin Services PMI", "day": 5, "importance": 2},
        {"indicator": "Trade Balance", "day": 7, "importance": 3},
        {"indicator": "CPI YoY", "day": 10, "importance": 3},
        {"indicator": "PPI YoY", "day": 10, "importance": 2},
        {"indicator": "Industrial Production YoY", "day": 15, "importance": 2},
        {"indicator": "Retail Sales YoY", "day": 15, "importance": 2},
        {"indicator": "Fixed Asset Investment YoY", "day": 15, "importance": 2},
        {"indicator": "LPR Decision", "day": 20, "importance": 3},
    ]

    for rel in monthly_releases:
        for month_offset in range(2):
            month = now.month + month_offset
            year = now.year
            if month > 12:
                month -= 12
                year += 1
            try:
                date = datetime(year, month, rel["day"], tzinfo=timezone.utc)
            except ValueError:
                continue
            if now <= date <= now + timedelta(days=days_ahead):
                events.append({
                    "indicator": rel["indicator"],
                    "date": date.strftime("%Y-%m-%d"),
                    "time_utc": "01:30",  # Most China data at 9:30 CST = 01:30 UTC
                    "previous": None,
                    "forecast": None,
                    "importance": rel["importance"],
                })

    events.sort(key=lambda e: e.get("date", ""))
    return events


# ---------------------------------------------------------------------------
# Latest China data
# ---------------------------------------------------------------------------

def fetch_latest_china_data() -> dict:
    """Fetch current key China economic indicators."""
    cached = _cache_get("china_data", 21600)
    if cached:
        return cached

    data = {
        "gdp_growth": None,
        "cpi_yoy": None,
        "ppi_yoy": None,
        "pmi_official": None,
        "pmi_caixin": None,
        "trade_balance_usd_bn": None,
        "unemployment": None,
        "industrial_production_yoy": None,
        "retail_sales_yoy": None,
        "property_investment_yoy": None,
        "source": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        resp = httpx.get(
            "https://tradingeconomics.com/china/indicators",
            headers=_HEADERS, timeout=15, follow_redirects=True,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text()

            # Parse key indicators
            patterns = {
                "gdp_growth": r"GDP.*?Growth.*?(-?\d+\.?\d*)\s*%",
                "cpi_yoy": r"Consumer.*?Price.*?(-?\d+\.?\d*)\s*%",
                "ppi_yoy": r"Producer.*?Price.*?(-?\d+\.?\d*)\s*%",
                "unemployment": r"Unemployment.*?(\d+\.?\d*)\s*%",
            }
            for key, pat in patterns.items():
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    data[key] = float(m.group(1))

            data["source"] = "tradingeconomics"
    except Exception as e:
        logger.warning("China data fetch failed: %s", e)

    # Fallback with recent known values
    if data["gdp_growth"] is None:
        data.update({
            "gdp_growth": 4.9,
            "cpi_yoy": 0.2,
            "ppi_yoy": -2.8,
            "pmi_official": 49.8,
            "pmi_caixin": 50.5,
            "trade_balance_usd_bn": 82.3,
            "unemployment": 5.0,
            "source": "fallback_hardcoded",
        })

    _cache_set("china_data", data, 21600)
    return data


# ---------------------------------------------------------------------------
# Market matching
# ---------------------------------------------------------------------------

_INDICATOR_KEYWORDS = {
    "GDP": ["gdp", "growth", "economy", "economic"],
    "PMI": ["pmi", "manufacturing", "factory"],
    "CPI": ["cpi", "inflation", "prices", "consumer"],
    "Trade Balance": ["trade", "export", "import", "tariff", "surplus", "deficit"],
    "Property": ["property", "real estate", "housing", "construction"],
    "Unemployment": ["unemployment", "jobs", "labor", "employment"],
    "Retail Sales": ["retail", "consumer spending", "consumption"],
}


def match_china_events_to_markets(
    events: list[dict], active_markets: list[dict]
) -> list[dict]:
    """Map upcoming China data releases to relevant prediction markets."""
    if not events or not active_markets:
        return []

    matches = []
    for event in events:
        indicator = event.get("indicator", "")
        for category, keywords in _INDICATOR_KEYWORDS.items():
            if any(kw in indicator.lower() for kw in keywords):
                for market in active_markets:
                    title = (market.get("title", "") + " " + market.get("question", "")).lower()
                    if any(kw in title for kw in keywords) or "china" in title:
                        matches.append({
                            "event": event,
                            "market": market,
                            "category": category,
                            "relevance": "direct" if category.lower() in title else "indirect",
                        })
                break

    return matches


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_china_macro_alert(event: dict) -> str:
    """Format upcoming China macro event for Telegram."""
    parts = [f"🇨🇳 **China Data Release**\n"]
    parts.append(f"📊 **{event.get('indicator', 'Unknown')}**")
    if event.get("date"):
        parts.append(f"📅 {event['date']} {event.get('time_utc', '')}")
    if event.get("forecast"):
        parts.append(f"Forecast: {event['forecast']}")
    if event.get("previous"):
        parts.append(f"Previous: {event['previous']}")

    importance = event.get("importance", 0)
    if importance >= 3:
        parts.append("🔴 HIGH IMPACT")
    elif importance >= 2:
        parts.append("🟡 Medium impact")

    return "\n".join(parts)
