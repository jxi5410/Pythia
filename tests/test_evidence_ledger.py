"""
Tests for the EvidenceLedger: deduplication, freshness scoring,
relevance scoring, stance classification, and scenario linkage.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.core.evidence_ledger import (
    EvidenceLedger,
    compute_freshness_score,
    compute_relevance_score,
    _parse_timestamp,
    _detect_source_type,
    _classify_stance,
)
from src.core.models import (
    AttributionRun,
    EvidenceItem,
    EvidenceSourceType,
    EvidenceStance,
    RunStatus,
    Scenario,
    ScenarioEvidenceLinkType,
    ScenarioStatus,
)
from src.core.persistence import RunRepository, init_db


def _utcnow():
    return datetime.now(timezone.utc)


@pytest.fixture
def repo():
    conn = init_db(":memory:")
    return RunRepository(conn)


@pytest.fixture
def run(repo):
    r = AttributionRun(
        spike_event_id=uuid4(), market_id=uuid4(), status=RunStatus.CREATED,
    )
    repo.create_run(r)
    return r


@pytest.fixture
def ledger(repo):
    return EvidenceLedger(repo)


# ══════════════════════════════════════════════════════════════════════
#  Freshness scoring
# ══════════════════════════════════════════════════════════════════════

class TestFreshnessScore:
    def test_just_published_is_near_one(self):
        now = _utcnow()
        score = compute_freshness_score(now, reference_time=now)
        assert score > 0.99

    def test_6_hours_is_half(self):
        now = _utcnow()
        six_ago = now - timedelta(hours=6)
        score = compute_freshness_score(six_ago, reference_time=now)
        assert 0.45 < score < 0.55

    def test_24_hours_is_low(self):
        now = _utcnow()
        day_ago = now - timedelta(hours=24)
        score = compute_freshness_score(day_ago, reference_time=now)
        assert score < 0.1

    def test_none_gives_default(self):
        score = compute_freshness_score(None)
        assert score == 0.3

    def test_future_timestamp_clamps_to_one(self):
        now = _utcnow()
        future = now + timedelta(hours=2)
        score = compute_freshness_score(future, reference_time=now)
        assert score >= 0.99

    def test_monotonic_decay(self):
        """Scores decrease as age increases."""
        now = _utcnow()
        scores = [
            compute_freshness_score(now - timedelta(hours=h), reference_time=now)
            for h in [0, 1, 3, 6, 12, 24]
        ]
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1]


# ══════════════════════════════════════════════════════════════════════
#  Relevance scoring
# ══════════════════════════════════════════════════════════════════════

class TestRelevanceScore:
    def test_no_entities_is_zero(self):
        assert compute_relevance_score("some text", []) == 0.0

    def test_no_text_is_zero(self):
        assert compute_relevance_score("", ["Bitcoin"]) == 0.0

    def test_all_entities_match(self):
        score = compute_relevance_score(
            "Bitcoin and Federal Reserve impact on Treasury yields",
            ["Bitcoin", "Federal Reserve", "Treasury"],
        )
        assert score == 1.0

    def test_partial_match(self):
        score = compute_relevance_score(
            "Bitcoin price surges on whale activity",
            ["Bitcoin", "Federal Reserve", "FOMC", "Treasury"],
        )
        assert 0.2 < score < 0.4

    def test_case_insensitive(self):
        score = compute_relevance_score(
            "bitcoin rally continues",
            ["Bitcoin"],
        )
        assert score > 0.0


# ══════════════════════════════════════════════════════════════════════
#  Normalization helpers
# ══════════════════════════════════════════════════════════════════════

class TestNormalization:
    def test_parse_iso_timestamp(self):
        dt = _parse_timestamp("2025-01-15T12:30:00+00:00")
        assert dt is not None
        assert dt.hour == 12

    def test_parse_z_timestamp(self):
        dt = _parse_timestamp("2025-01-15T12:30:00Z")
        assert dt is not None

    def test_parse_date_only(self):
        dt = _parse_timestamp("2025-01-15")
        assert dt is not None
        assert dt.day == 15

    def test_parse_none(self):
        assert _parse_timestamp(None) is None

    def test_parse_garbage(self):
        assert _parse_timestamp("not a date") is None

    def test_detect_twitter_source(self):
        st = _detect_source_type({"source": "twitter", "data_type": "tweet"})
        assert st == EvidenceSourceType.SOCIAL_MEDIA

    def test_detect_onchain_source(self):
        st = _detect_source_type({"source": "crypto_onchain", "data_type": "whale_movement"})
        assert st == EvidenceSourceType.ON_CHAIN

    def test_detect_news_source(self):
        st = _detect_source_type({"source": "reuters", "data_type": "article"})
        assert st == EvidenceSourceType.NEWS_ARTICLE

    def test_detect_unknown_source(self):
        st = _detect_source_type({"source": "xyz_unknown"})
        assert st == EvidenceSourceType.OTHER

    def test_classify_supports_stance(self):
        stance = _classify_stance(
            {"stance": "supports"}, "evidence text"
        )
        assert stance == EvidenceStance.SUPPORTS

    def test_classify_from_text(self):
        stance = _classify_stance(
            {}, "this evidence strongly supports the hypothesis"
        )
        assert stance == EvidenceStance.SUPPORTS

    def test_classify_weakens_from_text(self):
        stance = _classify_stance(
            {}, "this challenges and contradicts the main narrative"
        )
        assert stance == EvidenceStance.WEAKENS

    def test_classify_neutral_default(self):
        stance = _classify_stance({}, "some neutral information")
        assert stance == EvidenceStance.NEUTRAL


# ══════════════════════════════════════════════════════════════════════
#  Deduplication
# ══════════════════════════════════════════════════════════════════════

class TestDeduplication:
    def test_same_url_deduplicates(self, ledger, run):
        raw1 = {"url": "https://example.com/article1", "title": "First"}
        raw2 = {"url": "https://example.com/article1", "title": "Duplicate"}

        item1 = ledger.ingest_evidence(run.id, raw1, "agent-a")
        item2 = ledger.ingest_evidence(run.id, raw2, "agent-b")

        assert item1 is not None
        assert item2 is None  # deduplicated

    def test_different_urls_both_ingested(self, ledger, run):
        raw1 = {"url": "https://example.com/article1", "title": "First"}
        raw2 = {"url": "https://example.com/article2", "title": "Second"}

        item1 = ledger.ingest_evidence(run.id, raw1, "agent-a")
        item2 = ledger.ingest_evidence(run.id, raw2, "agent-b")

        assert item1 is not None
        assert item2 is not None

    def test_no_url_always_ingested(self, ledger, run):
        """Evidence without URLs are never considered duplicates."""
        raw1 = {"title": "LLM hypothesis A", "summary": "Something"}
        raw2 = {"title": "LLM hypothesis B", "summary": "Something else"}

        item1 = ledger.ingest_evidence(run.id, raw1, "agent-a")
        item2 = ledger.ingest_evidence(run.id, raw2, "agent-a")

        assert item1 is not None
        assert item2 is not None

    def test_same_url_different_runs(self, ledger, repo):
        """Same URL in different runs is NOT a duplicate."""
        run1 = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        run2 = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        repo.create_run(run1)
        repo.create_run(run2)

        raw = {"url": "https://example.com/article", "title": "Test"}

        item1 = ledger.ingest_evidence(run1.id, raw, "agent")
        item2 = ledger.ingest_evidence(run2.id, raw, "agent")

        assert item1 is not None
        assert item2 is not None


# ══════════════════════════════════════════════════════════════════════
#  Ingestion pipeline
# ══════════════════════════════════════════════════════════════════════

class TestIngestion:
    def test_freshness_score_set(self, ledger, run):
        now = _utcnow()
        raw = {
            "title": "Breaking: Fed cuts rates",
            "timestamp": now.isoformat(),
        }
        item = ledger.ingest_evidence(run.id, raw, "macro-agent")
        assert item is not None
        assert item.freshness_score > 0.9

    def test_relevance_score_with_entities(self, ledger, run):
        raw = {
            "title": "Federal Reserve announces rate cut affecting Bitcoin markets",
            "summary": "The Federal Reserve cut rates, Bitcoin surged",
        }
        item = ledger.ingest_evidence(
            run.id, raw, "macro-agent",
            entity_labels=["Federal Reserve", "Bitcoin", "rate cut"],
        )
        assert item is not None
        assert item.relevance_score > 0.5

    def test_source_type_detected(self, ledger, run):
        raw = {
            "title": "Whale alert",
            "source": "crypto_onchain",
            "data_type": "whale_movement",
        }
        item = ledger.ingest_evidence(run.id, raw, "crypto-agent")
        assert item is not None
        assert item.source_type == EvidenceSourceType.ON_CHAIN

    def test_stance_classified(self, ledger, run):
        raw = {
            "title": "Evidence supports rate hike hypothesis",
            "summary": "Strong data supports the claim that rates will rise",
        }
        item = ledger.ingest_evidence(run.id, raw, "agent")
        assert item is not None
        assert item.stance == EvidenceStance.SUPPORTS

    def test_persisted_to_db(self, ledger, run, repo):
        raw = {"title": "Persisted evidence", "url": "https://example.com/test"}
        ledger.ingest_evidence(run.id, raw, "agent")

        evidence = repo.get_evidence(str(run.id))
        assert len(evidence) == 1
        assert evidence[0].title == "Persisted evidence"

    def test_metadata_preserved(self, ledger, run):
        raw = {
            "title": "Test",
            "custom_field": "preserved",
            "source": "twitter",
            "data_type": "tweet",
        }
        item = ledger.ingest_evidence(run.id, raw, "agent")
        assert item.metadata.get("custom_field") == "preserved"
        assert item.metadata.get("source") == "twitter"


# ══════════════════════════════════════════════════════════════════════
#  Scenario linkage
# ══════════════════════════════════════════════════════════════════════

class TestScenarioLinkage:
    def test_link_round_trip(self, ledger, run, repo):
        """Evidence linked to a scenario can be retrieved grouped by type."""
        # Create evidence
        ev1 = ledger.ingest_evidence(run.id, {"title": "Supporting ev"}, "agent")
        ev2 = ledger.ingest_evidence(run.id, {"title": "Challenging ev"}, "agent")
        ev3 = ledger.ingest_evidence(run.id, {"title": "Rebutting ev"}, "agent")

        # Create scenario
        from src.core.models import Scenario as PydanticScenario
        sc = PydanticScenario(
            run_id=run.id, title="Test Scenario",
            mechanism_type="macro", status=ScenarioStatus.PRIMARY,
        )
        repo.save_scenario(sc)

        # Link
        ledger.link_to_scenario(ev1.id, sc.id, "supports", "agent-a")
        ledger.link_to_scenario(ev2.id, sc.id, "challenges", "agent-b")
        ledger.link_to_scenario(ev3.id, sc.id, "rebuts", "agent-a")

        # Retrieve
        grouped = ledger.get_scenario_evidence(sc.id)
        assert len(grouped["supporting"]) == 1
        assert len(grouped["challenging"]) == 1
        assert len(grouped["rebutting"]) == 1
        assert len(grouped["unresolved"]) == 0

        assert grouped["supporting"][0].title == "Supporting ev"
        assert grouped["challenging"][0].title == "Challenging ev"

    def test_link_returns_model(self, ledger, run, repo):
        ev = ledger.ingest_evidence(run.id, {"title": "Test"}, "agent")
        sc = Scenario(
            run_id=run.id, title="S", mechanism_type="m",
        )
        repo.save_scenario(sc)

        link = ledger.link_to_scenario(ev.id, sc.id, "supports", "agent")
        assert link.scenario_id == sc.id
        assert link.evidence_id == ev.id
        assert link.link_type == ScenarioEvidenceLinkType.SUPPORTS

    def test_empty_scenario_returns_all_empty(self, ledger, run, repo):
        sc = Scenario(run_id=run.id, title="Empty", mechanism_type="m")
        repo.save_scenario(sc)

        grouped = ledger.get_scenario_evidence(sc.id)
        assert all(len(v) == 0 for v in grouped.values())


# ══════════════════════════════════════════════════════════════════════
#  Entity-based lookup
# ══════════════════════════════════════════════════════════════════════

class TestEntityLookup:
    def test_find_by_entity(self, ledger, run):
        ledger.ingest_evidence(run.id, {
            "title": "Federal Reserve cuts rates",
            "summary": "The Fed announced a 25bp cut",
        }, "macro")
        ledger.ingest_evidence(run.id, {
            "title": "Bitcoin whale moves 10k BTC",
            "summary": "Large on-chain transfer detected",
        }, "crypto")

        fed_evidence = ledger.get_evidence_by_entity(run.id, "Federal Reserve")
        assert len(fed_evidence) == 1
        assert "Federal Reserve" in fed_evidence[0].title

        btc_evidence = ledger.get_evidence_by_entity(run.id, "Bitcoin")
        assert len(btc_evidence) == 1

    def test_case_insensitive_entity(self, ledger, run):
        ledger.ingest_evidence(run.id, {
            "title": "BITCOIN surge",
        }, "agent")

        results = ledger.get_evidence_by_entity(run.id, "bitcoin")
        assert len(results) == 1

    def test_no_match_returns_empty(self, ledger, run):
        ledger.ingest_evidence(run.id, {"title": "Unrelated stuff"}, "agent")
        results = ledger.get_evidence_by_entity(run.id, "Nonexistent Entity")
        assert len(results) == 0


# ══════════════════════════════════════════════════════════════════════
#  API endpoints
# ══════════════════════════════════════════════════════════════════════

class TestEvidenceAPI:
    def setup_method(self):
        self.conn = init_db(":memory:", check_same_thread=False)
        self.repo = RunRepository(self.conn)

    def test_get_run_evidence(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        self.repo.create_run(run)
        ledger = EvidenceLedger(self.repo)
        ledger.ingest_evidence(run.id, {"title": "E1"}, "a")
        ledger.ingest_evidence(run.id, {"title": "E2"}, "b")

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run.id}/evidence")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["evidence"]) == 2

    def test_get_evidence_by_id(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        self.repo.create_run(run)
        ledger = EvidenceLedger(self.repo)
        item = ledger.ingest_evidence(run.id, {"title": "Specific"}, "a")

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/evidence/{item.id}")

        assert resp.status_code == 200
        assert resp.json()["title"] == "Specific"

    def test_get_evidence_by_scenario(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        self.repo.create_run(run)
        ledger = EvidenceLedger(self.repo)
        ev = ledger.ingest_evidence(run.id, {"title": "Linked"}, "a")
        sc = Scenario(run_id=run.id, title="S", mechanism_type="m")
        self.repo.save_scenario(sc)
        ledger.link_to_scenario(ev.id, sc.id, "supports", "a")

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(
                f"/api/runs/{run.id}/evidence",
                params={"scenario_id": str(sc.id)},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["supporting"]) == 1
        assert body["supporting"][0]["title"] == "Linked"

    def test_get_evidence_not_found(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.api.server import app

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/evidence/{uuid4()}")

        assert resp.status_code == 404
