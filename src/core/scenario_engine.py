"""
Scenario engine — creates, revises, promotes, dismisses, and clusters scenarios.

Wraps existing bace_scenarios.py clustering logic and adds revision tracking,
"why not" structure for dismissed scenarios, and scenario comparison.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from src.core.models import (
    AgentAction,
    AgentActionType,
    EvidenceItem,
    Scenario,
    ScenarioEvidenceLink,
    ScenarioEvidenceLinkType,
    ScenarioRevision,
    ScenarioRevisionType,
    ScenarioStatus,
)
from src.core.persistence import RunRepository

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Failure mode enum for dismissed scenarios ─────────────────────────

class FailureMode(str, Enum):
    """Why a scenario was dismissed."""
    TIMING = "timing"                  # Evidence timing doesn't fit
    EVIDENCE_QUALITY = "quality"       # Weak or contradicted evidence
    MECHANISM = "mechanism"            # Causal mechanism implausible
    CONTRADICTION = "contradiction"    # Directly contradicted by strong evidence


# ══════════════════════════════════════════════════════════════════════
#  ScenarioEngine
# ══════════════════════════════════════════════════════════════════════

class ScenarioEngine:
    """Creates, revises, promotes, dismisses, and clusters scenarios."""

    def __init__(self, db: RunRepository) -> None:
        self._db = db

    # ── Create ────────────────────────────────────────────────────

    def create_scenario(
        self,
        run_id: UUID | str,
        title: str,
        mechanism_type: str,
        summary: str = "",
        confidence: float = 0.0,
        lead_agents: list[str] | None = None,
        status: str = "alternative",
    ) -> Scenario:
        """Create and persist a new scenario."""
        run_id = UUID(run_id) if isinstance(run_id, str) else run_id
        try:
            sc_status = ScenarioStatus(status)
        except ValueError:
            sc_status = ScenarioStatus.ALTERNATIVE

        scenario = Scenario(
            run_id=run_id,
            title=title,
            mechanism_type=mechanism_type,
            summary=summary,
            confidence_score=max(0.0, min(1.0, confidence)),
            status=sc_status,
            lead_agents=lead_agents or [],
        )
        self._db.save_scenario(scenario)
        return scenario

    # ── Update (with revision tracking) ───────────────────────────

    def update_scenario(
        self,
        scenario_id: UUID | str,
        updates: dict[str, Any],
    ) -> Scenario:
        """Update a scenario and record a revision for audit.

        Supported update keys: confidence_score, summary, title,
        supporting_agents, challenging_agents, what_breaks_this,
        temporal_fit, unresolved_questions, metadata.

        Must include 'reason' and optionally 'triggering_action_id'.
        """
        scenario_id_str = str(scenario_id)
        scenario = self._db.get_scenario_by_id(scenario_id_str)
        if scenario is None:
            raise ValueError(f"Scenario {scenario_id_str} not found")

        reason = updates.pop("reason", "")
        triggering_action_id = updates.pop("triggering_action_id", None)
        if triggering_action_id and isinstance(triggering_action_id, str):
            triggering_action_id = UUID(triggering_action_id)

        old_confidence = scenario.confidence_score
        new_confidence = updates.get("confidence_score", old_confidence)

        # Determine revision type
        if "confidence_score" in updates and new_confidence != old_confidence:
            rev_type = ScenarioRevisionType.CONFIDENCE_UPDATED
        else:
            rev_type = ScenarioRevisionType.CONFIDENCE_UPDATED

        # Apply updates to the scenario
        for key, value in updates.items():
            if hasattr(scenario, key):
                setattr(scenario, key, value)
        scenario.updated_at = _utcnow()

        # Persist updated scenario
        self._db.update_scenario(scenario)

        # Record revision
        revision = ScenarioRevision(
            scenario_id=scenario.id,
            run_id=scenario.run_id,
            revision_type=rev_type,
            previous_confidence=old_confidence,
            new_confidence=max(0.0, min(1.0, new_confidence)),
            reason=reason,
            triggering_action_id=triggering_action_id,
        )
        self._db.save_scenario_revision(revision)

        return scenario

    # ── Promote ───────────────────────────────────────────────────

    def promote_scenario(
        self,
        scenario_id: UUID | str,
        reason: str,
    ) -> Scenario:
        """Promote a scenario to primary status."""
        scenario_id_str = str(scenario_id)
        scenario = self._db.get_scenario_by_id(scenario_id_str)
        if scenario is None:
            raise ValueError(f"Scenario {scenario_id_str} not found")

        old_status = scenario.status
        if old_status == ScenarioStatus.PRIMARY:
            return scenario  # already primary

        return self.update_scenario(scenario_id, {
            "status": ScenarioStatus.PRIMARY,
            "reason": reason,
        })

    # ── Dismiss (with "why not" structure) ────────────────────────

    def dismiss_scenario(
        self,
        scenario_id: UUID | str,
        reason: str,
        decisive_evidence_id: str | None = None,
        decisive_challenge_action_id: str | None = None,
        failure_mode: str | FailureMode = FailureMode.MECHANISM,
    ) -> Scenario:
        """Dismiss a scenario and record the "why not" structure.

        The "why not" is captured in a ScenarioRevision with metadata
        persisted in the scenario's metadata field:
        - why_lost: human-readable reason
        - failure_mode: timing | quality | mechanism | contradiction
        - weakening_evidence_ids: evidence that weakened it
        - decisive_critique_action_id: the action that sealed the dismissal
        """
        scenario_id_str = str(scenario_id)
        scenario = self._db.get_scenario_by_id(scenario_id_str)
        if scenario is None:
            raise ValueError(f"Scenario {scenario_id_str} not found")

        if isinstance(failure_mode, str):
            try:
                failure_mode = FailureMode(failure_mode)
            except ValueError:
                failure_mode = FailureMode.MECHANISM

        # Build "why not" metadata
        why_not = {
            "why_lost": reason,
            "failure_mode": failure_mode.value,
            "weakening_evidence_ids": [],
            "decisive_critique_action_id": decisive_challenge_action_id,
        }
        if decisive_evidence_id:
            why_not["weakening_evidence_ids"].append(decisive_evidence_id)

        # Merge into scenario metadata
        existing_meta = dict(scenario.metadata) if scenario.metadata else {}
        existing_meta["why_not"] = why_not

        triggering_id = (
            UUID(decisive_challenge_action_id)
            if decisive_challenge_action_id else None
        )

        return self.update_scenario(scenario_id, {
            "status": ScenarioStatus.DISMISSED,
            "confidence_score": 0.0,
            "metadata": existing_meta,
            "reason": reason,
            "triggering_action_id": str(triggering_id) if triggering_id else None,
        })

    # ── Cluster from actions ──────────────────────────────────────

    def cluster_from_actions(
        self,
        run_id: UUID | str,
        actions: list[AgentAction],
        evidence: list[EvidenceItem],
    ) -> list[Scenario]:
        """Group debate actions into formal Scenario objects.

        Delegates to bace_scenarios.cluster_hypotheses_into_scenarios
        for the actual clustering logic, then wraps the results as
        Pydantic Scenario models and persists them.
        """
        run_id = UUID(run_id) if isinstance(run_id, str) else run_id

        # Build hypothesis-like dicts from PROPOSE actions for bace_scenarios
        hypotheses = []
        for action in actions:
            if action.action_type != AgentActionType.PROPOSE:
                continue
            hypotheses.append({
                "id": str(action.id),
                "agent": action.agent_name,
                "agent_name": action.agent_name,
                "cause": action.content,
                "confidence": action.confidence_after,
                "confidence_score": action.confidence_after,
                "reasoning": action.content,
                "status": "survived",
                "evidence": [],
                "evidence_urls": [],
                "impact_speed": "",
                "time_to_peak": "",
            })

        if not hypotheses:
            return []

        # Apply confidence updates from later actions
        hyp_by_agent: dict[str, dict] = {}
        for h in hypotheses:
            hyp_by_agent[h["agent"]] = h

        for action in actions:
            if action.action_type == AgentActionType.UPDATE_CONFIDENCE:
                target = hyp_by_agent.get(action.agent_name)
                if target:
                    target["confidence"] = action.confidence_after
                    target["confidence_score"] = action.confidence_after

            elif action.action_type == AgentActionType.CONCEDE:
                target = hyp_by_agent.get(action.agent_name)
                if target:
                    target["status"] = "debunked"
                    target["confidence"] = 0.0
                    target["confidence_score"] = 0.0

        # Call the legacy clustering logic
        from src.core.bace_scenarios import cluster_hypotheses_into_scenarios
        legacy_scenarios = cluster_hypotheses_into_scenarios(hypotheses)

        # Convert legacy Scenario dataclasses → Pydantic models, persist
        status_map = {
            "primary": ScenarioStatus.PRIMARY,
            "alternative": ScenarioStatus.ALTERNATIVE,
            "dismissed": ScenarioStatus.DISMISSED,
        }

        pydantic_scenarios: list[Scenario] = []
        for ls in legacy_scenarios:
            sc = Scenario(
                run_id=run_id,
                title=ls.label,
                mechanism_type=ls.mechanism,
                summary=ls.causal_chain,
                confidence_score=ls.confidence,
                status=status_map.get(ls.tier, ScenarioStatus.ALTERNATIVE),
                lead_agents=[ls.lead_agent] if ls.lead_agent else [],
                supporting_agents=ls.supporting_agents,
                challenging_agents=ls.challenging_agents,
                what_breaks_this=[ls.what_breaks_this] if ls.what_breaks_this else [],
                temporal_fit=ls.temporal_fit,
                metadata={
                    "hypothesis_ids": ls.hypothesis_ids,
                    "evidence_chain": ls.evidence_chain,
                    "evidence_urls": ls.evidence_urls,
                    "impact_speed": ls.impact_speed,
                    "time_to_peak": ls.time_to_peak,
                    "legacy_id": ls.id,
                },
            )
            self._db.save_scenario(sc)
            pydantic_scenarios.append(sc)

        logger.info(
            "Clustered %d actions into %d scenarios for run %s",
            len(actions), len(pydantic_scenarios), run_id,
        )
        return pydantic_scenarios

    # ── Scenario comparison ───────────────────────────────────────

    def get_scenario_comparison(
        self,
        scenario_id_a: UUID | str,
        scenario_id_b: UUID | str,
    ) -> dict[str, Any]:
        """Compare two scenarios: evidence overlap, disagreements, critiques."""
        sc_a = self._db.get_scenario_by_id(str(scenario_id_a))
        sc_b = self._db.get_scenario_by_id(str(scenario_id_b))
        if sc_a is None or sc_b is None:
            raise ValueError("One or both scenarios not found")

        # Evidence overlap
        links_a = self._db.get_evidence_links_by_scenario(str(sc_a.id))
        links_b = self._db.get_evidence_links_by_scenario(str(sc_b.id))

        ev_ids_a = {str(l.evidence_id) for l in links_a}
        ev_ids_b = {str(l.evidence_id) for l in links_b}
        shared = ev_ids_a & ev_ids_b
        only_a = ev_ids_a - ev_ids_b
        only_b = ev_ids_b - ev_ids_a

        # Agent disagreements
        agents_a = set(sc_a.supporting_agents + sc_a.lead_agents)
        agents_b = set(sc_b.supporting_agents + sc_b.lead_agents)
        challengers_a = set(sc_a.challenging_agents)
        challengers_b = set(sc_b.challenging_agents)

        # Agents supporting A but challenging B (or vice versa)
        disagreement_points = []
        for agent in agents_a & challengers_b:
            disagreement_points.append({
                "agent": agent,
                "supports": str(sc_a.id),
                "challenges": str(sc_b.id),
            })
        for agent in agents_b & challengers_a:
            disagreement_points.append({
                "agent": agent,
                "supports": str(sc_b.id),
                "challenges": str(sc_a.id),
            })

        return {
            "scenario_a": {"id": str(sc_a.id), "title": sc_a.title, "confidence": sc_a.confidence_score},
            "scenario_b": {"id": str(sc_b.id), "title": sc_b.title, "confidence": sc_b.confidence_score},
            "evidence_overlap": {
                "shared_count": len(shared),
                "shared_ids": sorted(shared),
                "only_a_count": len(only_a),
                "only_b_count": len(only_b),
            },
            "disagreement_points": disagreement_points,
            "confidence_gap": abs(sc_a.confidence_score - sc_b.confidence_score),
        }
