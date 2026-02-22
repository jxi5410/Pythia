#!/usr/bin/env python3
"""Tests for the confluence scorer module."""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from pythia_live.confluence import (
    Signal,
    ConfluenceEvent,
    ConfluenceScorer,
    classify_event_category,
    adapt_equities,
    adapt_congressional,
    adapt_twitter,
    adapt_fixed_income,
    adapt_crypto,
    adapt_macro_calendar,
    adapt_china_signals,
    adapt_causal,
    run_confluence_check,
    format_confluence_alert,
)


def _make_signal(layer: str, direction: str = "bullish",
                 category: str = "fed_rate", confidence: float = 0.7,
                 ts: datetime = None) -> Signal:
    """Helper to create test signals."""
    return Signal(
        layer=layer,
        direction=direction,
        event_category=category,
        confidence=confidence,
        timestamp=ts or datetime.now(timezone.utc),
        description=f"Test signal from {layer}",
        raw_data={"test": True},
    )


class TestClassifyEventCategory(unittest.TestCase):
    def test_fed_rate(self):
        self.assertEqual(classify_event_category("FOMC rate cut decision"), "fed_rate")

    def test_tariffs(self):
        self.assertEqual(classify_event_category("New tariff on Chinese imports trade war"), "tariffs")

    def test_china_macro(self):
        self.assertEqual(classify_event_category("PBOC cuts yuan rate Beijing"), "china_macro")

    def test_fallback(self):
        self.assertEqual(classify_event_category("xyzzy gibberish nothing"), "geopolitical")

    def test_energy(self):
        self.assertEqual(classify_event_category("OPEC crude oil production cut"), "energy")


class TestConfluenceScorer(unittest.TestCase):
    """Core confluence scoring logic."""

    def test_no_signals(self):
        """Empty buffer returns no events."""
        scorer = ConfluenceScorer(min_layers=2)
        events = scorer.check_confluence()
        self.assertEqual(events, [])

    def test_single_signal_no_confluence(self):
        """A single signal does not produce confluence."""
        scorer = ConfluenceScorer(min_layers=2)
        scorer.ingest_signal(_make_signal("equities"))
        events = scorer.check_confluence()
        self.assertEqual(events, [])

    def test_two_layers_basic(self):
        """Two agreeing layers with min_layers=2 triggers confluence."""
        scorer = ConfluenceScorer(min_layers=2)
        scorer.ingest_signal(_make_signal("equities", "bullish", "fed_rate"))
        scorer.ingest_signal(_make_signal("fixed_income", "bullish", "fed_rate"))
        events = scorer.check_confluence()

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_category, "fed_rate")
        self.assertEqual(event.direction, "bullish")
        self.assertEqual(event.layer_count, 2)
        self.assertAlmostEqual(event.confluence_score, 0.3, delta=0.15)

    def test_three_layers_medium(self):
        """Three layers give a medium score (~0.6)."""
        scorer = ConfluenceScorer(min_layers=3)
        for layer in ["equities", "fixed_income", "twitter"]:
            scorer.ingest_signal(_make_signal(layer, "bearish", "recession", 0.8))
        events = scorer.check_confluence()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].layer_count, 3)
        self.assertGreaterEqual(events[0].confluence_score, 0.4)

    def test_four_layers_high(self):
        """Four layers give a high score (>=0.7)."""
        scorer = ConfluenceScorer(min_layers=2)
        for layer in ["equities", "fixed_income", "twitter", "congressional"]:
            scorer.ingest_signal(_make_signal(layer, "bullish", "fed_rate", 0.9))
        events = scorer.check_confluence()

        self.assertEqual(len(events), 1)
        self.assertGreaterEqual(events[0].confluence_score, 0.7)
        self.assertEqual(events[0].layer_count, 4)

    def test_five_layers_very_high(self):
        """Five layers give a very high score (>=0.85)."""
        scorer = ConfluenceScorer(min_layers=2)
        for layer in ["equities", "fixed_income", "twitter", "congressional", "crypto_onchain"]:
            scorer.ingest_signal(_make_signal(layer, "bullish", "fed_rate", 0.9))
        events = scorer.check_confluence()

        self.assertEqual(len(events), 1)
        self.assertGreaterEqual(events[0].confluence_score, 0.85)

    def test_neutral_signals_ignored(self):
        """Neutral direction signals do not contribute to confluence."""
        scorer = ConfluenceScorer(min_layers=2)
        scorer.ingest_signal(_make_signal("equities", "neutral", "fed_rate"))
        scorer.ingest_signal(_make_signal("twitter", "neutral", "fed_rate"))
        events = scorer.check_confluence()
        self.assertEqual(events, [])

    def test_conflicting_directions_separate(self):
        """Bullish and bearish signals on the same category are separate groups."""
        scorer = ConfluenceScorer(min_layers=2)
        scorer.ingest_signal(_make_signal("equities", "bullish", "fed_rate"))
        scorer.ingest_signal(_make_signal("twitter", "bearish", "fed_rate"))
        events = scorer.check_confluence()
        # Neither group has 2 layers
        self.assertEqual(events, [])

    def test_expired_signals_pruned(self):
        """Signals older than the time window are pruned."""
        scorer = ConfluenceScorer(time_window_hours=1, min_layers=2)

        old_ts = datetime.now(timezone.utc) - timedelta(hours=2)
        scorer.ingest_signal(_make_signal("equities", "bullish", "fed_rate", ts=old_ts))
        scorer.ingest_signal(_make_signal("twitter", "bullish", "fed_rate"))

        events = scorer.check_confluence()
        self.assertEqual(events, [])  # old signal was pruned

    def test_duplicate_layer_deduplication(self):
        """Multiple signals from the same layer only count once."""
        scorer = ConfluenceScorer(min_layers=3)
        scorer.ingest_signal(_make_signal("equities", "bullish", "fed_rate", 0.5))
        scorer.ingest_signal(_make_signal("equities", "bullish", "fed_rate", 0.9))
        scorer.ingest_signal(_make_signal("twitter", "bullish", "fed_rate", 0.7))

        events = scorer.check_confluence()
        # Only 2 unique layers (equities, twitter), need 3
        self.assertEqual(events, [])

    def test_category_filter(self):
        """check_confluence with event_category filters results."""
        scorer = ConfluenceScorer(min_layers=2)
        scorer.ingest_signal(_make_signal("equities", "bullish", "fed_rate"))
        scorer.ingest_signal(_make_signal("twitter", "bullish", "fed_rate"))
        scorer.ingest_signal(_make_signal("crypto_onchain", "bearish", "crypto_regulation"))
        scorer.ingest_signal(_make_signal("causal", "bearish", "crypto_regulation"))

        fed_events = scorer.check_confluence(event_category="fed_rate")
        self.assertEqual(len(fed_events), 1)
        self.assertEqual(fed_events[0].event_category, "fed_rate")

        crypto_events = scorer.check_confluence(event_category="crypto_regulation")
        self.assertEqual(len(crypto_events), 1)

    def test_suggested_assets_populated(self):
        """ConfluenceEvent includes suggested assets from asset_map."""
        scorer = ConfluenceScorer(min_layers=2)
        scorer.ingest_signal(_make_signal("equities", "bullish", "fed_rate"))
        scorer.ingest_signal(_make_signal("fixed_income", "bullish", "fed_rate"))
        events = scorer.check_confluence()

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0].suggested_assets, list)

    def test_alert_text_contains_key_info(self):
        """Alert text contains category, direction, and layers."""
        scorer = ConfluenceScorer(min_layers=2)
        scorer.ingest_signal(_make_signal("equities", "bullish", "fed_rate"))
        scorer.ingest_signal(_make_signal("twitter", "bullish", "fed_rate"))
        events = scorer.check_confluence()

        alert = format_confluence_alert(events[0])
        self.assertIn("FED_RATE", alert)
        self.assertIn("BULLISH", alert)
        self.assertIn("equities", alert)
        self.assertIn("twitter", alert)


class TestScoreMethod(unittest.TestCase):
    """Test the score() method directly."""

    def test_empty_signals(self):
        """Scoring empty list returns zero-value event."""
        scorer = ConfluenceScorer()
        event = scorer.score([])
        self.assertEqual(event.confluence_score, 0.0)
        self.assertEqual(event.layer_count, 0)

    def test_time_decay(self):
        """Older signals reduce the confluence score."""
        scorer = ConfluenceScorer(time_window_hours=4)

        fresh = [
            _make_signal("equities", "bullish", "fed_rate", 0.8),
            _make_signal("twitter", "bullish", "fed_rate", 0.8),
            _make_signal("fixed_income", "bullish", "fed_rate", 0.8),
        ]
        fresh_event = scorer.score(fresh)

        old_ts = datetime.now(timezone.utc) - timedelta(hours=3)
        stale = [
            _make_signal("equities", "bullish", "fed_rate", 0.8, ts=old_ts),
            _make_signal("twitter", "bullish", "fed_rate", 0.8, ts=old_ts),
            _make_signal("fixed_income", "bullish", "fed_rate", 0.8, ts=old_ts),
        ]
        stale_event = scorer.score(stale)

        self.assertGreater(fresh_event.confluence_score, stale_event.confluence_score)


class TestLayerAdapters(unittest.TestCase):
    """Test that each adapter correctly transforms module output to Signal."""

    def test_adapt_equities(self):
        data = {
            "moves": [{"ticker": "SPY", "pct_change": 1.5}],
            "cross_asset_confidence": "high",
            "summary": "S&P 500 moved up on fed rate expectations",
        }
        signal = adapt_equities(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.layer, "equities")
        self.assertEqual(signal.direction, "bullish")
        self.assertGreater(signal.confidence, 0.5)

    def test_adapt_equities_empty(self):
        self.assertIsNone(adapt_equities(None))
        self.assertIsNone(adapt_equities({}))
        self.assertIsNone(adapt_equities({"moves": []}))

    def test_adapt_congressional(self):
        data = {
            "is_signal": True,
            "politician": "Nancy Pelosi",
            "ticker": "NVDA",
            "transaction_type": "buy",
            "confidence": 0.75,
            "description": "Pelosi bought NVDA",
        }
        signal = adapt_congressional(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.layer, "congressional")
        self.assertEqual(signal.direction, "bullish")

    def test_adapt_congressional_not_signal(self):
        self.assertIsNone(adapt_congressional({"is_signal": False}))

    def test_adapt_twitter(self):
        data = {
            "is_signal": True,
            "sentiment": "bearish",
            "velocity": {"tweets_per_minute": 15},
            "description": "Negative sentiment on tariff announcement",
        }
        signal = adapt_twitter(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.layer, "twitter")
        self.assertEqual(signal.direction, "bearish")

    def test_adapt_fixed_income(self):
        data = {
            "spread_bps": 15,
            "description": "FedWatch spread: 15bps cut probability",
        }
        signal = adapt_fixed_income(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.layer, "fixed_income")
        self.assertEqual(signal.event_category, "fed_rate")
        self.assertEqual(signal.direction, "bullish")

    def test_adapt_crypto(self):
        data = {
            "is_signal": True,
            "source": "whale_movement",
            "details": {"flow_direction": "exchange_inflow"},
            "confidence": 0.6,
            "description": "Large BTC exchange inflow detected",
        }
        signal = adapt_crypto(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.layer, "crypto_onchain")
        self.assertEqual(signal.direction, "bearish")

    def test_adapt_macro_calendar(self):
        data = {
            "title": "Nonfarm Payrolls",
            "impact": "high",
            "actual": "250",
            "forecast": "200",
        }
        signal = adapt_macro_calendar(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.layer, "macro_calendar")
        self.assertEqual(signal.direction, "bullish")

    def test_adapt_china_signals(self):
        data = {
            "is_signal": True,
            "source": "pboc",
            "details": {"sentiment": "easing"},
            "confidence": 0.7,
            "description": "PBOC rate cut announced",
        }
        signal = adapt_china_signals(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.layer, "china_signals")
        self.assertEqual(signal.event_category, "china_macro")
        self.assertEqual(signal.direction, "bullish")

    def test_adapt_causal(self):
        data = {
            "attribution": {
                "most_likely_cause": "Fed rate cut expectations rising",
                "confidence": "HIGH",
                "trading_implication": "Buy treasury futures",
            }
        }
        signal = adapt_causal(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.layer, "causal")
        self.assertEqual(signal.direction, "bullish")
        self.assertGreater(signal.confidence, 0.7)

    def test_adapt_causal_dry_run(self):
        data = {
            "attribution": {
                "most_likely_cause": "[dry-run — attribution skipped]",
                "confidence": "N/A",
            }
        }
        self.assertIsNone(adapt_causal(data))


class TestRunConfluenceCheck(unittest.TestCase):
    """Integration test for the one-shot convenience function."""

    def test_multi_layer_confluence(self):
        """Three layers agreeing produces a confluence event."""
        events = run_confluence_check(
            equities_data=[{
                "moves": [{"ticker": "SPY", "pct_change": 2.0}],
                "cross_asset_confidence": "high",
                "summary": "S&P rally on FOMC rate cut",
            }],
            fixed_income_data=[{
                "spread_bps": 20,
                "description": "FedWatch showing 80% rate cut probability",
            }],
            twitter_data=[{
                "is_signal": True,
                "sentiment": "bullish",
                "velocity": {"tweets_per_minute": 25},
                "description": "Twitter buzzing about fed rate cut dovish Powell",
            }],
            min_layers=2,
        )
        self.assertGreaterEqual(len(events), 1)

    def test_no_data(self):
        """No data produces no events."""
        events = run_confluence_check()
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
