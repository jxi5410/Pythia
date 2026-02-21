"""
Tests for crypto on-chain signals module.
Run: python -m pytest tests/test_crypto.py -v
Or:  python tests/test_crypto.py  (for individual source testing)
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pythia_live.crypto_onchain import (
    fetch_whale_movements,
    fetch_exchange_flows,
    fetch_funding_rates,
    fetch_fear_greed,
    fetch_crypto_market_data,
    detect_crypto_signals,
    format_crypto_alert,
    format_crypto_summary,
    _cache,
)


def test_fear_greed():
    """Test Alternative.me Fear & Greed Index (most reliable free API)."""
    print("\n--- Fear & Greed Index ---")
    result = fetch_fear_greed()
    print(json.dumps(result, indent=2))
    assert result.get("value") is not None, "Should return a value"
    assert 0 <= result["value"] <= 100
    assert result["classification"] != "unknown"
    print("✅ Fear & Greed OK")
    return result


def test_market_data():
    """Test CoinGecko market data."""
    print("\n--- Crypto Market Data ---")
    result = fetch_crypto_market_data(["bitcoin", "ethereum"])
    print(json.dumps(result, indent=2, default=str))
    assert "bitcoin" in result, "Should have BTC data"
    assert result["bitcoin"]["price"] > 0
    assert "ethereum" in result, "Should have ETH data"
    print("✅ Market Data OK")
    return result


def test_funding_rates():
    """Test funding rates fetch."""
    print("\n--- Funding Rates ---")
    result = fetch_funding_rates()
    print(json.dumps(result, indent=2))
    assert "btc_funding" in result
    assert "signal" in result
    print(f"✅ Funding Rates OK (source: {result.get('source', 'unknown')})")
    return result


def test_whale_movements():
    """Test whale movement detection (may be slow)."""
    print("\n--- Whale Movements ---")
    result = fetch_whale_movements(min_btc=500, hours_back=2)
    print(f"Found {len(result)} whale transactions")
    for w in result[:3]:
        print(f"  {w['btc_amount']:,.0f} BTC (${w['usd_value']/1e6:.1f}M) "
              f"{w['from_type']}→{w['to_type']}")
    print("✅ Whale Movements OK")
    return result


def test_exchange_flows():
    """Test exchange flow estimation."""
    print("\n--- Exchange Flows ---")
    result = fetch_exchange_flows(hours_back=4)
    print(json.dumps(result, indent=2, default=str))
    assert "direction" in result
    print(f"✅ Exchange Flows OK (direction: {result['direction']})")
    return result


def test_signal_detection():
    """Test full signal detection pipeline."""
    print("\n--- Signal Detection ---")
    # Clear cache to test fresh
    _cache.clear()

    # Mock some prediction markets
    mock_markets = [
        {
            "question": "Will Bitcoin drop below $90K by March?",
            "last_price": 0.34,
            "platform": "polymarket",
        },
        {
            "question": "Will ETH reach $5,000 by June 2025?",
            "last_price": 0.12,
            "platform": "polymarket",
        },
        {
            "question": "Will the Fed cut rates in March?",
            "last_price": 0.05,
            "platform": "kalshi",
        },
    ]

    signals = detect_crypto_signals(active_markets=mock_markets)
    print(f"Found {len(signals)} signals")
    for s in signals:
        print(f"\n  Type: {s['type']}, Score: {s.get('score', 0):.0%}")
        for r in s.get("reasons", []):
            print(f"    {r}")
    print("✅ Signal Detection OK")
    return signals


def test_formatting():
    """Test alert formatting."""
    print("\n--- Alert Formatting ---")
    mock_signal = {
        "type": "crypto_onchain",
        "score": 0.75,
        "reasons": [
            "🐋 5,000 BTC ($450M) moved unknown→Coinbase",
            "📊 Exchange inflow: 8,000 BTC ($720M)",
            "💰 Funding rate: +0.0800%",
            "😱 Fear & Greed: 28 (Fear)",
        ],
        "market": {
            "question": "Will BTC drop below $90K?",
            "last_price": 0.34,
        },
    }
    alert = format_crypto_alert(mock_signal)
    print(alert)
    assert "ON-CHAIN" in alert
    assert "🐋" in alert
    print("\n✅ Formatting OK")


if __name__ == "__main__":
    print("=" * 60)
    print("CRYPTO ON-CHAIN SIGNALS — Individual Source Tests")
    print("=" * 60)

    # Run tests in order of reliability/speed
    test_fear_greed()
    test_market_data()
    test_funding_rates()
    test_formatting()

    # These hit mempool.space more heavily
    print("\n" + "=" * 60)
    print("HEAVIER TESTS (whale + flows + full pipeline)")
    print("=" * 60)

    test_whale_movements()
    test_exchange_flows()
    test_signal_detection()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)
