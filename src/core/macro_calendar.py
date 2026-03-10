"""
Macro Calendar + Earnings Integration for Pythia.

Maps prediction market movements to scheduled events: FOMC, CPI, earnings, OPEC, jobs reports.
Data sources: Investing.com, FRED, Fed website, yfinance — all free.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# --- Cache ---

CACHE_DIR = Path(__file__).parent.parent.parent / ".cache" / "macro_calendar"
CACHE_TTL = 6 * 3600  # 6 hours

ET = timezone(timedelta(hours=-5))  # EST (simplification; DST handled below)
UTC = timezone.utc


def _et_offset() -> timedelta:
    """Return current ET offset accounting for US DST (Mar 2nd Sun - Nov 1st Sun)."""
    now = datetime.now(UTC)
    year = now.year
    # 2nd Sunday of March
    mar1 = datetime(year, 3, 1)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7)
    # 1st Sunday of November
    nov1 = datetime(year, 11, 1)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    if dst_start.replace(tzinfo=UTC) <= now < dst_end.replace(tzinfo=UTC):
        return timedelta(hours=-4)  # EDT
    return timedelta(hours=-5)  # EST


def _to_et() -> timezone:
    return timezone(_et_offset())


def _cache_get(key: str) -> Optional[list]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        data = json.loads(path.read_text())
        if time.time() - data.get("ts", 0) < CACHE_TTL:
            return data["payload"]
    return None


def _cache_set(key: str, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps({"ts": time.time(), "payload": payload}))


# --- Headers for scraping ---

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# --- Category classification ---

CATEGORY_KEYWORDS = {
    "rates": ["interest rate", "fed funds", "fomc", "rate decision", "monetary policy", "central bank"],
    "inflation": ["cpi", "ppi", "pce", "inflation", "consumer price", "producer price"],
    "employment": ["nonfarm", "payroll", "unemployment", "jobless", "employment", "jobs", "adp"],
    "gdp": ["gdp", "gross domestic"],
    "trade": ["trade balance", "export", "import", "current account"],
}


def _classify_category(event_name: str) -> str:
    lower = event_name.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return cat
    return "other"


# ============================================================
# 1. fetch_economic_calendar
# ============================================================

def fetch_economic_calendar(days_ahead: int = 14) -> list[dict]:
    """Get upcoming macro events from Investing.com economic calendar."""
    cached = _cache_get(f"econ_cal_{days_ahead}")
    if cached is not None:
        return cached

    events = []
    try:
        events = _fetch_investing_com(days_ahead)
    except Exception as e:
        logger.warning(f"Investing.com scrape failed: {e}")

    if not events:
        try:
            events = _fetch_fred_calendar(days_ahead)
        except Exception as e:
            logger.warning(f"FRED calendar fallback failed: {e}")

    _cache_set(f"econ_cal_{days_ahead}", events)
    return events


def _fetch_investing_com(days_ahead: int) -> list[dict]:
    """Scrape Investing.com economic calendar via their AJAX endpoint."""
    today = datetime.now(UTC).date()
    end_date = today + timedelta(days=days_ahead)

    url = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
    # Use the main page scrape approach instead
    events = []
    for offset in range(0, days_ahead, 7):
        start = today + timedelta(days=offset)
        end = min(start + timedelta(days=6), end_date)
        page_url = f"https://www.investing.com/economic-calendar/"
        try:
            resp = requests.get(
                page_url,
                headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                params={"dateFrom": start.isoformat(), "dateTo": end.isoformat()},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("tr.js-event-item")
            current_date = None
            for row in rows:
                try:
                    # Date from preceding header or data attribute
                    date_attr = row.get("data-event-datetime", "")
                    time_cell = row.select_one("td.time")
                    time_str = time_cell.get_text(strip=True) if time_cell else ""

                    name_cell = row.select_one("td.event a")
                    if not name_cell:
                        continue
                    event_name = name_cell.get_text(strip=True)

                    country_cell = row.select_one("td.flagCur span")
                    country = country_cell.get("title", "") if country_cell else ""

                    # Importance: count bull icons
                    bulls = row.select("td.sentiment i.grayFullBullishIcon")
                    importance_map = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}
                    importance = importance_map.get(len(bulls), "LOW")

                    prev_cell = row.select_one("td.prev span") or row.select_one("td.prev")
                    prev_val = prev_cell.get_text(strip=True) if prev_cell else ""

                    forecast_cell = row.select_one("td.forecast") or row.select_one("td.fore")
                    forecast_val = forecast_cell.get_text(strip=True) if forecast_cell else ""

                    # Parse datetime
                    event_date = date_attr[:10] if date_attr else str(start)

                    events.append({
                        "event_name": event_name,
                        "date": event_date,
                        "time_utc": time_str,
                        "country": country,
                        "importance": importance,
                        "previous_value": prev_val,
                        "forecast_value": forecast_val,
                        "category": _classify_category(event_name),
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Investing.com page fetch error: {e}")
            continue

    return events


def _fetch_fred_calendar(days_ahead: int) -> list[dict]:
    """Fallback: fetch FRED release calendar."""
    today = datetime.now(UTC).date()
    end_date = today + timedelta(days=days_ahead)
    url = "https://api.stlouisfed.org/fred/releases/dates"

    # FRED API without key — use the calendar page
    page_url = f"https://fred.stlouisfed.org/releases/calendar"
    resp = requests.get(page_url, headers=HEADERS, timeout=15)
    events = []
    if resp.status_code == 200:
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".release-calendar-item, .calendar-release"):
            try:
                name = item.select_one(".release-name, a")
                date_el = item.select_one(".release-date, time")
                if name and date_el:
                    events.append({
                        "event_name": name.get_text(strip=True),
                        "date": date_el.get("datetime", date_el.get_text(strip=True))[:10],
                        "time_utc": "",
                        "country": "US",
                        "importance": "MEDIUM",
                        "previous_value": "",
                        "forecast_value": "",
                        "category": _classify_category(name.get_text(strip=True)),
                    })
            except Exception:
                continue
    return events


# ============================================================
# 2. fetch_fomc_schedule
# ============================================================

def fetch_fomc_schedule() -> list[dict]:
    """Get FOMC meeting dates for current year from the Fed website."""
    cached = _cache_get("fomc_schedule")
    if cached is not None:
        return cached

    events = []
    try:
        url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        year = datetime.now(UTC).year

        # The Fed page has panels per year with meeting dates
        panels = soup.select(".fomc-meeting, .panel, .row")
        for panel in panels:
            text = panel.get_text(" ", strip=True)
            # Look for date patterns like "January 28-29" or "January 28-29*"
            # Also "March 18-19 (notation)" patterns
            date_patterns = re.findall(
                r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?',
                text
            )
            for match in date_patterns:
                month_str, day1, day2 = match
                try:
                    end_day = day2 if day2 else day1
                    date_str = f"{month_str} {end_day}, {year}"
                    dt = datetime.strptime(date_str, "%B %d, %Y")
                    meeting_date = dt.strftime("%Y-%m-%d")

                    is_minutes = "minutes" in text.lower()
                    events.append({
                        "date": meeting_date,
                        "type": "minutes" if is_minutes else "meeting",
                        "statement_release_time": "14:00 ET",
                    })
                except ValueError:
                    continue

        # Deduplicate
        seen = set()
        unique = []
        for e in events:
            key = (e["date"], e["type"])
            if key not in seen:
                seen.add(key)
                unique.append(e)
        events = sorted(unique, key=lambda x: x["date"])

    except Exception as e:
        logger.error(f"Failed to fetch FOMC schedule: {e}")

    _cache_set("fomc_schedule", events)
    return events


# ============================================================
# 3. fetch_earnings_calendar
# ============================================================

def fetch_earnings_calendar(days_ahead: int = 7) -> list[dict]:
    """Get upcoming earnings using yfinance."""
    cached = _cache_get(f"earnings_{days_ahead}")
    if cached is not None:
        return cached

    events = []
    try:
        import yfinance as yf

        # Major tickers to check for upcoming earnings
        major_tickers = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM",
            "BAC", "WFC", "GS", "MS", "UNH", "JNJ", "PFE", "XOM", "CVX",
            "WMT", "HD", "DIS", "NFLX", "CRM", "ORCL", "INTC", "AMD",
            "BA", "CAT", "MMM", "KO", "PEP", "MCD", "NKE", "V", "MA",
            "PYPL", "SQ", "COIN", "SNAP", "UBER", "ABNB", "PLTR",
        ]

        today = datetime.now(UTC).date()
        end_date = today + timedelta(days=days_ahead)

        for ticker_sym in major_tickers:
            try:
                tk = yf.Ticker(ticker_sym)
                cal = tk.calendar
                if cal is None or (hasattr(cal, 'empty') and cal.empty):
                    continue

                # yfinance calendar returns dict or DataFrame
                if isinstance(cal, dict):
                    earnings_date = cal.get("Earnings Date")
                    if earnings_date:
                        if isinstance(earnings_date, list) and len(earnings_date) > 0:
                            ed = earnings_date[0]
                        else:
                            ed = earnings_date
                        if hasattr(ed, 'date'):
                            ed_date = ed.date()
                        else:
                            ed_date = datetime.strptime(str(ed)[:10], "%Y-%m-%d").date()

                        if today <= ed_date <= end_date:
                            events.append({
                                "ticker": ticker_sym,
                                "company": tk.info.get("shortName", ticker_sym) if hasattr(tk, 'info') else ticker_sym,
                                "date": str(ed_date),
                                "time": "BMO",  # Default; hard to determine from yfinance
                                "eps_estimate": str(cal.get("Earnings Average", "")),
                                "revenue_estimate": str(cal.get("Revenue Average", "")),
                            })
                else:
                    # DataFrame format
                    if "Earnings Date" in cal.index:
                        ed = cal.loc["Earnings Date"].iloc[0] if hasattr(cal.loc["Earnings Date"], 'iloc') else cal.loc["Earnings Date"]
                        ed_str = str(ed)[:10]
                        try:
                            ed_date = datetime.strptime(ed_str, "%Y-%m-%d").date()
                            if today <= ed_date <= end_date:
                                events.append({
                                    "ticker": ticker_sym,
                                    "company": ticker_sym,
                                    "date": ed_str,
                                    "time": "BMO",
                                    "eps_estimate": "",
                                    "revenue_estimate": "",
                                })
                        except ValueError:
                            pass
            except Exception:
                continue

    except ImportError:
        logger.warning("yfinance not installed, trying Earnings Whispers fallback")
        events = _fetch_earnings_whispers(days_ahead)
    except Exception as e:
        logger.error(f"Earnings calendar fetch failed: {e}")

    _cache_set(f"earnings_{days_ahead}", events)
    return events


def _fetch_earnings_whispers(days_ahead: int) -> list[dict]:
    """Fallback: scrape Earnings Whispers."""
    events = []
    try:
        resp = requests.get(
            "https://www.earningswhispers.com/calendar",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.select(".cal-item, .earnings-item, li[data-ticker]"):
                try:
                    ticker = item.get("data-ticker", "")
                    name_el = item.select_one(".company-name, .name")
                    date_el = item.select_one(".date, time")
                    if ticker:
                        events.append({
                            "ticker": ticker,
                            "company": name_el.get_text(strip=True) if name_el else ticker,
                            "date": date_el.get_text(strip=True) if date_el else "",
                            "time": "BMO",
                            "eps_estimate": "",
                            "revenue_estimate": "",
                        })
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"Earnings Whispers scrape failed: {e}")
    return events


# ============================================================
# 4. find_nearest_event
# ============================================================

def find_nearest_event(
    spike_time: str,
    category: str = None,
    hours_window: int = 4,
) -> Optional[dict]:
    """
    Given a spike timestamp, find the nearest scheduled event within the window.
    spike_time: ISO format string (e.g. "2024-01-15T14:30:00Z")
    Returns: {event, time_delta_minutes, before_or_after, likely_related}
    """
    try:
        if spike_time.endswith("Z"):
            spike_time = spike_time[:-1] + "+00:00"
        spike_dt = datetime.fromisoformat(spike_time)
        if spike_dt.tzinfo is None:
            spike_dt = spike_dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        logger.error(f"Invalid spike_time format: {spike_time}")
        return None

    # Collect all events
    all_events = []

    econ = fetch_economic_calendar(days_ahead=3)
    for e in econ:
        dt = _parse_event_datetime(e)
        if dt:
            all_events.append((dt, e))

    fomc = fetch_fomc_schedule()
    for f in fomc:
        try:
            # FOMC releases at 14:00 ET
            dt = datetime.strptime(f["date"], "%Y-%m-%d").replace(
                hour=14, minute=0, tzinfo=_to_et()
            ).astimezone(UTC)
            all_events.append((dt, {**f, "event_name": f"FOMC {f['type'].title()}", "category": "rates"}))
        except Exception:
            continue

    earnings = fetch_earnings_calendar(days_ahead=3)
    for e in earnings:
        try:
            hour = 7 if e.get("time") == "BMO" else 16
            dt = datetime.strptime(e["date"], "%Y-%m-%d").replace(
                hour=hour, minute=0, tzinfo=_to_et()
            ).astimezone(UTC)
            all_events.append((dt, {**e, "event_name": f"{e['ticker']} Earnings", "category": "earnings"}))
        except Exception:
            continue

    # Filter by category if specified
    if category:
        all_events = [(dt, e) for dt, e in all_events if e.get("category") == category]

    # Find nearest within window
    window = timedelta(hours=hours_window)
    best = None
    best_delta = None

    for event_dt, event in all_events:
        delta = spike_dt - event_dt
        abs_delta = abs(delta)
        if abs_delta <= window:
            if best_delta is None or abs_delta < best_delta:
                best_delta = abs_delta
                delta_minutes = int(delta.total_seconds() / 60)
                best = {
                    "event": event,
                    "time_delta_minutes": abs(delta_minutes),
                    "before_or_after": "post" if delta_minutes > 0 else "pre",
                    "likely_related": abs(delta_minutes) <= 120,  # Within 2 hours = likely related
                }

    return best


def _parse_event_datetime(event: dict) -> Optional[datetime]:
    """Try to parse an event dict into a UTC datetime."""
    date_str = event.get("date", "")
    time_str = event.get("time_utc", "")

    if not date_str:
        return None

    try:
        if time_str and re.match(r"\d{1,2}:\d{2}", time_str):
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            return dt.replace(tzinfo=UTC)
        else:
            return datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12, tzinfo=UTC)
    except ValueError:
        return None


# ============================================================
# 5. get_event_context
# ============================================================

def get_event_context(event: dict) -> dict:
    """
    Enrich an event with context: actual values, surprise, expected market reaction.
    Uses web search when available for post-release data.
    """
    result = {
        "event": event,
        "actual_value": None,
        "surprise": None,
        "market_reaction_expected": None,
    }

    event_name = event.get("event_name", "").lower()
    forecast = event.get("forecast_value", "")
    previous = event.get("previous_value", "")

    # Try to determine context based on event type
    if "cpi" in event_name or "inflation" in event_name:
        result["market_reaction_expected"] = (
            "Hot print (above forecast) → hawkish repricing → rate cut odds DOWN. "
            "Cool print → dovish → rate cut odds UP."
        )
    elif "fomc" in event_name or "rate" in event_name:
        result["market_reaction_expected"] = (
            "Hawkish hold/hike → risk off. "
            "Dovish cut/signal → risk on, rate cut markets spike."
        )
    elif "nonfarm" in event_name or "payroll" in event_name or "employment" in event_name:
        result["market_reaction_expected"] = (
            "Strong jobs → hawkish (less cuts). "
            "Weak jobs → dovish (more cuts). Watch revisions."
        )
    elif "gdp" in event_name:
        result["market_reaction_expected"] = (
            "Above forecast → strong economy → less cuts. "
            "Below → recession fears → more cuts expected."
        )
    elif "earnings" in event_name:
        ticker = event.get("ticker", "")
        result["market_reaction_expected"] = (
            f"Beat → stock up, sector sentiment positive. "
            f"Miss → stock down, contagion to related markets."
        )

    # If we have forecast and previous, estimate surprise direction
    if forecast and previous:
        try:
            f_val = float(re.sub(r"[^\d.\-]", "", forecast))
            p_val = float(re.sub(r"[^\d.\-]", "", previous))
            if f_val != p_val:
                direction = "higher" if f_val > p_val else "lower"
                result["market_reaction_expected"] = (
                    (result.get("market_reaction_expected") or "") +
                    f"\nForecast ({forecast}) is {direction} than previous ({previous})."
                )
        except (ValueError, TypeError):
            pass

    return result


# ============================================================
# 6. build_week_ahead_briefing
# ============================================================

def build_week_ahead_briefing() -> str:
    """Generate a Week Ahead briefing formatted for Telegram."""
    now = datetime.now(UTC)
    monday = now.date() - timedelta(days=now.weekday())
    next_monday = monday + timedelta(days=7)
    week_label = f"{monday.strftime('%b %d')} – {(next_monday - timedelta(days=1)).strftime('%b %d, %Y')}"

    lines = [f"📋 WEEK AHEAD — {week_label}", ""]

    # Economic events
    econ = fetch_economic_calendar(days_ahead=7)
    high_events = [e for e in econ if e.get("importance") == "HIGH"]
    med_events = [e for e in econ if e.get("importance") == "MEDIUM"]

    if high_events:
        lines.append("🔴 HIGH IMPACT")
        for e in sorted(high_events, key=lambda x: x.get("date", "")):
            time_str = e.get("time_utc", "")
            forecast = e.get("forecast_value", "")
            prev = e.get("previous_value", "")
            detail = ""
            if forecast or prev:
                parts = []
                if forecast:
                    parts.append(f"F: {forecast}")
                if prev:
                    parts.append(f"P: {prev}")
                detail = f" ({' | '.join(parts)})"
            lines.append(f"  • {e['date']} {time_str} — {e['event_name']}{detail}")
        lines.append("")

    if med_events:
        lines.append("🟡 MEDIUM IMPACT")
        for e in sorted(med_events, key=lambda x: x.get("date", ""))[:10]:
            lines.append(f"  • {e['date']} — {e['event_name']}")
        lines.append("")

    # FOMC
    fomc = fetch_fomc_schedule()
    upcoming_fomc = [f for f in fomc if f["date"] >= str(now.date()) and f["date"] <= str(now.date() + timedelta(days=14))]
    if upcoming_fomc:
        lines.append("🏛 FOMC")
        for f in upcoming_fomc:
            lines.append(f"  • {f['date']} — {f['type'].title()} (Statement at {f['statement_release_time']})")
        lines.append("")

    # Earnings
    earnings = fetch_earnings_calendar(days_ahead=7)
    if earnings:
        lines.append("💰 KEY EARNINGS")
        for e in sorted(earnings, key=lambda x: x.get("date", ""))[:15]:
            time_label = "Pre-mkt" if e.get("time") == "BMO" else "After-hrs"
            eps = f" (Est EPS: {e['eps_estimate']})" if e.get("eps_estimate") else ""
            lines.append(f"  • {e['date']} {time_label} — {e['ticker']}{eps}")
        lines.append("")

    # Market impact notes
    lines.append("🎯 PREDICTION MARKET WATCH")
    if any("cpi" in e.get("event_name", "").lower() for e in econ):
        lines.append("  • CPI release → watch inflation / rate cut markets")
    if any("nonfarm" in e.get("event_name", "").lower() or "payroll" in e.get("event_name", "").lower() for e in econ):
        lines.append("  • Jobs report → employment & recession markets")
    if upcoming_fomc:
        lines.append("  • FOMC → rate decision & forward guidance markets")
    if earnings:
        tickers = [e["ticker"] for e in earnings[:5]]
        lines.append(f"  • Earnings: {', '.join(tickers)} → sector sentiment")

    if not econ and not earnings and not upcoming_fomc:
        lines.append("  ℹ️ Light calendar week — lower event-driven volatility expected")

    return "\n".join(lines)


# ============================================================
# 7. format_calendar_alert
# ============================================================

def format_calendar_alert(event: dict, related_markets: list = None) -> str:
    """Format an event as a Telegram alert message."""
    name = event.get("event_name", "Unknown Event")
    date_str = event.get("date", "")
    time_str = event.get("time_utc", "")
    forecast = event.get("forecast_value", "")
    previous = event.get("previous_value", "")
    category = event.get("category", "other")

    # Determine relative time label
    now = datetime.now(UTC).date()
    try:
        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if event_date == now:
            date_label = f"Today {time_str}"
        elif event_date == now + timedelta(days=1):
            date_label = f"Tomorrow {time_str}"
        else:
            date_label = f"{event_date.strftime('%a %b %d')} {time_str}"
    except ValueError:
        date_label = f"{date_str} {time_str}"

    # Icon by category
    icons = {
        "rates": "🏛", "inflation": "📈", "employment": "👷",
        "gdp": "📊", "trade": "🚢", "earnings": "💰",
    }
    icon = icons.get(category, "📅")

    lines = [f"{icon} MACRO EVENT — {name}", f"🕐 {date_label}"]

    if forecast or previous:
        parts = []
        if forecast:
            parts.append(f"Forecast: {forecast}")
        if previous:
            parts.append(f"Previous: {previous}")
        lines.append(f"📊 {' | '.join(parts)}")

    if related_markets:
        lines.append("🎯 Related markets:")
        for m in related_markets[:5]:
            if isinstance(m, dict):
                name_m = m.get("name", m.get("question", ""))
                price = m.get("price", m.get("lastTradePrice", ""))
                lines.append(f'  • "{name_m}" ({price}¢)')
            else:
                lines.append(f"  • {m}")

    # Add watch-for note based on category
    context = get_event_context(event)
    reaction = context.get("market_reaction_expected")
    if reaction:
        # Take first sentence only for brevity
        short = reaction.split(".")[0] + "."
        lines.append(f"⚡ Watch for: {short}")

    return "\n".join(lines)


# ============================================================
# Convenience: all-in-one event lookup
# ============================================================

def get_all_upcoming_events(days_ahead: int = 7) -> list[dict]:
    """Get all events (economic + FOMC + earnings) in a unified list."""
    events = []

    for e in fetch_economic_calendar(days_ahead):
        events.append({**e, "source": "economic"})

    for f in fetch_fomc_schedule():
        try:
            fd = datetime.strptime(f["date"], "%Y-%m-%d").date()
            now = datetime.now(UTC).date()
            if now <= fd <= now + timedelta(days=days_ahead):
                events.append({
                    "event_name": f"FOMC {f['type'].title()}",
                    "date": f["date"],
                    "time_utc": "19:00" if f["type"] == "meeting" else "",
                    "country": "US",
                    "importance": "HIGH",
                    "previous_value": "",
                    "forecast_value": "",
                    "category": "rates",
                    "source": "fomc",
                })
        except Exception:
            continue

    for e in fetch_earnings_calendar(days_ahead):
        events.append({
            "event_name": f"{e['ticker']} Earnings",
            "date": e["date"],
            "time_utc": "11:30" if e.get("time") == "BMO" else "21:00",
            "country": "US",
            "importance": "MEDIUM",
            "previous_value": "",
            "forecast_value": e.get("eps_estimate", ""),
            "category": "earnings",
            "source": "earnings",
            "ticker": e.get("ticker", ""),
        })

    return sorted(events, key=lambda x: x.get("date", ""))
