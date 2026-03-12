import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.evidence.news_retrieval import retrieve_candidate_news


def test_retrieve_candidate_news_deduplicates_and_aggregates(monkeypatch):
    monkeypatch.setattr("core.evidence.news_retrieval.newsapi_search", lambda *a, **k: [
        {"headline": "Fed rates unchanged", "published": "2025-01-01T00:00:00"}
    ])
    monkeypatch.setattr("core.evidence.news_retrieval.google_news_rss", lambda *a, **k: [
        {"headline": "Fed rates unchanged", "published": "2025-01-01T00:00:00"},
        {"headline": "Powell speech", "published": "2025-01-01T00:30:00"},
    ])
    monkeypatch.setattr("core.evidence.news_retrieval.duckduckgo_search", lambda *a, **k: [])
    monkeypatch.setattr("core.evidence.news_retrieval.reddit_search", lambda *a, **k: [])

    ctx = {
        "entities": ["Fed", "Powell"],
        "category": "fed_rate",
        "temporal_window": {"start": "2024-12-31T20:00:00", "end": "2025-01-01T02:00:00"},
    }

    out = retrieve_candidate_news(ctx)

    headlines = [x["headline"] for x in out]
    assert len(out) == 2
    assert "Fed rates unchanged" in headlines
    assert "Powell speech" in headlines
