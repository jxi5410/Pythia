"""Tests for equities correlation layer and backtesting framework."""
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

from .equities import (
    get_related_tickers, correlate_spike, format_correlation_alert,
    _move_confirms_spike, _build_summary, CATEGORY_TICKERS,
)


class TestTickerMapping(unittest.TestCase):
    def test_known_categories(self):
        for cat in CATEGORY_TICKERS:
            tickers = get_related_tickers("test", cat)
            self.assertIsInstance(tickers, list)
            self.assertTrue(len(tickers) >= 3)
            self.assertIn("ticker", tickers[0])

    def test_keyword_inference(self):
        tickers = get_related_tickers("Will the Fed cut rates?", "unknown")
        self.assertTrue(any(t["ticker"] == "TLT" for t in tickers))

        tickers = get_related_tickers("Bitcoin price above 100k?", "unknown")
        self.assertTrue(any(t["ticker"] == "BTC-USD" for t in tickers))

        tickers = get_related_tickers("New tariff on China?", "unknown")
        self.assertTrue(any(t["ticker"] == "EEM" for t in tickers))

    def test_fallback(self):
        with patch("subprocess.run", side_effect=Exception("no claude")):
            tickers = get_related_tickers("Something random and obscure", "zzz_unknown")
            self.assertTrue(any(t["ticker"] == "SPY" for t in tickers))


class TestMoveConfirms(unittest.TestCase):
    def test_direct_confirms(self):
        self.assertTrue(_move_confirms_spike("up", "up", "direct", 1.0))
        self.assertFalse(_move_confirms_spike("up", "down", "direct", -1.0))

    def test_inverse_relation(self):
        # Bonds up when spike up (flight to safety confirms)
        self.assertTrue(_move_confirms_spike("up", "up", "inverse_rate", 1.0))

    def test_fear_gauge(self):
        # VIX up on negative spike
        self.assertTrue(_move_confirms_spike("down", "up", "fear_gauge", 2.0))
        self.assertFalse(_move_confirms_spike("up", "up", "fear_gauge", 2.0))

    def test_too_small(self):
        self.assertFalse(_move_confirms_spike("up", "up", "direct", 0.01))


class TestFormatCorrelation(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(format_correlation_alert({"correlated_moves": [], "cross_asset_confidence": "NONE"}), "")

    def test_with_moves(self):
        corr = {
            "correlated_moves": [
                {"ticker": "SPY", "pct_change_4h": 1.5, "confirms_spike": True,
                 "direction": "up", "relation": "broad_market"},
                {"ticker": "TLT", "pct_change_4h": -0.8, "confirms_spike": False,
                 "direction": "down", "relation": "inverse_rate"},
            ],
            "cross_asset_confidence": "MEDIUM",
            "spike_direction": "up",
        }
        text = format_correlation_alert(corr)
        self.assertIn("CROSS-ASSET", text)
        self.assertIn("SPY", text)
        self.assertIn("MEDIUM", text)


class TestBuildSummary(unittest.TestCase):
    def test_no_moves(self):
        self.assertIn("No equity data", _build_summary([], "NONE", "up"))

    def test_minimal_moves(self):
        moves = [{"ticker": "SPY", "pct_change_4h": 0.01, "confirms_spike": True, "direction": "up"}]
        self.assertIn("minimal", _build_summary(moves, "LOW", "up"))


class TestCorrelateSpike(unittest.TestCase):
    @patch("src.pythia_live.equities.get_price_around_spike")
    def test_full_pipeline(self, mock_price):
        mock_price.return_value = {
            "ticker": "SPY", "price_at_spike": 500.0,
            "price_1h_before": 499.0, "price_1h_after": 501.0,
            "price_4h_after": 502.0, "pct_change_1h": 0.4,
            "pct_change_4h": 0.4, "direction": "up",
        }
        result = correlate_spike("Fed rate cut?", "fed_rate",
                                 "2025-01-15T14:00:00Z", "up")
        self.assertIn("cross_asset_confidence", result)
        self.assertIsInstance(result["correlated_moves"], list)
        self.assertTrue(len(result["correlated_moves"]) > 0)

    @patch("src.pythia_live.equities.get_price_around_spike", return_value=None)
    def test_no_data(self, mock_price):
        result = correlate_spike("Test", "fed_rate", "2025-01-15T14:00:00Z", "up")
        self.assertEqual(result["cross_asset_confidence"], "NONE")


if __name__ == "__main__":
    unittest.main()
