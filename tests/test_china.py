"""Tests for China data layer modules."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# china_weibo tests
# ---------------------------------------------------------------------------

class TestChinaWeibo:
    def test_bilingual_queries(self):
        from pythia_live.china_weibo import _extract_bilingual_queries
        queries = _extract_bilingual_queries("Will China impose tariffs on US goods?")
        assert any("关税" in q for q in queries), f"Expected Chinese term in {queries}"

    def test_bilingual_queries_multiple(self):
        from pythia_live.china_weibo import _extract_bilingual_queries
        queries = _extract_bilingual_queries("Will Xi Jinping meet with Taiwan officials?")
        chinese = [q for q in queries if any(ord(c) > 0x4E00 for c in q)]
        assert len(chinese) >= 2, f"Expected ≥2 Chinese queries, got {queries}"

    def test_velocity_no_posts(self):
        from pythia_live.china_weibo import calculate_weibo_velocity
        result = calculate_weibo_velocity([])
        assert result["recent_count"] == 0
        assert result["is_spike"] is False

    def test_velocity_spike(self):
        from pythia_live.china_weibo import calculate_weibo_velocity
        now = datetime.now(timezone.utc)
        # Many recent posts, few baseline
        posts = [
            {"timestamp": (now - timedelta(minutes=i)).isoformat(), "reposts": 10, "comments": 5}
            for i in range(20)
        ] + [
            {"timestamp": (now - timedelta(minutes=90 + i * 30)).isoformat(), "reposts": 1, "comments": 0}
            for i in range(2)
        ]
        result = calculate_weibo_velocity(posts, window_minutes=30)
        assert result["velocity_ratio"] > 1
        assert result["recent_count"] > 0

    def test_parse_weibo_time(self):
        from pythia_live.china_weibo import _parse_weibo_time
        assert _parse_weibo_time("刚刚") is not None
        assert _parse_weibo_time("5分钟前") is not None
        assert _parse_weibo_time("2小时前") is not None

    @patch("pythia_live.china_weibo.search_weibo")
    def test_detect_weibo_signal(self, mock_search):
        from pythia_live.china_weibo import detect_weibo_signal
        mock_search.return_value = []
        result = detect_weibo_signal("Will China cut rates?")
        assert result["source"] == "weibo"
        assert result["is_signal"] is False

    @patch("pythia_live.china_weibo.search_weibo")
    def test_search_bilingual(self, mock_search):
        from pythia_live.china_weibo import search_weibo_bilingual
        mock_search.return_value = [
            {"url": "https://m.weibo.cn/detail/1", "reposts": 5, "comments": 3}
        ]
        results = search_weibo_bilingual("Huawei semiconductor ban")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# china_pboc tests
# ---------------------------------------------------------------------------

class TestChinaPboc:
    def test_next_lpr_date(self):
        from pythia_live.china_pboc import _next_lpr_date
        date_str = _next_lpr_date()
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        assert dt.weekday() < 5  # Not a weekend

    def test_fetch_rates_fallback(self):
        from pythia_live.china_pboc import _fetch_rates_fallback
        rates = _fetch_rates_fallback()
        assert rates["lpr_1y"] is not None
        assert rates["mlf_rate"] is not None

    def test_is_china_market(self):
        from pythia_live.china_pboc import _is_china_market
        assert _is_china_market({"title": "Will China stimulate economy?"})
        assert _is_china_market({"title": "PBOC rate cut in 2025?"})
        assert not _is_china_market({"title": "Will the Fed cut rates?"})

    @patch("pythia_live.china_pboc._fetch_rates_eastmoney")
    @patch("pythia_live.china_pboc._fetch_rates_sina")
    def test_fetch_pboc_rates(self, mock_sina, mock_east):
        from pythia_live.china_pboc import fetch_pboc_rates, _cache
        _cache.clear()
        mock_east.return_value = {"lpr_1y": 3.1, "lpr_5y": 3.6, "source": "eastmoney"}
        mock_sina.return_value = {}
        rates = fetch_pboc_rates()
        assert rates["lpr_1y"] == 3.1

    def test_detect_pboc_signal_no_markets(self):
        from pythia_live.china_pboc import detect_pboc_signal, _cache
        _cache.clear()
        result = detect_pboc_signal(None)
        assert result["source"] == "pboc"
        assert result["is_signal"] is False

    def test_format_pboc_alert(self):
        from pythia_live.china_pboc import format_pboc_alert
        alert = format_pboc_alert({
            "rates": {"lpr_1y": 3.1, "lpr_5y": 3.6, "mlf_rate": 2.5, "rrr": 9.5},
            "stance": {"direction": "easing", "signals": ["LPR low"]},
            "matches": [],
        })
        assert "🇨🇳" in alert
        assert "3.1" in alert


# ---------------------------------------------------------------------------
# china_economic tests
# ---------------------------------------------------------------------------

class TestChinaEconomic:
    def test_generate_known_schedule(self):
        from pythia_live.china_economic import _generate_known_schedule
        events = _generate_known_schedule(30)
        assert len(events) > 0
        assert all("indicator" in e for e in events)

    def test_match_events_to_markets(self):
        from pythia_live.china_economic import match_china_events_to_markets
        events = [{"indicator": "CPI YoY", "date": "2025-03-10"}]
        markets = [
            {"title": "China inflation above 2% in March?"},
            {"title": "Will Fed cut rates?"},
        ]
        matches = match_china_events_to_markets(events, markets)
        assert len(matches) >= 1
        assert matches[0]["category"] == "CPI"

    def test_format_macro_alert(self):
        from pythia_live.china_economic import format_china_macro_alert
        alert = format_china_macro_alert({
            "indicator": "NBS Manufacturing PMI",
            "date": "2025-03-01",
            "time_utc": "01:30",
            "forecast": "50.2",
            "previous": "49.8",
            "importance": 3,
        })
        assert "PMI" in alert
        assert "HIGH IMPACT" in alert


# ---------------------------------------------------------------------------
# china_equities tests
# ---------------------------------------------------------------------------

class TestChinaEquities:
    def test_get_tickers_by_category(self):
        from pythia_live.china_equities import get_china_tickers
        tickers = get_china_tickers("", "trade_war")
        assert len(tickers) > 0
        symbols = [t["ticker"] for t in tickers]
        assert "FXI" in symbols

    def test_get_tickers_by_title(self):
        from pythia_live.china_equities import get_china_tickers
        tickers = get_china_tickers("Will BYD overtake Tesla in EV sales?")
        assert any("1211" in t["ticker"] or "NIO" in t["ticker"] for t in tickers)

    def test_get_tickers_taiwan(self):
        from pythia_live.china_equities import get_china_tickers
        tickers = get_china_tickers("Will China invade Taiwan?")
        symbols = [t["ticker"] for t in tickers]
        assert "TSM" in symbols

    def test_correlate_spike_no_yfinance(self):
        from pythia_live.china_equities import correlate_china_spike
        with patch("pythia_live.china_equities.yf", None):
            result = correlate_china_spike(
                "China tariffs", "tariffs",
                "2025-01-15T10:00:00Z", "down"
            )
            assert result["correlations"] == []


# ---------------------------------------------------------------------------
# china_insider tests
# ---------------------------------------------------------------------------

class TestChinaInsider:
    def test_match_insider_to_markets(self):
        from pythia_live.china_insider import match_insider_to_markets
        deals = [{"ticker": "9988", "company": "Alibaba Group"}]
        markets = [
            {"title": "Will China tech regulation increase in 2025?"},
            {"title": "Fed rate decision"},
        ]
        matches = match_insider_to_markets(deals, markets)
        assert len(matches) >= 1
        assert matches[0]["company"] == "Alibaba"

    def test_format_insider_alert(self):
        from pythia_live.china_insider import format_insider_alert
        alert = format_insider_alert({
            "deal": {"ticker": "0700", "company": "Tencent", "transaction_type": "Buy", "date": "2025-01-10"},
            "market": {"title": "China tech regulation"},
            "company": "Tencent",
        })
        assert "🇨🇳" in alert
        assert "Tencent" in alert


# ---------------------------------------------------------------------------
# china_signals (orchestrator) tests
# ---------------------------------------------------------------------------

class TestChinaSignals:
    def test_is_china_related(self):
        from pythia_live.china_signals import _is_china_related
        assert _is_china_related({"title": "China tariff increase?"})
        assert _is_china_related({"title": "PBOC rate cut?"})
        assert not _is_china_related({"title": "US GDP growth?"})

    @patch("pythia_live.china_signals.detect_weibo_signal")
    @patch("pythia_live.china_signals.detect_pboc_signal")
    @patch("pythia_live.china_signals.fetch_nbs_calendar")
    @patch("pythia_live.china_signals.fetch_hkex_insider_deals")
    def test_detect_china_signals(self, mock_insider, mock_cal, mock_pboc, mock_weibo):
        from pythia_live.china_signals import detect_china_signals
        mock_weibo.return_value = {"is_signal": False}
        mock_pboc.return_value = {"is_signal": False, "matches": []}
        mock_cal.return_value = []
        mock_insider.return_value = []

        signals = detect_china_signals([
            {"title": "Will China impose new tariffs?", "price": 0.45},
        ])
        assert isinstance(signals, list)

    def test_format_china_alert_weibo(self):
        from pythia_live.china_signals import format_china_alert
        alert = format_china_alert({
            "source": "weibo",
            "market": {"title": "China tariffs", "price": 0.45},
            "confidence": 0.7,
            "details": {
                "velocity": {"velocity_ratio": 4.5, "recent_count": 20, "recent_engagement": 150},
                "top_posts": [{"text": "重大新闻关税变化"}],
            },
        })
        assert "🇨🇳" in alert
        assert "Weibo" in alert
