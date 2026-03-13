"""
Evidence ledger — normalizes, deduplicates, scores, and links evidence.

Sits between raw evidence sources (bace_evidence_provider, news fetchers)
and the persistence layer. Every piece of evidence ingested through the
ledger gets a freshness score, relevance score, stance classification,
and deduplication check before it hits the database.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.core.models import (
    EvidenceItem,
    EvidenceSourceType,
    EvidenceStance,
    ScenarioEvidenceLink,
    ScenarioEvidenceLinkType,
)
from src.core.persistence import RunRepository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Source type detection ─────────────────────────────────────────────

_SOURCE_PATTERNS: list[tuple[str, EvidenceSourceType]] = [
    ("twitter", EvidenceSourceType.SOCIAL_MEDIA),
    ("tweet", EvidenceSourceType.SOCIAL_MEDIA),
    ("reddit", EvidenceSourceType.REDDIT),
    ("r/", EvidenceSourceType.REDDIT),
    ("congress", EvidenceSourceType.CONGRESSIONAL),
    ("gov", EvidenceSourceType.GOVERNMENT_FILING),
    ("sec.gov", EvidenceSourceType.GOVERNMENT_FILING),
    ("cftc", EvidenceSourceType.GOVERNMENT_FILING),
    ("on-chain", EvidenceSourceType.ON_CHAIN),
    ("onchain", EvidenceSourceType.ON_CHAIN),
    ("blockchain", EvidenceSourceType.ON_CHAIN),
    ("whale", EvidenceSourceType.ON_CHAIN),
    ("orderbook", EvidenceSourceType.ORDERBOOK),
    ("order_book", EvidenceSourceType.ORDERBOOK),
    ("depth", EvidenceSourceType.ORDERBOOK),
    ("cme", EvidenceSourceType.MARKET_DATA),
    ("fedwatch", EvidenceSourceType.MARKET_DATA),
    ("market_data", EvidenceSourceType.MARKET_DATA),
    ("equities", EvidenceSourceType.MARKET_DATA),
    ("calendar", EvidenceSourceType.ECONOMIC_CALENDAR),
    ("economic", EvidenceSourceType.ECONOMIC_CALENDAR),
    ("fomc", EvidenceSourceType.ECONOMIC_CALENDAR),
    ("news", EvidenceSourceType.NEWS_ARTICLE),
    ("reuters", EvidenceSourceType.NEWS_ARTICLE),
    ("bloomberg", EvidenceSourceType.NEWS_ARTICLE),
    ("ap ", EvidenceSourceType.NEWS_ARTICLE),
]

_STANCE_SUPPORTS = {"support", "supports", "confirms", "bullish", "positive", "corroborates"}
_STANCE_WEAKENS = {"challenge", "challenges", "weakens", "bearish", "negative", "contradicts", "rebuts"}


# ── Scoring functions ─────────────────────────────────────────────────

def compute_freshness_score(
    publication_time: datetime | None,
    reference_time: datetime | None = None,
) -> float:
    """Score freshness on [0, 1] using exponential decay.

    - 0 hours old → 1.0
    - 6 hours old → ~0.5
    - 24 hours old → ~0.06
    - None / unparseable → 0.3 (unknown, moderate penalty)

    Uses half-life of 6 hours: score = exp(-0.693 * hours / 6).
    """
    if publication_time is None:
        return 0.3

    ref = reference_time or _utcnow()
    # Ensure both are offset-aware for subtraction
    if publication_time.tzinfo is None:
        publication_time = publication_time.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    hours = max((ref - publication_time).total_seconds() / 3600, 0.0)
    half_life = 6.0
    return math.exp(-0.693 * hours / half_life)


def compute_relevance_score(
    evidence_text: str,
    entity_labels: list[str],
) -> float:
    """Score relevance [0, 1] based on entity overlap.

    Each entity label found in the evidence text contributes to the score.
    Score = min(1.0, matches / max(3, total_entities)).
    """
    if not entity_labels or not evidence_text:
        return 0.0

    text_lower = evidence_text.lower()
    matches = sum(1 for label in entity_labels if label.lower() in text_lower)
    denominator = max(3, len(entity_labels))
    return min(1.0, matches / denominator)


# ── Normalization helpers ─────────────────────────────────────────────

def _parse_timestamp(raw: str | None) -> datetime | None:
    """Best-effort parse of various timestamp formats."""
    if not raw:
        return None
    raw = raw.strip()
    # Try ISO 8601 first
    for fmt in (raw, raw.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(fmt)
        except (ValueError, TypeError):
            pass
    # Try common formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return None


def _detect_source_type(raw: dict[str, Any]) -> EvidenceSourceType:
    """Detect source type from raw evidence dict fields."""
    haystack = " ".join(str(v) for v in [
        raw.get("source", ""),
        raw.get("data_type", ""),
        raw.get("url", raw.get("source_url", "")),
    ]).lower()

    for pattern, source_type in _SOURCE_PATTERNS:
        if pattern in haystack:
            return source_type

    return EvidenceSourceType.OTHER


def _classify_stance(raw: dict[str, Any], text: str) -> EvidenceStance:
    """Classify evidence stance from explicit field or text analysis."""
    explicit = str(raw.get("stance", raw.get("timing_vs_spike", ""))).lower()
    if explicit in _STANCE_SUPPORTS:
        return EvidenceStance.SUPPORTS
    if explicit in _STANCE_WEAKENS:
        return EvidenceStance.WEAKENS

    text_lower = text.lower()
    supports_signals = sum(1 for w in _STANCE_SUPPORTS if w in text_lower)
    weakens_signals = sum(1 for w in _STANCE_WEAKENS if w in text_lower)

    if supports_signals > weakens_signals:
        return EvidenceStance.SUPPORTS
    if weakens_signals > supports_signals:
        return EvidenceStance.WEAKENS
    return EvidenceStance.NEUTRAL


# ══════════════════════════════════════════════════════════════════════
#  EvidenceLedger
# ══════════════════════════════════════════════════════════════════════

class EvidenceLedger:
    """Normalizes, deduplicates, scores, and persists evidence items."""

    def __init__(self, db: RunRepository) -> None:
        self._db = db

    def ingest_evidence(
        self,
        run_id: UUID | str,
        raw_evidence: dict[str, Any],
        provider_agent: str,
        entity_labels: list[str] | None = None,
    ) -> EvidenceItem | None:
        """Normalize, deduplicate, score, and persist a single evidence item.

        Returns the persisted EvidenceItem, or None if it was a duplicate.
        """
        run_id = UUID(run_id) if isinstance(run_id, str) else run_id

        # Extract fields
        source_url = raw_evidence.get("url", raw_evidence.get("source_url"))
        title = raw_evidence.get("title", raw_evidence.get("headline", ""))
        summary = raw_evidence.get("summary", raw_evidence.get("content", title))
        if not title and summary:
            title = summary[:200]

        # Deduplicate by source_url within run
        if source_url:
            existing = self._db.get_evidence(str(run_id))
            for ex in existing:
                if ex.source_url and ex.source_url == source_url:
                    return None

        # Parse publication timestamp
        pub_ts = _parse_timestamp(
            raw_evidence.get("timestamp",
            raw_evidence.get("publication_timestamp",
            raw_evidence.get("published_at")))
        )

        # Detect source type
        explicit_source = raw_evidence.get("source_type")
        if explicit_source:
            try:
                source_type = EvidenceSourceType(explicit_source)
            except ValueError:
                source_type = _detect_source_type(raw_evidence)
        else:
            source_type = _detect_source_type(raw_evidence)

        # Score freshness
        freshness = compute_freshness_score(pub_ts)

        # Score relevance
        search_text = f"{title} {summary}"
        relevance = compute_relevance_score(search_text, entity_labels or [])

        # Classify stance
        stance = _classify_stance(raw_evidence, search_text)

        # Confidence impact: positive for supports, negative for weakens
        confidence_raw = raw_evidence.get("confidence", raw_evidence.get("confidence_impact", 0.0))
        try:
            confidence_impact = float(confidence_raw)
        except (ValueError, TypeError):
            confidence_impact = 0.0
        if stance == EvidenceStance.WEAKENS and confidence_impact > 0:
            confidence_impact = -confidence_impact

        item = EvidenceItem(
            run_id=run_id,
            title=title[:500],
            source_url=source_url,
            source_type=source_type,
            publication_timestamp=pub_ts,
            provider_agent=provider_agent,
            summary=summary[:2000] if summary else "",
            relevance_score=round(relevance, 4),
            freshness_score=round(freshness, 4),
            confidence_impact=max(-1.0, min(1.0, confidence_impact)),
            stance=stance,
            metadata={
                k: v for k, v in raw_evidence.items()
                if k not in ("url", "source_url", "title", "headline",
                             "summary", "content", "timestamp",
                             "publication_timestamp", "published_at")
            },
        )

        self._db.save_evidence(item)
        return item

    def link_to_scenario(
        self,
        evidence_id: UUID | str,
        scenario_id: UUID | str,
        link_type: str | ScenarioEvidenceLinkType,
        agent_name: str = "",
    ) -> ScenarioEvidenceLink:
        """Create a link between an evidence item and a scenario."""
        if isinstance(link_type, str):
            link_type = ScenarioEvidenceLinkType(link_type)
        evidence_id = UUID(evidence_id) if isinstance(evidence_id, str) else evidence_id
        scenario_id = UUID(scenario_id) if isinstance(scenario_id, str) else scenario_id

        link = ScenarioEvidenceLink(
            scenario_id=scenario_id,
            evidence_id=evidence_id,
            link_type=link_type,
            agent_name=agent_name,
        )
        self._db.save_evidence_link(link)
        return link

    def get_scenario_evidence(
        self, scenario_id: UUID | str,
    ) -> dict[str, list[EvidenceItem]]:
        """Get evidence linked to a scenario, grouped by link type.

        Returns dict with keys: supporting, challenging, rebutting, unresolved.
        """
        scenario_id_str = str(scenario_id)
        links = self._db.get_evidence_links_by_scenario(scenario_id_str)

        result: dict[str, list[EvidenceItem]] = {
            "supporting": [],
            "challenging": [],
            "rebutting": [],
            "unresolved": [],
        }

        for link in links:
            evidence = self._db.get_evidence_by_id(str(link.evidence_id))
            if evidence is None:
                continue

            key = {
                ScenarioEvidenceLinkType.SUPPORTS: "supporting",
                ScenarioEvidenceLinkType.CHALLENGES: "challenging",
                ScenarioEvidenceLinkType.REBUTS: "rebutting",
            }.get(link.link_type, "unresolved")
            result[key].append(evidence)

        return result

    def get_evidence_by_entity(
        self, run_id: UUID | str, entity_label: str,
    ) -> list[EvidenceItem]:
        """Get all evidence for a run that mentions the given entity label."""
        all_evidence = self._db.get_evidence(str(run_id))
        label_lower = entity_label.lower()
        return [
            ev for ev in all_evidence
            if label_lower in f"{ev.title} {ev.summary}".lower()
        ]
