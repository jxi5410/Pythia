#!/usr/bin/env python3
"""Tests for the congressional trading module."""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from pythia_live.congressional import (
    fetch_recent_trades,
    match_trades_to_markets,
    get_politician_profile,
    detect_congressional_signal,
    format_congressional_alert,
    _normalize_txn,
    _lookup_profile,
    _clean_name,
)


class TestNormalization(unittest.TestCase):
    def test_normalize_txn(self):
        self.assertEqual(_normalize_txn("Purchase"), "buy")
        self.assertEqual(_normalize_txn("Sale (Full)"), "sell")
        self.assertEqual(_normalize_txn("Buy"), "buy")
        self.assertEqual(_normalize_txn("Exchange"), "exchange")
        self.assertEqual(_normalize_txn(""), "unknown")

    def test_clean_name(self):
        self.assertEqual(_clean_name("Hon. Nancy Pelosi"), "Nancy Pelosi")
        self.assertEqual(_clean_name("Sen.  Tommy   Tuberville"), "Tommy Tuberville")

    def test_lookup_profile(self):
        p = _lookup_profile("Nancy Pelosi")
        self.assertEqual(p["party"], "D")
        self.assertEqual(p["chamber"], "House")

        p2 = _lookup_profile("Tuberville")
        self.assertEqual(p2["party"], "R")

        p3 = _lookup_profile("Unknown Person XYZ")
        self.assertEqual(p3, {})


class TestPoliticianProfile(unittest.TestCase):
    def test_known_politician(self):
        p = get_politician_profile("Tommy Tuberville")
        self.assertEqual(p["party"], "R")
        self.assertIn("Armed Services", p["committees"][0])

    def test_unknown_politician(self):
        p = get_politician_profile("John Doe")
        self.assertEqual(p["party"], "?")


@patch("pythia_live.congressional._llm_refine_matches", side_effect=lambda all_m, amb: all_m)
class TestMatchTradesToMarkets(unittest.TestCase):
    def setUp(self):
        self.trades = [
            {
                "politician": "Nancy Pelosi",
                "party": "D",
                "chamber": "House",
                "ticker": "NVDA",
                "transaction_type": "buy",
                "amount_range": "$1,000,001 - $5,000,000",
                "trade_date": "2026-02-10",
                "disclosure_date": "2026-02-20",
                "committees": [],
            },
            {
                "politician": "Tommy Tuberville",
                "party": "R",
                "chamber": "Senate",
                "ticker": "LMT",
                "transaction_type": "buy",
                "amount_range": "$50,001 - $100,000",
                "trade_date": "2026-02-01",
                "disclosure_date": "2026-03-15",
                "committees": ["Armed Services"],
            },
        ]
        self.markets = [
            {
                "question": "Will Congress pass AI regulation by 2026?",
                "description": "Resolution on artificial intelligence safety standards",
                "last_price": 0.35,
            },
            {
                "question": "Will US increase defense spending by 10%?",
                "description": "Annual defense budget increase for military",
                "last_price": 0.62,
            },
            {
                "question": "Will Bitcoin reach $100K?",
                "description": "Crypto price prediction",
                "last_price": 0.45,
            },
        ]

    def test_basic_matching(self, _mock_llm):
        matches = match_trades_to_markets(self.trades, self.markets)
        self.assertTrue(len(matches) > 0)
        # NVDA should match AI market
        nvda_matches = [m for m in matches if m["trade"]["ticker"] == "NVDA"]
        self.assertTrue(any("AI" in m["explanation"] for m in nvda_matches))

    def test_defense_match(self, _mock_llm):
        matches = match_trades_to_markets(self.trades, self.markets)
        lmt_matches = [m for m in matches if m["trade"]["ticker"] == "LMT"]
        self.assertTrue(len(lmt_matches) > 0)
        # Should match defense spending market
        defense_match = [m for m in lmt_matches if "defense" in m["market"]["question"].lower()]
        self.assertTrue(len(defense_match) > 0)

    def test_no_false_positives(self, _mock_llm):
        matches = match_trades_to_markets(self.trades, self.markets)
        # Bitcoin market shouldn't match either trade with high score
        btc_matches = [m for m in matches if "Bitcoin" in m["market"]["question"]]
        for m in btc_matches:
            self.assertLess(m["relevance_score"], 0.5)

    def test_empty_inputs(self, _mock_llm):
        self.assertEqual(match_trades_to_markets([], self.markets), [])
        self.assertEqual(match_trades_to_markets(self.trades, []), [])


class TestFormatAlert(unittest.TestCase):
    def test_format(self):
        signal = {
            "trade": {
                "politician": "Tommy Tuberville",
                "party": "R",
                "chamber": "Senate",
                "ticker": "LMT",
                "transaction_type": "buy",
                "amount_range": "$50,001 - $100,000",
                "trade_date": "2026-01-15",
                "disclosure_date": "2026-03-01",
                "committees": ["Armed Services"],
            },
            "market": {
                "question": "Will US increase defense spending by 10%?",
                "last_price": 0.62,
            },
            "relevance_score": 0.85,
            "disclosure_delay_days": 45,
            "explanation": "Defense sector match",
        }
        text = format_congressional_alert(signal)
        self.assertIn("🏛️ CONGRESSIONAL SIGNAL", text)
        self.assertIn("Tuberville", text)
        self.assertIn("BUY", text)
        self.assertIn("LMT", text)
        self.assertIn("62¢", text)
        self.assertIn("45 days", text)
        self.assertIn("🔴", text)  # High score


class TestFetchWithMock(unittest.TestCase):
    @patch("pythia_live.congressional._fetch_quiver_quant")
    @patch("pythia_live.congressional._fetch_capitol_trades")
    def test_fallback(self, mock_ct, mock_qq):
        mock_qq.return_value = None
        mock_ct.return_value = [{"politician": "Test", "ticker": "TST"}]

        # Clear cache
        from pythia_live.congressional import _cache_path
        cp = _cache_path("trades_7d")
        if cp.exists():
            cp.unlink()

        trades = fetch_recent_trades(7)
        mock_qq.assert_called_once()
        mock_ct.assert_called_once()
        self.assertEqual(len(trades), 1)


if __name__ == "__main__":
    unittest.main()
