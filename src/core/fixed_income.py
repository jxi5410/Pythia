"""
Fixed Income / CME FedWatch Arbitrage Detector

Compares institutional pricing (CME FedWatch, derived from Fed Funds futures)
against retail prediction market pricing (Polymarket/Kalshi) to detect
arbitrage signals. Adds macro context from FRED, Treasury yields, and
Cleveland Fed Nowcast.

All data sources are free. No paid APIs required.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: Dict[str, dict] = {}
CACHE_TTL = 900  # 15 minutes


def _get_cached(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["data"]
    return None


def _set_cached(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
}

# ---------------------------------------------------------------------------
# 1. CME FedWatch
# ---------------------------------------------------------------------------

# CME provides FedWatch data via an API endpoint used by their frontend.
CME_FEDWATCH_API = "https://www.cmegroup.com/services/fed-funds-target-rate"
CME_FEDWATCH_MEETINGS_API = "https://www.cmegroup.com/services/fed-funds-target-rate/meetings"


def fetch_fedwatch_probabilities() -> dict:
    """
    Fetch CME FedWatch implied probabilities for upcoming FOMC meetings.

    Returns:
        {meeting_date_str: {
            "cut_50bp": float, "cut_25bp": float, "hold": float,
            "hike_25bp": float, "hike_50bp": float,
            "raw_probabilities": dict  # full target-rate probability breakdown
        }, ...}

    Falls back to scraping if the JSON API changes.
    """
    cached = _get_cached("fedwatch")
    if cached:
        return cached

    result = {}

    # Strategy 1: CME JSON API (used by their React frontend)
    try:
        result = _fetch_fedwatch_api()
        if result:
            _set_cached("fedwatch", result)
            return result
    except Exception as e:
        logger.warning("FedWatch API fetch failed: %s", e)

    # Strategy 2: Scrape the FedWatch HTML page for embedded data
    try:
        result = _fetch_fedwatch_scrape()
        if result:
            _set_cached("fedwatch", result)
            return result
    except Exception as e:
        logger.warning("FedWatch scrape failed: %s", e)

    # Strategy 3: Use Federal Funds futures prices from CME to derive probabilities
    try:
        result = _fetch_fedwatch_from_futures()
        if result:
            _set_cached("fedwatch", result)
            return result
    except Exception as e:
        logger.warning("FedWatch futures derivation failed: %s", e)

    logger.error("All FedWatch fetch strategies failed")
    return result


def _fetch_fedwatch_api() -> dict:
    """Try CME's internal JSON API for FedWatch data."""
    result = {}

    # Get meetings list
    try:
        resp = requests.get(CME_FEDWATCH_MEETINGS_API, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        meetings_data = resp.json()
    except Exception:
        # Try alternative endpoint
        resp = requests.get(CME_FEDWATCH_API, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        meetings_data = resp.json()

    # Parse meetings - CME returns various formats
    meetings = []
    if isinstance(meetings_data, list):
        meetings = meetings_data
    elif isinstance(meetings_data, dict):
        meetings = meetings_data.get("meetings", meetings_data.get("data", []))

    for meeting in meetings[:4]:  # Next 4 meetings
        date_str = meeting.get("meetingDate", meeting.get("date", ""))
        probabilities = meeting.get("probabilities", meeting.get("probs", {}))

        if not date_str or not probabilities:
            continue

        parsed = _parse_rate_probabilities(probabilities)
        result[date_str] = parsed

    return result


def _parse_rate_probabilities(probs: dict) -> dict:
    """
    Parse raw probability data into standardised cut/hold/hike format.
    CME provides probabilities per target rate range (e.g., "425-450": 0.25).
    We classify relative to the current rate.
    """
    # Get current effective fed funds rate (approximate)
    current_rate = _get_current_fed_funds_rate()

    cut_50bp = 0.0
    cut_25bp = 0.0
    hold = 0.0
    hike_25bp = 0.0
    hike_50bp = 0.0
    raw = {}

    for rate_range, prob in probs.items():
        prob_val = float(prob) if not isinstance(prob, (int, float)) else prob
        raw[rate_range] = prob_val

        # Parse rate range like "425-450" or "4.25-4.50"
        try:
            if "-" in str(rate_range):
                parts = str(rate_range).replace("%", "").split("-")
                upper = float(parts[-1].strip())
                # Normalise to basis points if needed
                if upper < 20:
                    upper = upper * 100
            else:
                upper = float(str(rate_range).replace("%", "").strip())
                if upper < 20:
                    upper = upper * 100
        except (ValueError, IndexError):
            continue

        diff_bp = upper - current_rate * 100

        if diff_bp <= -37.5:
            cut_50bp += prob_val
        elif diff_bp <= -12.5:
            cut_25bp += prob_val
        elif diff_bp <= 12.5:
            hold += prob_val
        elif diff_bp <= 37.5:
            hike_25bp += prob_val
        else:
            hike_50bp += prob_val

    return {
        "cut_50bp": round(cut_50bp * 100, 1) if cut_50bp <= 1.0 else round(cut_50bp, 1),
        "cut_25bp": round(cut_25bp * 100, 1) if cut_25bp <= 1.0 else round(cut_25bp, 1),
        "hold": round(hold * 100, 1) if hold <= 1.0 else round(hold, 1),
        "hike_25bp": round(hike_25bp * 100, 1) if hike_25bp <= 1.0 else round(hike_25bp, 1),
        "hike_50bp": round(hike_50bp * 100, 1) if hike_50bp <= 1.0 else round(hike_50bp, 1),
        "raw_probabilities": raw,
    }


def _get_current_fed_funds_rate() -> float:
    """Get current effective federal funds rate. Cached."""
    cached = _get_cached("current_ffr")
    if cached is not None:
        return cached

    # Try FRED first
    try:
        rate = _fetch_fred_series("DFEDTARU", limit=1)
        if rate:
            val = float(rate[0]["value"])
            _set_cached("current_ffr", val)
            return val
    except Exception:
        pass

    # Fallback: hardcoded (update periodically)
    # As of early 2025, target range is 4.25-4.50%
    return 4.50


def _fetch_fedwatch_scrape() -> dict:
    """Scrape CME FedWatch page for embedded JSON data."""
    url = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Look for embedded JSON in script tags
    for script in soup.find_all("script"):
        text = script.string or ""
        if "fedwatch" in text.lower() or "targetRate" in text:
            # Try to extract JSON
            match = re.search(r'(?:fedwatch|targetRate)\s*[=:]\s*(\{.+?\})\s*[;\n]', text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    return _parse_fedwatch_embedded(data)
                except json.JSONDecodeError:
                    continue

    # Try finding table data
    tables = soup.find_all("table")
    for table in tables:
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if any("probability" in h.lower() or "target" in h.lower() for h in headers):
            return _parse_fedwatch_table(table)

    return {}


def _parse_fedwatch_embedded(data: dict) -> dict:
    """Parse embedded FedWatch JSON."""
    result = {}
    meetings = data.get("meetings", data.get("data", []))
    if isinstance(meetings, dict):
        meetings = list(meetings.values())
    for m in meetings[:4]:
        date_str = m.get("date", m.get("meetingDate", "unknown"))
        probs = m.get("probabilities", m.get("probs", {}))
        if probs:
            result[date_str] = _parse_rate_probabilities(probs)
    return result


def _parse_fedwatch_table(table) -> dict:
    """Parse an HTML table of FedWatch probabilities."""
    result = {}
    rows = table.find_all("tr")
    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])] if rows else []

    for row in rows[1:5]:  # Next 4 meetings
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        if len(cells) >= 2:
            date_str = cells[0]
            probs = {}
            for i, header in enumerate(headers[1:], 1):
                if i < len(cells):
                    try:
                        probs[header] = float(cells[i].replace("%", "")) / 100
                    except ValueError:
                        continue
            if probs:
                result[date_str] = _parse_rate_probabilities(probs)

    return result


def _fetch_fedwatch_from_futures() -> dict:
    """
    Derive FedWatch-style probabilities from Fed Funds futures prices.
    Uses Yahoo Finance for ZQ (30-Day Fed Funds) futures.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not available for futures derivation")
        return {}

    # This is a simplified version — real FedWatch uses the full futures curve
    # For now, return empty and rely on API/scrape methods
    return {}


# ---------------------------------------------------------------------------
# 2. Prediction Market Rates
# ---------------------------------------------------------------------------

def fetch_prediction_market_rates(markets: Optional[List[dict]] = None) -> List[dict]:
    """
    Get current Polymarket/Kalshi prices for Fed rate decision markets.

    Args:
        markets: Optional pre-fetched market list. If None, searches both platforms.

    Returns:
        [{market_title, current_price, volume, platform, event_type, meeting_date}, ...]
    """
    cached = _get_cached("prediction_rates")
    if cached:
        return cached

    results = []

    # Search Polymarket
    try:
        results.extend(_search_polymarket_rate_markets())
    except Exception as e:
        logger.warning("Polymarket rate market search failed: %s", e)

    # Search Kalshi
    try:
        results.extend(_search_kalshi_rate_markets())
    except Exception as e:
        logger.warning("Kalshi rate market search failed: %s", e)

    _set_cached("prediction_rates", results)
    return results


def _search_polymarket_rate_markets() -> List[dict]:
    """Search Polymarket for Fed rate / FOMC related markets."""
    from pythia_live.connectors.polymarket import PolymarketConnector

    pm = PolymarketConnector()
    results = []

    # Search keywords related to Fed rate decisions
    rate_keywords = [
        "federal reserve", "fed rate", "fomc", "interest rate",
        "rate cut", "rate hike", "basis points", "fed funds",
    ]

    try:
        # Polymarket Gamma API supports tag/keyword search
        for keyword in ["fed", "fomc", "interest rate", "federal reserve"]:
            try:
                resp = pm.client.get(
                    f"{pm.GAMMA_URL}/markets",
                    params={"tag": keyword, "active": "true", "closed": "false", "limit": 20},
                    timeout=10,
                )
                if resp.status_code == 200:
                    markets = resp.json()
                    if isinstance(markets, dict):
                        markets = markets.get("data", markets.get("markets", []))
                    for m in markets:
                        title = (m.get("question") or m.get("title") or "").lower()
                        if any(kw in title for kw in rate_keywords):
                            outcome_prices = m.get("outcomePrices")
                            if isinstance(outcome_prices, str):
                                outcome_prices = json.loads(outcome_prices)
                            yes_price = float(outcome_prices[0]) if outcome_prices else 0.5

                            market_info = {
                                "market_title": m.get("question") or m.get("title"),
                                "current_price": yes_price,
                                "volume": float(m.get("volume", 0) or 0),
                                "platform": "polymarket",
                                "market_id": m.get("conditionId") or m.get("condition_id") or m.get("id"),
                                "slug": m.get("slug", ""),
                                "event_type": _classify_rate_event(title),
                                "meeting_date": _extract_meeting_date(title),
                            }
                            # Deduplicate by market_id
                            if not any(r["market_id"] == market_info["market_id"] for r in results):
                                results.append(market_info)
            except Exception:
                continue

        # Also search via text query
        try:
            resp = pm.client.get(
                f"{pm.GAMMA_URL}/markets",
                params={"_q": "federal reserve rate", "active": "true", "closed": "false", "limit": 20},
                timeout=10,
            )
            if resp.status_code == 200:
                markets = resp.json()
                if isinstance(markets, dict):
                    markets = markets.get("data", markets.get("markets", []))
                for m in markets:
                    title = (m.get("question") or m.get("title") or "").lower()
                    if any(kw in title for kw in rate_keywords):
                        outcome_prices = m.get("outcomePrices")
                        if isinstance(outcome_prices, str):
                            outcome_prices = json.loads(outcome_prices)
                        yes_price = float(outcome_prices[0]) if outcome_prices else 0.5

                        market_info = {
                            "market_title": m.get("question") or m.get("title"),
                            "current_price": yes_price,
                            "volume": float(m.get("volume", 0) or 0),
                            "platform": "polymarket",
                            "market_id": m.get("conditionId") or m.get("condition_id") or m.get("id"),
                            "slug": m.get("slug", ""),
                            "event_type": _classify_rate_event(title),
                            "meeting_date": _extract_meeting_date(title),
                        }
                        if not any(r["market_id"] == market_info["market_id"] for r in results):
                            results.append(market_info)
        except Exception:
            pass

    except Exception as e:
        logger.warning("Polymarket rate search error: %s", e)

    return results


def _search_kalshi_rate_markets() -> List[dict]:
    """Search Kalshi for Fed rate / FOMC related markets."""
    from pythia_live.connectors.kalshi import KalshiConnector

    kalshi = KalshiConnector()
    results = []

    rate_keywords = [
        "federal reserve", "fed rate", "fomc", "interest rate",
        "rate cut", "rate hike", "fed funds",
    ]

    try:
        # Kalshi series for Fed rate: "FED" or "FOMC"
        for series in ["FED", "FOMC", "RATES"]:
            try:
                resp = kalshi.client.get(
                    f"{kalshi.BASE_URL}/markets",
                    params={"series_ticker": series, "status": "open", "limit": 50},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    markets = data.get("markets", [])
                    for m in markets:
                        title = (m.get("title") or m.get("subtitle") or "").lower()
                        yes_price = float(m.get("yes_bid", 0) or m.get("last_price", 0) or 0) / 100

                        market_info = {
                            "market_title": m.get("title") or m.get("subtitle"),
                            "current_price": yes_price,
                            "volume": float(m.get("volume", 0) or 0),
                            "platform": "kalshi",
                            "market_id": m.get("ticker") or m.get("id"),
                            "slug": m.get("ticker", ""),
                            "event_type": _classify_rate_event(title),
                            "meeting_date": _extract_meeting_date(title),
                        }
                        results.append(market_info)
            except Exception:
                continue
    except Exception as e:
        logger.warning("Kalshi rate search error: %s", e)

    return results


def _classify_rate_event(title: str) -> str:
    """Classify a market title into rate event type."""
    title = title.lower()
    if "cut" in title and "50" in title:
        return "cut_50bp"
    elif "cut" in title and "25" in title:
        return "cut_25bp"
    elif "cut" in title:
        return "cut"
    elif "hike" in title or "raise" in title or "increase" in title:
        return "hike"
    elif "hold" in title or "unchanged" in title or "no change" in title:
        return "hold"
    elif "lower" in title:
        return "cut"
    elif "higher" in title:
        return "hike"
    return "rate_decision"


def _extract_meeting_date(title: str) -> Optional[str]:
    """Try to extract FOMC meeting date from market title."""
    months = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "jun": "06", "jul": "07", "aug": "08", "sep": "09",
        "oct": "10", "nov": "11", "dec": "12",
    }
    title_lower = title.lower()
    for month_name, month_num in months.items():
        # Use word boundary matching to avoid "mar" in "market" etc.
        if re.search(r'\b' + month_name + r'\b', title_lower):
            # Try to find year
            year_match = re.search(r"20\d{2}", title)
            year = year_match.group() if year_match else str(datetime.now().year)
            return f"{year}-{month_num}"
    return None


# ---------------------------------------------------------------------------
# 3. Spread Calculation
# ---------------------------------------------------------------------------

def calculate_spread(fedwatch: dict, prediction_markets: List[dict]) -> List[dict]:
    """
    Compare institutional (FedWatch) vs retail (prediction market) pricing.

    Returns:
        [{event, fedwatch_prob, polymarket_prob, spread_pct,
          direction, significance, meeting_date, platform}, ...]
    """
    if not fedwatch or not prediction_markets:
        return []

    spreads = []

    for market in prediction_markets:
        event_type = market.get("event_type", "")
        meeting_date = market.get("meeting_date")
        market_price = market.get("current_price", 0)
        market_prob = market_price * 100  # Convert cents to percentage

        # Find matching FedWatch meeting
        fw_prob = _match_fedwatch_probability(fedwatch, event_type, meeting_date)
        if fw_prob is None:
            continue

        spread = fw_prob - market_prob
        abs_spread = abs(spread)

        # Significance thresholds
        if abs_spread >= 15:
            significance = "HIGH"
        elif abs_spread >= 8:
            significance = "MEDIUM"
        elif abs_spread >= 3:
            significance = "LOW"
        else:
            continue  # Too small to matter

        direction = "fedwatch_higher" if spread > 0 else "fedwatch_lower"

        spreads.append({
            "event": market.get("market_title", event_type),
            "event_type": event_type,
            "meeting_date": meeting_date,
            "fedwatch_prob": round(fw_prob, 1),
            "polymarket_prob": round(market_prob, 1),
            "spread_pct": round(abs_spread, 1),
            "spread_signed": round(spread, 1),
            "direction": direction,
            "significance": significance,
            "platform": market.get("platform", "unknown"),
            "volume": market.get("volume", 0),
        })

    # Sort by significance then spread
    sig_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    spreads.sort(key=lambda x: (sig_order.get(x["significance"], 3), -x["spread_pct"]))

    return spreads


def _match_fedwatch_probability(fedwatch: dict, event_type: str, meeting_date: Optional[str]) -> Optional[float]:
    """Find the FedWatch probability that matches a prediction market event."""
    # Try to match by meeting date
    matched_meeting = None

    if meeting_date:
        for fw_date, probs in fedwatch.items():
            if meeting_date in fw_date or fw_date in meeting_date:
                matched_meeting = probs
                break

    # If no date match, use the next upcoming meeting (first in dict)
    if not matched_meeting and fedwatch:
        matched_meeting = next(iter(fedwatch.values()))

    if not matched_meeting:
        return None

    # Map event type to FedWatch probability
    event_map = {
        "cut_50bp": "cut_50bp",
        "cut_25bp": "cut_25bp",
        "cut": "cut_25bp",  # Default cut = 25bp
        "hold": "hold",
        "hike": "hike_25bp",
        "hike_25bp": "hike_25bp",
        "hike_50bp": "hike_50bp",
        "rate_decision": None,  # Can't match generic
    }

    fw_key = event_map.get(event_type)
    if fw_key and fw_key in matched_meeting:
        return matched_meeting[fw_key]

    # For generic "rate_decision", try to infer from title
    # Sum all cuts as "easing probability"
    if event_type == "rate_decision":
        total_cut = matched_meeting.get("cut_25bp", 0) + matched_meeting.get("cut_50bp", 0)
        if total_cut > 0:
            return total_cut

    return None


# ---------------------------------------------------------------------------
# 4. Macro Indicators
# ---------------------------------------------------------------------------

def fetch_macro_indicators() -> dict:
    """
    Pull key macro data from FRED and Yahoo Finance.

    Returns:
        {fed_funds_rate, cpi_latest, cpi_yoy, ten_year_yield, two_year_yield,
         yield_curve_2s10s, unemployment_rate, gdp_latest, timestamp}
    """
    cached = _get_cached("macro")
    if cached:
        return cached

    result = {"timestamp": datetime.now().isoformat()}

    # Treasury yields via yfinance
    try:
        import yfinance as yf

        tickers = {
            "^TNX": "ten_year_yield",    # 10Y Treasury
            "^FVX": "five_year_yield",   # 5Y Treasury
            "^IRX": "thirteen_week_yield",  # 13-week T-bill
        }

        for ticker, key in tickers.items():
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if not hist.empty:
                    result[key] = round(float(hist["Close"].iloc[-1]), 3)
            except Exception:
                continue

        # 2Y yield (^TWO not always available on Yahoo, try alternative)
        try:
            two = yf.Ticker("2YY=F")  # 2Y Treasury futures
            hist = two.history(period="5d")
            if not hist.empty:
                result["two_year_yield"] = round(float(hist["Close"].iloc[-1]), 3)
        except Exception:
            pass

        # Calculate 2s10s spread if we have both
        if "ten_year_yield" in result and "two_year_yield" in result:
            result["yield_curve_2s10s"] = round(
                result["ten_year_yield"] - result["two_year_yield"], 3
            )

    except ImportError:
        logger.warning("yfinance not available for yield data")

    # FRED data (no API key needed for HTML scraping)
    fred_series = {
        "DFEDTARU": "fed_funds_rate",      # Fed Funds upper target
        "CPIAUCSL": "cpi_latest",           # CPI All Urban Consumers
        "UNRATE": "unemployment_rate",      # Unemployment Rate
    }

    for series_id, key in fred_series.items():
        try:
            data = _fetch_fred_series(series_id, limit=1)
            if data:
                result[key] = float(data[0]["value"])
                result[f"{key}_date"] = data[0].get("date", "")
        except Exception as e:
            logger.warning("FRED %s fetch failed: %s", series_id, e)

    # CPI YoY change
    try:
        cpi_data = _fetch_fred_series("CPIAUCSL", limit=13)
        if cpi_data and len(cpi_data) >= 13:
            latest = float(cpi_data[0]["value"])
            year_ago = float(cpi_data[12]["value"])
            result["cpi_yoy"] = round((latest - year_ago) / year_ago * 100, 1)
    except Exception:
        pass

    _set_cached("macro", result)
    return result


def _fetch_fred_series(series_id: str, limit: int = 1) -> List[dict]:
    """
    Fetch data from FRED. Tries API with key first, falls back to scraping.
    """
    import os

    api_key = os.environ.get("FRED_API_KEY")

    if api_key:
        try:
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            observations = data.get("observations", [])
            return [{"date": o["date"], "value": o["value"]}
                    for o in observations if o.get("value") != "."]
        except Exception:
            pass

    # Fallback: scrape FRED page
    try:
        url = f"https://fred.stlouisfed.org/series/{series_id}"
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for the latest observation value
        meta = soup.find("span", class_="series-meta-observation-value")
        if meta:
            value = meta.get_text(strip=True).replace(",", "")
            return [{"date": datetime.now().strftime("%Y-%m-%d"), "value": value}]

        # Alternative: look in meta tags
        for meta_tag in soup.find_all("meta"):
            content = meta_tag.get("content", "")
            if series_id in content and "value" in content.lower():
                match = re.search(r"[\d.]+", content)
                if match:
                    return [{"date": datetime.now().strftime("%Y-%m-%d"), "value": match.group()}]

    except Exception as e:
        logger.warning("FRED scrape for %s failed: %s", series_id, e)

    return []


# ---------------------------------------------------------------------------
# 5. Inflation Nowcast
# ---------------------------------------------------------------------------

def fetch_inflation_nowcast() -> dict:
    """
    Get Cleveland Fed Inflation Nowcast data.

    Returns:
        {cpi_nowcast, pce_nowcast, core_cpi_nowcast, core_pce_nowcast,
         nowcast_date, vs_consensus}
    """
    cached = _get_cached("nowcast")
    if cached:
        return cached

    result = {}

    try:
        url = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try to find nowcast values in the page
        # Cleveland Fed typically shows current month CPI/PCE nowcast
        text = soup.get_text()

        # Look for patterns like "CPI: X.XX%" or "Inflation Nowcast: X.X%"
        patterns = [
            (r"CPI\s*(?:Nowcast|forecast|estimate)[:\s]*(\d+\.?\d*)\s*%", "cpi_nowcast"),
            (r"PCE\s*(?:Nowcast|forecast|estimate)[:\s]*(\d+\.?\d*)\s*%", "pce_nowcast"),
            (r"Core\s*CPI[:\s]*(\d+\.?\d*)\s*%", "core_cpi_nowcast"),
            (r"Core\s*PCE[:\s]*(\d+\.?\d*)\s*%", "core_pce_nowcast"),
        ]

        for pattern, key in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result[key] = float(match.group(1))

        # Try to find data in embedded JSON or data attributes
        for script in soup.find_all("script"):
            script_text = script.string or ""
            if "nowcast" in script_text.lower() or "inflation" in script_text.lower():
                # Try to extract JSON data
                json_matches = re.findall(r'\{[^{}]*"(?:cpi|pce|inflation)"[^{}]*\}', script_text, re.IGNORECASE)
                for jm in json_matches:
                    try:
                        data = json.loads(jm)
                        for k, v in data.items():
                            if isinstance(v, (int, float)):
                                result[k.lower()] = v
                    except json.JSONDecodeError:
                        continue

        # Also try the Cleveland Fed API/data download
        if not result:
            result = _fetch_nowcast_data_api()

        result["nowcast_date"] = datetime.now().strftime("%Y-%m-%d")
        result["source"] = "cleveland_fed"

    except Exception as e:
        logger.warning("Cleveland Fed Nowcast fetch failed: %s", e)

    if result:
        _set_cached("nowcast", result)
    return result


def _fetch_nowcast_data_api() -> dict:
    """Try Cleveland Fed data API for nowcast values."""
    result = {}
    try:
        # Cleveland Fed sometimes exposes data via API endpoints
        api_url = "https://www.clevelandfed.org/api/inflation-nowcasting/data"
        resp = requests.get(api_url, headers=_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                result["cpi_nowcast"] = data.get("cpi", data.get("CPI"))
                result["pce_nowcast"] = data.get("pce", data.get("PCE"))
    except Exception:
        pass
    return {k: v for k, v in result.items() if v is not None}


# ---------------------------------------------------------------------------
# 6. Signal Detection (Full Pipeline)
# ---------------------------------------------------------------------------

def detect_rate_signals(active_markets: Optional[List[dict]] = None) -> List[dict]:
    """
    Full pipeline: FedWatch → prediction markets → spreads → macro context → signals.

    Args:
        active_markets: Optional pre-fetched list of prediction market rates.

    Returns:
        Sorted list of signal dicts with arbitrage opportunities and macro context.
    """
    signals = []

    # Step 1: Get FedWatch probabilities
    fedwatch = fetch_fedwatch_probabilities()
    if not fedwatch:
        logger.warning("No FedWatch data available — signals will be limited")

    # Step 2: Get prediction market prices
    pm_rates = active_markets or fetch_prediction_market_rates()
    if not pm_rates:
        logger.warning("No prediction market rate data available")

    # Step 3: Calculate spreads
    spreads = []
    if fedwatch and pm_rates:
        spreads = calculate_spread(fedwatch, pm_rates)

    # Step 4: Add macro context
    macro = fetch_macro_indicators()
    nowcast = fetch_inflation_nowcast()

    # Step 5: Build signals
    for spread in spreads:
        signal = {
            **spread,
            "macro_context": _build_macro_context(macro),
            "nowcast": nowcast,
            "fedwatch_full": fedwatch,
            "signal_time": datetime.now().isoformat(),
        }

        # Add implication
        signal["implication"] = _derive_implication(signal, macro, nowcast)

        signals.append(signal)

    # If no spreads but we have data, still report the state
    if not spreads and (fedwatch or macro):
        signals.append({
            "event": "Market State Summary",
            "event_type": "summary",
            "fedwatch_prob": None,
            "polymarket_prob": None,
            "spread_pct": 0,
            "direction": "aligned",
            "significance": "INFO",
            "macro_context": _build_macro_context(macro),
            "nowcast": nowcast,
            "fedwatch_full": fedwatch,
            "signal_time": datetime.now().isoformat(),
            "implication": "No significant divergence between institutional and retail pricing",
        })

    return signals


def _build_macro_context(macro: dict) -> str:
    """Build human-readable macro context string."""
    parts = []

    if "cpi_yoy" in macro:
        parts.append(f"CPI YoY: {macro['cpi_yoy']}%")
    elif "cpi_latest" in macro:
        parts.append(f"CPI: {macro['cpi_latest']}")

    if "unemployment_rate" in macro:
        parts.append(f"Unemployment: {macro['unemployment_rate']}%")

    if "fed_funds_rate" in macro:
        parts.append(f"Fed Funds: {macro['fed_funds_rate']}%")

    if "yield_curve_2s10s" in macro:
        spread_val = macro["yield_curve_2s10s"]
        status = "inverted" if spread_val < 0 else "normal"
        parts.append(f"2s10s: {spread_val:+.2f}% ({status})")
    elif "ten_year_yield" in macro:
        parts.append(f"10Y: {macro['ten_year_yield']}%")

    return ", ".join(parts) if parts else "Macro data unavailable"


def _derive_implication(signal: dict, macro: dict, nowcast: dict) -> str:
    """Derive trading implication from signal + macro context."""
    direction = signal.get("direction", "")
    event_type = signal.get("event_type", "")
    spread = signal.get("spread_pct", 0)
    platform = signal.get("platform", "market")

    if direction == "fedwatch_higher":
        if "cut" in event_type:
            return (f"{platform.title()} likely underpricing cut probability. "
                    f"Institutional money (${spread:.0f}pts more dovish) may be leading.")
        elif "hike" in event_type:
            return (f"{platform.title()} may be underpricing hawkish risk. "
                    f"Futures market sees higher hike probability by {spread:.0f}pts.")
        else:
            return f"Institutional pricing {spread:.0f}pts above retail — potential buy signal."
    elif direction == "fedwatch_lower":
        if "cut" in event_type:
            return (f"{platform.title()} may be overpricing cut probability. "
                    f"Institutional money is {spread:.0f}pts less dovish.")
        elif "hike" in event_type:
            return (f"{platform.title()} may be overpricing hike risk by {spread:.0f}pts. "
                    f"Futures market more sanguine.")
        else:
            return f"Retail pricing {spread:.0f}pts above institutional — potential fade."

    return "Pricing aligned between institutional and retail markets."


# ---------------------------------------------------------------------------
# 7. Alert Formatting
# ---------------------------------------------------------------------------

def format_rate_alert(signal: dict) -> str:
    """
    Format a rate signal as a Telegram-friendly alert message.
    """
    if signal.get("significance") == "INFO":
        return _format_summary_alert(signal)

    event = signal.get("event", "Unknown")
    fw_prob = signal.get("fedwatch_prob")
    pm_prob = signal.get("polymarket_prob")
    spread = signal.get("spread_pct", 0)
    direction = signal.get("direction", "")
    significance = signal.get("significance", "")
    macro_ctx = signal.get("macro_context", "")
    implication = signal.get("implication", "")
    platform = signal.get("platform", "market").title()
    nowcast = signal.get("nowcast", {})

    # Significance emoji
    sig_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(significance, "⚪")

    # Direction description
    if direction == "fedwatch_higher":
        dir_desc = "institutional money more aggressive"
    else:
        dir_desc = "retail more aggressive than institutional"

    lines = [
        f"💰 RATE ARBITRAGE SIGNAL {sig_emoji}",
        f"{event}",
        f"CME FedWatch: {fw_prob:.0f}% / {platform}: {pm_prob:.0f}¢",
        f"Spread: {spread:.0f}pts ({dir_desc})",
    ]

    if macro_ctx:
        lines.append(f"📊 Macro: {macro_ctx}")

    if nowcast.get("cpi_nowcast"):
        lines.append(f"🎯 Cleveland Nowcast CPI: {nowcast['cpi_nowcast']}%")

    if implication:
        lines.append(f"⚡ {implication}")

    return "\n".join(lines)


def _format_summary_alert(signal: dict) -> str:
    """Format a summary/info signal."""
    macro_ctx = signal.get("macro_context", "N/A")
    fedwatch = signal.get("fedwatch_full", {})
    nowcast = signal.get("nowcast", {})

    lines = ["📊 RATE MARKET STATE"]

    if fedwatch:
        lines.append("\nCME FedWatch Probabilities:")
        for meeting, probs in list(fedwatch.items())[:3]:
            hold = probs.get("hold", 0)
            cut25 = probs.get("cut_25bp", 0)
            cut50 = probs.get("cut_50bp", 0)
            hike25 = probs.get("hike_25bp", 0)
            lines.append(f"  {meeting}: Hold {hold}% | Cut25 {cut25}% | Cut50 {cut50}% | Hike {hike25}%")

    lines.append(f"\n{macro_ctx}")

    if nowcast.get("cpi_nowcast"):
        lines.append(f"Cleveland Fed CPI Nowcast: {nowcast['cpi_nowcast']}%")

    lines.append(f"\n{signal.get('implication', '')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def run_scan() -> str:
    """Run full scan and return formatted alerts. Entry point for integration."""
    signals = detect_rate_signals()
    if not signals:
        return "💰 Fixed Income: No signals detected. Markets may be closed or data unavailable."

    alerts = []
    for sig in signals:
        alerts.append(format_rate_alert(sig))

    return "\n\n---\n\n".join(alerts)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_scan())
