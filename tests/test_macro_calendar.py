"""Tests for macro_calendar module."""

import json
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pythia_live.macro_calendar import (
    _classify_category,
    _parse_event_datetime,
    find_nearest_event,
    get_event_context,
    format_calendar_alert,
    build_week_ahead_briefing,
    fetch_economic_calendar,
    fetch_fomc_schedule,
    fetch_earnings_calendar,
    get_all_upcoming_events,
    _cache_get,
    _cache_set,
)


# --- Unit tests (no network) ---

class TestClassifyCategory:
    def test_inflation(self):
        assert _classify_category("CPI m/m") == "inflation"
        assert _classify_category("Consumer Price Index") == "inflation"

    def test_rates(self):
        assert _classify_category("FOMC Statement") == "rates"
        assert _classify_category("Interest Rate Decision") == "rates"

    def test_employment(self):
        assert _classify_category("Nonfarm Payrolls") == "employment"
        assert _classify_category("Unemployment Rate") == "employment"

    def test_gdp(self):
        assert _classify_category("GDP q/q") == "gdp"

    def test_trade(self):
        assert _classify_category("Trade Balance") == "trade"

    def test_other(self):
        assert _classify_category("Retail Sales m/m") == "other"


class TestParseEventDatetime:
    def test_with_time(self):
        event = {"date": "2024-03-15", "time_utc": "12:30"}
        dt = _parse_event_datetime(event)
        assert dt is not None
        assert dt.hour == 12
        assert dt.minute == 30

    def test_date_only(self):
        event = {"date": "2024-03-15", "time_utc": ""}
        dt = _parse_event_datetime(event)
        assert dt is not None
        assert dt.hour == 12  # default noon

    def test_empty(self):
        assert _parse_event_datetime({}) is None


class TestFindNearestEvent:
    @patch("pythia_live.macro_calendar.fetch_economic_calendar")
    @patch("pythia_live.macro_calendar.fetch_fomc_schedule")
    @patch("pythia_live.macro_calendar.fetch_earnings_calendar")
    def test_finds_nearby_event(self, mock_earn, mock_fomc, mock_econ):
        mock_econ.return_value = [{
            "event_name": "CPI m/m",
            "date": "2024-03-15",
            "time_utc": "12:30",
            "country": "US",
            "importance": "HIGH",
            "previous_value": "3.1%",
            "forecast_value": "3.2%",
            "category": "inflation",
        }]
        mock_fomc.return_value = []
        mock_earn.return_value = []

        result = find_nearest_event("2024-03-15T13:00:00Z")
        assert result is not None
        assert result["time_delta_minutes"] == 30
        assert result["before_or_after"] == "post"
        assert result["likely_related"] is True

    @patch("pythia_live.macro_calendar.fetch_economic_calendar")
    @patch("pythia_live.macro_calendar.fetch_fomc_schedule")
    @patch("pythia_live.macro_calendar.fetch_earnings_calendar")
    def test_no_event_in_window(self, mock_earn, mock_fomc, mock_econ):
        mock_econ.return_value = [{
            "event_name": "CPI m/m",
            "date": "2024-03-15",
            "time_utc": "12:30",
            "country": "US",
            "importance": "HIGH",
            "previous_value": "",
            "forecast_value": "",
            "category": "inflation",
        }]
        mock_fomc.return_value = []
        mock_earn.return_value = []

        result = find_nearest_event("2024-03-16T12:00:00Z", hours_window=4)
        assert result is None

    @patch("pythia_live.macro_calendar.fetch_economic_calendar")
    @patch("pythia_live.macro_calendar.fetch_fomc_schedule")
    @patch("pythia_live.macro_calendar.fetch_earnings_calendar")
    def test_category_filter(self, mock_earn, mock_fomc, mock_econ):
        mock_econ.return_value = [
            {"event_name": "CPI", "date": "2024-03-15", "time_utc": "12:30",
             "country": "US", "importance": "HIGH", "previous_value": "", "forecast_value": "", "category": "inflation"},
            {"event_name": "GDP", "date": "2024-03-15", "time_utc": "12:30",
             "country": "US", "importance": "HIGH", "previous_value": "", "forecast_value": "", "category": "gdp"},
        ]
        mock_fomc.return_value = []
        mock_earn.return_value = []

        result = find_nearest_event("2024-03-15T13:00:00Z", category="gdp")
        assert result is not None
        assert result["event"]["category"] == "gdp"


class TestGetEventContext:
    def test_cpi_context(self):
        event = {"event_name": "CPI m/m", "forecast_value": "3.2%", "previous_value": "3.4%"}
        ctx = get_event_context(event)
        assert ctx["market_reaction_expected"] is not None
        assert "Hot print" in ctx["market_reaction_expected"]

    def test_fomc_context(self):
        event = {"event_name": "FOMC Statement"}
        ctx = get_event_context(event)
        assert "Hawkish" in ctx["market_reaction_expected"]

    def test_earnings_context(self):
        event = {"event_name": "AAPL Earnings", "ticker": "AAPL"}
        ctx = get_event_context(event)
        assert "Beat" in ctx["market_reaction_expected"]


class TestFormatCalendarAlert:
    def test_basic_format(self):
        event = {
            "event_name": "CPI Release",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "time_utc": "12:30",
            "forecast_value": "3.2%",
            "previous_value": "3.4%",
            "category": "inflation",
        }
        alert = format_calendar_alert(event)
        assert "CPI Release" in alert
        assert "3.2%" in alert
        assert "MACRO EVENT" in alert

    def test_with_related_markets(self):
        event = {
            "event_name": "FOMC Decision",
            "date": "2024-03-20",
            "time_utc": "19:00",
            "category": "rates",
        }
        markets = [
            {"name": "Fed rate cut March", "price": 62},
            {"name": "Recession 2024", "price": 25},
        ]
        alert = format_calendar_alert(event, related_markets=markets)
        assert "Fed rate cut March" in alert
        assert "Related markets" in alert


class TestBuildWeekAheadBriefing:
    @patch("pythia_live.macro_calendar.fetch_economic_calendar")
    @patch("pythia_live.macro_calendar.fetch_fomc_schedule")
    @patch("pythia_live.macro_calendar.fetch_earnings_calendar")
    def test_briefing_format(self, mock_earn, mock_fomc, mock_econ):
        mock_econ.return_value = [{
            "event_name": "CPI m/m",
            "date": "2024-03-15",
            "time_utc": "12:30",
            "country": "US",
            "importance": "HIGH",
            "previous_value": "3.1%",
            "forecast_value": "3.2%",
            "category": "inflation",
        }]
        mock_fomc.return_value = []
        mock_earn.return_value = [
            {"ticker": "AAPL", "company": "Apple", "date": "2024-03-14", "time": "AMC", "eps_estimate": "1.50", "revenue_estimate": ""},
        ]

        briefing = build_week_ahead_briefing()
        assert "WEEK AHEAD" in briefing
        assert "CPI" in briefing
        assert "AAPL" in briefing


class TestCache:
    def test_cache_round_trip(self):
        _cache_set("test_key", [{"a": 1}])
        result = _cache_get("test_key")
        assert result == [{"a": 1}]


# --- Integration tests (network, skip if offline) ---

@pytest.mark.skipif(
    os.environ.get("PYTHIA_SKIP_NETWORK") == "1",
    reason="Network tests skipped"
)
class TestNetworkIntegration:
    def test_fomc_schedule_fetch(self):
        """Test actual FOMC schedule fetch — should return list."""
        result = fetch_fomc_schedule()
        # May be empty if scraping fails, but should not error
        assert isinstance(result, list)

    def test_economic_calendar_fetch(self):
        result = fetch_economic_calendar(days_ahead=7)
        assert isinstance(result, list)

    def test_earnings_calendar_fetch(self):
        result = fetch_earnings_calendar(days_ahead=7)
        assert isinstance(result, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
