#!/usr/bin/env python3
"""Test script for equities correlation layer."""
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from pythia_live.equities import (
    get_related_tickers,
    get_price_around_spike,
    correlate_spike,
    format_correlation_alert,
)

def test_ticker_mapping():
    print("=== Test: Ticker Mapping ===")
    for title, cat in [
        ("Will the Fed cut rates in March?", "fed_rate"),
        ("Bitcoin above 100K?", "crypto"),
        ("US-China tariff escalation?", "trade_war"),
    ]:
        tickers = get_related_tickers(title, cat)
        print(f"  {cat}: {[t['ticker'] for t in tickers]}")
    print()

def test_correlation():
    print("=== Test: Full Correlation ===")
    # Use a recent-ish time (market hours)
    from datetime import datetime, timedelta
    # Use last Friday at 2pm ET as a reasonable test time
    now = datetime.now()
    # Go back to find a recent weekday
    test_time = now - timedelta(days=1)
    while test_time.weekday() >= 5:  # Skip weekends
        test_time -= timedelta(days=1)
    test_time = test_time.replace(hour=14, minute=0, second=0)

    result = correlate_spike(
        market_title="Will the Fed cut rates in March 2025?",
        category="fed_rate",
        spike_time=test_time.isoformat(),
        spike_direction="up",
    )

    print(f"  Confidence: {result['cross_asset_confidence']}")
    print(f"  Moves found: {len(result['correlated_moves'])}")
    for m in result["correlated_moves"]:
        print(f"    {m['ticker']}: {m['pct_change_4h']:+.2f}% ({m['direction']}) "
              f"{'✓' if m['confirms_spike'] else '✗'}")

    alert_text = format_correlation_alert(result)
    if alert_text:
        print(f"\n  Alert:\n{alert_text}")
    else:
        print("  (no significant moves to alert)")
    print()

if __name__ == "__main__":
    test_ticker_mapping()
    test_correlation()
    print("✅ All tests passed")
