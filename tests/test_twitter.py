"""Tests for twitter_signals module."""

import pytest
from datetime import datetime, timezone, timedelta

from pythia_live.twitter_signals import (
    extract_search_terms,
    calculate_tweet_velocity,
    detect_twitter_signal,
    format_twitter_alert,
)


# --- extract_search_terms ---

class TestExtractSearchTerms:
    def test_fed_rate_cut(self):
        terms = extract_search_terms("Will the Fed cut rates in March?")
        assert len(terms) >= 1
        combined = " ".join(terms).lower()
        assert "fed" in combined or "federal reserve" in combined

    def test_bitcoin_etf(self):
        terms = extract_search_terms("Will a Bitcoin ETF be approved by the SEC?")
        combined = " ".join(terms).lower()
        assert "bitcoin" in combined or "btc" in combined
        assert "sec" in combined

    def test_empty_title(self):
        terms = extract_search_terms("")
        assert isinstance(terms, list)

    def test_max_five_terms(self):
        terms = extract_search_terms("Will the Fed FOMC ECB SEC CPI GDP cut rates and approve BTC ETH?")
        assert len(terms) <= 5

    def test_deduplication(self):
        terms = extract_search_terms("Fed Federal Reserve Fed")
        lower_terms = [t.lower() for t in terms]
        assert len(lower_terms) == len(set(lower_terms))


# --- calculate_tweet_velocity ---

def _make_tweet(minutes_ago: int, text: str = "test tweet", author: str = "user1") -> dict:
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "author": author,
        "text": text,
        "timestamp": ts.isoformat(),
        "url": f"https://x.com/{author}/status/{int(ts.timestamp())}",
        "followers": 0,
        "verified": False,
        "engagement": 0,
        "source": "test",
    }


class TestCalculateVelocity:
    def test_empty(self):
        result = calculate_tweet_velocity([], window_minutes=30)
        assert result["total_tweets"] == 0
        assert result["is_accelerating"] is False

    def test_current_window_only(self):
        tweets = [_make_tweet(5), _make_tweet(10), _make_tweet(15)]
        result = calculate_tweet_velocity(tweets, window_minutes=30)
        assert result["total_tweets"] == 3
        assert result["current_window_count"] == 3
        assert result["previous_window_count"] == 0
        assert result["tweets_per_hour"] > 0

    def test_acceleration_detected(self):
        # 5 tweets in current window, 1 in previous
        current = [_make_tweet(i * 5) for i in range(5)]
        previous = [_make_tweet(35)]
        result = calculate_tweet_velocity(current + previous, window_minutes=30)
        assert result["velocity_change_pct"] > 0
        assert result["is_accelerating"] is True

    def test_deceleration(self):
        # 1 tweet in current, 5 in previous
        current = [_make_tweet(5)]
        previous = [_make_tweet(35 + i * 3) for i in range(5)]
        result = calculate_tweet_velocity(current + previous, window_minutes=30)
        assert result["velocity_change_pct"] < 0
        assert result["is_accelerating"] is False

    def test_sentiment_positive(self):
        tweets = [_make_tweet(5, text="bullish surge rally pump moon")]
        result = calculate_tweet_velocity(tweets)
        assert result["sentiment_signal"] == "positive"

    def test_sentiment_negative(self):
        tweets = [_make_tweet(5, text="bearish crash dump tank plunge")]
        result = calculate_tweet_velocity(tweets)
        assert result["sentiment_signal"] == "negative"

    def test_top_authors(self):
        tweets = [
            _make_tweet(5, author="alice"),
            _make_tweet(10, author="alice"),
            _make_tweet(15, author="bob"),
        ]
        result = calculate_tweet_velocity(tweets)
        assert result["top_authors"][0]["author"] == "alice"
        assert result["top_authors"][0]["count"] == 2


# --- detect_twitter_signal (unit-level, no network) ---

class TestDetectSignal:
    def test_returns_required_keys(self, monkeypatch):
        # Mock search to avoid network calls
        monkeypatch.setattr(
            "pythia_live.twitter_signals.search_recent_tweets",
            lambda q, hours_back=2: [_make_tweet(5, text=f"breaking news about {q}")],
        )
        result = detect_twitter_signal("Will Bitcoin hit 100k?")
        assert "signal_detected" in result
        assert "velocity_score" in result
        assert "top_tweets" in result
        assert "summary" in result
        assert 0 <= result["velocity_score"] <= 100

    def test_no_tweets_low_score(self, monkeypatch):
        monkeypatch.setattr(
            "pythia_live.twitter_signals.search_recent_tweets",
            lambda q, hours_back=2: [],
        )
        result = detect_twitter_signal("Will Mars be colonized by 2025?")
        assert result["velocity_score"] == 0
        assert result["signal_detected"] is False


# --- format_twitter_alert ---

class TestFormatAlert:
    def test_basic_format(self):
        signal = {
            "market_title": "Will BTC hit 100k?",
            "velocity_score": 75,
            "velocity": {
                "velocity_change_pct": 200,
                "sentiment_signal": "positive",
            },
            "top_tweets": [{"author": "whale_alert", "text": "Big BTC move incoming"}],
            "leading_indicator": True,
        }
        text = format_twitter_alert(signal)
        assert "TWITTER SIGNAL" in text
        assert "75/100" in text
        assert "whale_alert" in text
        assert "Leading indicator: YES" in text

    def test_no_tweets(self):
        signal = {
            "market_title": "Test",
            "velocity_score": 10,
            "velocity": {"velocity_change_pct": 0, "sentiment_signal": "neutral"},
            "top_tweets": [],
            "leading_indicator": False,
        }
        text = format_twitter_alert(signal)
        assert "TWITTER SIGNAL" in text
        assert "Leading indicator: NO" in text
