"""Tests for Twitter velocity signal detector."""

import logging
from twitter_signals import (
    extract_search_terms,
    calculate_tweet_velocity,
    detect_twitter_signal,
    format_twitter_alert,
)

logging.basicConfig(level=logging.INFO)


def test_extract_terms():
    print("=== Test: extract_search_terms ===")
    cases = [
        "Will the Fed cut rates in March?",
        "Will Trump impose new tariffs on China?",
        "Will Bitcoin reach $100k by end of year?",
        "Will the SEC approve a spot ETH ETF?",
        "Will CPI come in above 3% in February?",
    ]
    for title in cases:
        terms = extract_search_terms(title)
        print(f"  {title}")
        print(f"    → {terms}")
    print()


def test_velocity_calculation():
    print("=== Test: calculate_tweet_velocity (synthetic) ===")
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    # Simulate accelerating tweets: 2 old, 5 recent
    tweets = [
        {"author": "analyst1", "text": "Fed likely to cut rates", "timestamp": (now - timedelta(minutes=50)).isoformat(), "followers": 5000, "verified": True, "engagement": 100, "url": ""},
        {"author": "analyst2", "text": "FOMC meeting preview", "timestamp": (now - timedelta(minutes=45)).isoformat(), "followers": 3000, "verified": False, "engagement": 50, "url": ""},
        {"author": "fedwatcher", "text": "Breaking: Waller signals rate cut", "timestamp": (now - timedelta(minutes=15)).isoformat(), "followers": 50000, "verified": True, "engagement": 5000, "url": ""},
        {"author": "cnbc", "text": "Markets rally on Fed cut hopes", "timestamp": (now - timedelta(minutes=10)).isoformat(), "followers": 1000000, "verified": True, "engagement": 10000, "url": ""},
        {"author": "trader_joe", "text": "Rate cut confirmed, bullish!", "timestamp": (now - timedelta(minutes=8)).isoformat(), "followers": 2000, "verified": False, "engagement": 200, "url": ""},
        {"author": "macro_daily", "text": "Fed pivot incoming, dovish tone", "timestamp": (now - timedelta(minutes=5)).isoformat(), "followers": 15000, "verified": True, "engagement": 3000, "url": ""},
        {"author": "breaking_news", "text": "FOMC rate decision imminent", "timestamp": (now - timedelta(minutes=2)).isoformat(), "followers": 80000, "verified": True, "engagement": 8000, "url": ""},
    ]

    vel = calculate_tweet_velocity(tweets, window_minutes=30)
    print(f"  Total: {vel['total_tweets']}")
    print(f"  Rate: {vel['tweets_per_hour']}/hr")
    print(f"  Change: {vel['velocity_change_pct']}%")
    print(f"  Accelerating: {vel['is_accelerating']}")
    print(f"  Sentiment: {vel['sentiment_signal']}")
    print(f"  Top authors: {vel['top_authors']}")

    assert vel["is_accelerating"], "Should detect acceleration"
    assert vel["sentiment_signal"] == "positive", f"Expected positive, got {vel['sentiment_signal']}"
    print("  ✅ Passed\n")


def test_format_alert():
    print("=== Test: format_twitter_alert ===")
    signal = {
        "market_title": "Will the Fed cut rates in March?",
        "signal_detected": True,
        "velocity_score": 85,
        "velocity": {
            "total_tweets": 15,
            "tweets_per_hour": 20.0,
            "velocity_change_pct": 200.0,
            "top_authors": [{"author": "FedWatcher", "count": 3}],
            "sentiment_signal": "positive",
            "is_accelerating": True,
        },
        "top_tweets": [
            {"author": "FedWatcher", "text": "Waller just signaled March cut is likely", "url": "https://x.com/FedWatcher/status/123"},
        ],
        "leading_indicator": True,
    }
    alert = format_twitter_alert(signal)
    print(alert)
    assert "🐦 TWITTER SIGNAL" in alert
    assert "Leading indicator: YES" in alert
    print("  ✅ Passed\n")


def test_live_search():
    """Live test — actually searches the web. May return 0 results if all sources are blocked."""
    print("=== Test: Live signal detection ===")
    queries = [
        "Will the Fed cut rates in March?",
        "Will Trump impose new tariffs?",
    ]
    for q in queries:
        print(f"\n--- {q} ---")
        result = detect_twitter_signal(q)
        print(f"  Signal: {result['signal_detected']} (score: {result['velocity_score']})")
        print(f"  Terms: {result['search_terms']}")
        print(f"  Tweets found: {result['velocity']['total_tweets']}")
        print(f"  Summary: {result['summary']}")
        if result["top_tweets"]:
            t = result["top_tweets"][0]
            print(f"  Top tweet: @{t['author']}: {t['text'][:80]}")
        print()
        alert = format_twitter_alert(result)
        print(alert)
        print()


if __name__ == "__main__":
    test_extract_terms()
    test_velocity_calculation()
    test_format_alert()
    print("=" * 50)
    print("Live search test (may fail if sources are blocked):")
    print("=" * 50)
    test_live_search()
