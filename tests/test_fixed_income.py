"""
Tests for Fixed Income / CME FedWatch Arbitrage Detector
"""

import pytest
from unittest.mock import patch, MagicMock
from pythia_live.fixed_income import (
    calculate_spread,
    _classify_rate_event,
    _extract_meeting_date,
    _parse_rate_probabilities,
    _build_macro_context,
    _derive_implication,
    _match_fedwatch_probability,
    format_rate_alert,
    detect_rate_signals,
    fetch_macro_indicators,
    fetch_fedwatch_probabilities,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FEDWATCH = {
    "2025-03-19": {
        "cut_50bp": 5.0,
        "cut_25bp": 73.0,
        "hold": 20.0,
        "hike_25bp": 2.0,
        "hike_50bp": 0.0,
        "raw_probabilities": {"400-425": 0.05, "425-450": 0.73, "450-475": 0.20, "475-500": 0.02},
    },
    "2025-05-07": {
        "cut_50bp": 10.0,
        "cut_25bp": 55.0,
        "hold": 30.0,
        "hike_25bp": 5.0,
        "hike_50bp": 0.0,
        "raw_probabilities": {},
    },
}

SAMPLE_MARKETS = [
    {
        "market_title": "Will the Fed cut rates by 25bp in March 2025?",
        "current_price": 0.62,
        "volume": 150000,
        "platform": "polymarket",
        "market_id": "abc123",
        "slug": "fed-cut-march",
        "event_type": "cut_25bp",
        "meeting_date": "2025-03",
    },
    {
        "market_title": "Will the Fed hold rates in March 2025?",
        "current_price": 0.35,
        "volume": 80000,
        "platform": "polymarket",
        "market_id": "def456",
        "slug": "fed-hold-march",
        "event_type": "hold",
        "meeting_date": "2025-03",
    },
    {
        "market_title": "Fed rate cut May FOMC",
        "current_price": 0.45,
        "volume": 50000,
        "platform": "kalshi",
        "market_id": "FED-MAY-CUT",
        "slug": "FED-MAY-CUT",
        "event_type": "cut_25bp",
        "meeting_date": "2025-05",
    },
]


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestClassifyRateEvent:
    def test_cut_25bp(self):
        assert _classify_rate_event("Will the Fed cut rates by 25 basis points?") == "cut_25bp"

    def test_cut_50bp(self):
        assert _classify_rate_event("50bp rate cut in March") == "cut_50bp"

    def test_hold(self):
        assert _classify_rate_event("Fed holds rates unchanged") == "hold"

    def test_hike(self):
        assert _classify_rate_event("Will the Fed raise rates?") == "hike"

    def test_generic_cut(self):
        assert _classify_rate_event("Federal Reserve rate cut") == "cut"

    def test_generic(self):
        assert _classify_rate_event("Something unrelated about rates") == "rate_decision"


class TestExtractMeetingDate:
    def test_march_2025(self):
        assert _extract_meeting_date("Fed rate decision March 2025") == "2025-03"

    def test_jan_short(self):
        result = _extract_meeting_date("Jan 2025 FOMC meeting")
        assert result == "2025-01"

    def test_no_date(self):
        assert _extract_meeting_date("Some random market") is None


class TestCalculateSpread:
    def test_basic_spread(self):
        spreads = calculate_spread(SAMPLE_FEDWATCH, SAMPLE_MARKETS)
        assert len(spreads) > 0

        # March cut_25bp: FedWatch 73% vs Polymarket 62% = 11pt spread
        march_cut = next((s for s in spreads if "cut" in s["event"].lower() and "march" in s["event"].lower()), None)
        if march_cut:
            assert march_cut["fedwatch_prob"] == 73.0
            assert march_cut["polymarket_prob"] == 62.0
            assert march_cut["spread_pct"] == 11.0
            assert march_cut["direction"] == "fedwatch_higher"
            assert march_cut["significance"] == "MEDIUM"

    def test_empty_inputs(self):
        assert calculate_spread({}, []) == []
        assert calculate_spread(SAMPLE_FEDWATCH, []) == []
        assert calculate_spread({}, SAMPLE_MARKETS) == []

    def test_significance_levels(self):
        spreads = calculate_spread(SAMPLE_FEDWATCH, SAMPLE_MARKETS)
        for s in spreads:
            assert s["significance"] in ("HIGH", "MEDIUM", "LOW")

    def test_sorted_by_significance(self):
        spreads = calculate_spread(SAMPLE_FEDWATCH, SAMPLE_MARKETS)
        if len(spreads) >= 2:
            sig_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            for i in range(len(spreads) - 1):
                assert sig_order[spreads[i]["significance"]] <= sig_order[spreads[i + 1]["significance"]]


class TestMatchFedwatch:
    def test_match_by_date(self):
        prob = _match_fedwatch_probability(SAMPLE_FEDWATCH, "cut_25bp", "2025-03")
        assert prob == 73.0

    def test_match_hold(self):
        prob = _match_fedwatch_probability(SAMPLE_FEDWATCH, "hold", "2025-03")
        assert prob == 20.0

    def test_fallback_first_meeting(self):
        prob = _match_fedwatch_probability(SAMPLE_FEDWATCH, "cut_25bp", None)
        # Should match first meeting
        assert prob is not None

    def test_empty_fedwatch(self):
        assert _match_fedwatch_probability({}, "cut_25bp", "2025-03") is None


class TestBuildMacroContext:
    def test_full_context(self):
        macro = {
            "cpi_yoy": 3.1,
            "unemployment_rate": 3.7,
            "fed_funds_rate": 4.5,
            "yield_curve_2s10s": -0.15,
        }
        ctx = _build_macro_context(macro)
        assert "CPI YoY: 3.1%" in ctx
        assert "Unemployment: 3.7%" in ctx
        assert "inverted" in ctx

    def test_empty_macro(self):
        assert _build_macro_context({}) == "Macro data unavailable"

    def test_normal_yield_curve(self):
        macro = {"yield_curve_2s10s": 0.50}
        ctx = _build_macro_context(macro)
        assert "normal" in ctx


class TestDeriveImplication:
    def test_underpricing_cut(self):
        signal = {"direction": "fedwatch_higher", "event_type": "cut_25bp",
                  "spread_pct": 15, "platform": "polymarket"}
        impl = _derive_implication(signal, {}, {})
        assert "underpricing" in impl.lower()

    def test_overpricing_cut(self):
        signal = {"direction": "fedwatch_lower", "event_type": "cut_25bp",
                  "spread_pct": 10, "platform": "kalshi"}
        impl = _derive_implication(signal, {}, {})
        assert "overpricing" in impl.lower()


class TestFormatRateAlert:
    def test_signal_format(self):
        signal = {
            "event": "March FOMC: Fed cut 25bp",
            "fedwatch_prob": 78.0,
            "polymarket_prob": 62.0,
            "spread_pct": 16.0,
            "direction": "fedwatch_higher",
            "significance": "HIGH",
            "platform": "polymarket",
            "macro_context": "CPI cooling (3.1%), 2s10s inverted (-0.15%)",
            "nowcast": {"cpi_nowcast": 2.9},
            "implication": "Polymarket likely underpricing cut probability",
        }
        alert = format_rate_alert(signal)
        assert "💰" in alert
        assert "78%" in alert
        assert "62¢" in alert
        assert "16pts" in alert
        assert "Cleveland Nowcast" in alert

    def test_summary_format(self):
        signal = {
            "significance": "INFO",
            "event": "Summary",
            "macro_context": "CPI: 3.1%",
            "fedwatch_full": SAMPLE_FEDWATCH,
            "nowcast": {},
            "implication": "No divergence",
        }
        alert = format_rate_alert(signal)
        assert "📊" in alert
        assert "FedWatch" in alert


class TestParseRateProbabilities:
    def test_decimal_probs(self):
        probs = {"425-450": 0.73, "450-475": 0.20, "400-425": 0.05, "475-500": 0.02}
        with patch("pythia_live.fixed_income._get_current_fed_funds_rate", return_value=4.50):
            result = _parse_rate_probabilities(probs)
        assert "cut_25bp" in result
        assert "hold" in result
        assert result["raw_probabilities"] == probs


class TestDetectRateSignals:
    @patch("pythia_live.fixed_income.fetch_fedwatch_probabilities")
    @patch("pythia_live.fixed_income.fetch_prediction_market_rates")
    @patch("pythia_live.fixed_income.fetch_macro_indicators")
    @patch("pythia_live.fixed_income.fetch_inflation_nowcast")
    def test_full_pipeline(self, mock_nowcast, mock_macro, mock_pm, mock_fw):
        mock_fw.return_value = SAMPLE_FEDWATCH
        mock_pm.return_value = SAMPLE_MARKETS
        mock_macro.return_value = {"cpi_yoy": 3.1, "fed_funds_rate": 4.5}
        mock_nowcast.return_value = {"cpi_nowcast": 2.9}

        signals = detect_rate_signals()
        assert len(signals) > 0
        for sig in signals:
            assert "implication" in sig
            assert "macro_context" in sig

    @patch("pythia_live.fixed_income.fetch_fedwatch_probabilities")
    @patch("pythia_live.fixed_income.fetch_prediction_market_rates")
    @patch("pythia_live.fixed_income.fetch_macro_indicators")
    @patch("pythia_live.fixed_income.fetch_inflation_nowcast")
    def test_no_data_returns_summary(self, mock_nowcast, mock_macro, mock_pm, mock_fw):
        mock_fw.return_value = {}
        mock_pm.return_value = []
        mock_macro.return_value = {"fed_funds_rate": 4.5}
        mock_nowcast.return_value = {}

        signals = detect_rate_signals()
        assert len(signals) == 1
        assert signals[0]["significance"] == "INFO"


# ---------------------------------------------------------------------------
# Integration-style tests (can be skipped in CI)
# ---------------------------------------------------------------------------

class TestFetchMacroIndicators:
    @pytest.mark.skipif(True, reason="Requires network access")
    def test_live_fetch(self):
        macro = fetch_macro_indicators()
        assert "timestamp" in macro
        # Should have at least some data
        assert len(macro) > 1


class TestFetchFedWatch:
    @pytest.mark.skipif(True, reason="Requires network access")
    def test_live_fetch(self):
        fw = fetch_fedwatch_probabilities()
        # May be empty if CME changes their API, but shouldn't error
        assert isinstance(fw, dict)
