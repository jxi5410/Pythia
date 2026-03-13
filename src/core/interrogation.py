"""
InterrogationEngine — structured, DB-backed post-attribution interrogation.

Provides artifact-aware context loading and session persistence for
questioning scenarios, agents, evidence, graph nodes/edges, actions,
and governance decisions produced by attribution runs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any, Callable
from uuid import UUID

from src.core.models import (
    AnswerMode,
    InterrogationMessage,
    InterrogationRole,
    InterrogationSession,
    InterrogationTargetType,
)
from src.core.persistence import RunRepository


class InterrogationEngine:
    """Structured interrogation of attribution run artifacts."""

    def __init__(
        self,
        db: RunRepository,
        llm_client: Callable[[str], str],
    ) -> None:
        self._db = db
        self._llm_client = llm_client

    # ── Session management ───────────────────────────────────────────

    def create_session(
        self,
        run_id: UUID | str,
        target_type: str,
        target_id: UUID | str,
    ) -> InterrogationSession:
        run_uuid = UUID(str(run_id))
        target_uuid = UUID(str(target_id))

        try:
            tt = InterrogationTargetType(target_type)
        except ValueError:
            raise ValueError(
                f"Invalid target_type '{target_type}'. "
                f"Must be one of: {[t.value for t in InterrogationTargetType]}"
            )

        session = InterrogationSession(
            run_id=run_uuid,
            target_type=tt,
            target_id=target_uuid,
        )
        self._db.save_interrogation_session(session)
        return session

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = self._db.get_interrogation_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found")

        messages = self._db.get_interrogation_messages(session_id)
        return {
            "session": session.model_dump(mode="json"),
            "messages": [m.model_dump(mode="json") for m in messages],
        }

    # ── Ask (streaming) ──────────────────────────────────────────────

    async def ask(
        self,
        session_id: str,
        question: str,
        answer_mode: str = "concise",
    ) -> AsyncGenerator[str, None]:
        session = self._db.get_interrogation_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found")

        try:
            mode = AnswerMode(answer_mode)
        except ValueError:
            mode = AnswerMode.CONCISE

        # Persist user message
        user_msg = InterrogationMessage(
            session_id=session.id,
            role=InterrogationRole.USER,
            content=question,
            answer_mode=mode,
        )
        self._db.save_interrogation_message(user_msg)

        # Build context and prompt
        context = self.build_context(
            str(session.run_id),
            session.target_type.value,
            str(session.target_id),
        )
        history = self._db.get_interrogation_messages(session_id)
        prompt = self._build_prompt(
            session.target_type.value, context, history, question, mode,
        )

        # Call LLM in executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._llm_client, prompt)

        # Persist assistant message
        assistant_msg = InterrogationMessage(
            session_id=session.id,
            role=InterrogationRole.ASSISTANT,
            content=response,
            answer_mode=mode,
        )
        self._db.save_interrogation_message(assistant_msg)

        # Stream in chunks
        chunk_size = 40
        for i in range(0, len(response), chunk_size):
            chunk = response[i : i + chunk_size]
            yield f"data: {json.dumps({'text': chunk})}\n\n"
            await asyncio.sleep(0.02)

        yield "data: [DONE]\n\n"

    # ── Context building ─────────────────────────────────────────────

    def build_context(
        self,
        run_id: str,
        target_type: str,
        target_id: str,
    ) -> dict[str, Any]:
        builders = {
            "scenario": self._ctx_scenario,
            "agent": self._ctx_agent,
            "evidence": self._ctx_evidence,
            "node": self._ctx_node,
            "edge": self._ctx_edge,
            "action": self._ctx_action,
            "governance": self._ctx_governance,
        }
        builder = builders.get(target_type)
        if builder is None:
            return {"error": f"Unknown target_type: {target_type}"}
        return builder(run_id, target_id)

    def _ctx_scenario(self, run_id: str, target_id: str) -> dict[str, Any]:
        scenario = self._db.get_scenario_by_id(target_id)
        if scenario is None:
            return {"error": "Scenario not found"}

        links = self._db.get_evidence_links_by_scenario(target_id)
        evidence = []
        for link in links:
            ev = self._db.get_evidence_by_id(str(link.evidence_id))
            if ev:
                evidence.append({
                    "evidence": ev.model_dump(mode="json"),
                    "link_type": link.link_type.value,
                })

        revisions = self._db.get_scenario_revisions(target_id)
        actions = [
            a for a in self._db.get_actions(run_id)
            if str(a.target_scenario_id) == target_id
        ]

        return {
            "target_type": "scenario",
            "scenario": scenario.model_dump(mode="json"),
            "evidence_chain": evidence,
            "revisions": [r.model_dump(mode="json") for r in revisions],
            "actions": [a.model_dump(mode="json") for a in actions],
            "what_breaks_this": scenario.what_breaks_this,
        }

    def _ctx_agent(self, run_id: str, target_id: str) -> dict[str, Any]:
        agent_name = target_id  # target_id is agent name for agent targets
        actions = [
            a for a in self._db.get_actions(run_id)
            if a.agent_name == agent_name
        ]

        # Collect evidence referenced in actions
        evidence_ids: set[str] = set()
        for a in actions:
            for eid in a.evidence_ids:
                evidence_ids.add(str(eid))

        evidence = []
        for eid in evidence_ids:
            ev = self._db.get_evidence_by_id(eid)
            if ev:
                evidence.append(ev.model_dump(mode="json"))

        # Scenarios where this agent appears
        scenarios = self._db.get_scenarios(run_id)
        related_scenarios = [
            s.model_dump(mode="json") for s in scenarios
            if agent_name in s.lead_agents
            or agent_name in s.supporting_agents
            or agent_name in s.challenging_agents
        ]

        return {
            "target_type": "agent",
            "agent_name": agent_name,
            "actions": [a.model_dump(mode="json") for a in actions],
            "evidence": evidence,
            "related_scenarios": related_scenarios,
        }

    def _ctx_evidence(self, run_id: str, target_id: str) -> dict[str, Any]:
        ev = self._db.get_evidence_by_id(target_id)
        if ev is None:
            return {"error": "Evidence not found"}

        # Reverse: find scenario links for this evidence
        links = self._db.get_evidence_links_by_evidence(target_id)

        # Actions referencing this evidence
        actions = [
            a for a in self._db.get_actions(run_id)
            if UUID(target_id) in a.evidence_ids
        ]

        return {
            "target_type": "evidence",
            "evidence": ev.model_dump(mode="json"),
            "scenario_links": [
                {
                    "scenario_id": str(l.scenario_id),
                    "link_type": l.link_type.value,
                    "agent_name": l.agent_name,
                }
                for l in links
            ],
            "referencing_actions": [a.model_dump(mode="json") for a in actions],
        }

    def _ctx_node(self, run_id: str, target_id: str) -> dict[str, Any]:
        node = self._db.get_graph_node_by_id(target_id)
        if node is None:
            return {"error": "Graph node not found"}

        edges = self._db.get_graph_edges_by_node(target_id)

        # Find related evidence/scenarios by label matching
        evidence = self._db.get_evidence(run_id)
        related_evidence = [
            e.model_dump(mode="json") for e in evidence
            if node.label.lower() in e.title.lower()
            or node.label.lower() in e.summary.lower()
        ]

        scenarios = self._db.get_scenarios(run_id)
        related_scenarios = [
            s.model_dump(mode="json") for s in scenarios
            if node.label.lower() in s.title.lower()
            or node.label.lower() in s.summary.lower()
        ]

        return {
            "target_type": "node",
            "node": node.model_dump(mode="json"),
            "edges": [e.model_dump(mode="json") for e in edges],
            "related_evidence": related_evidence,
            "related_scenarios": related_scenarios,
        }

    def _ctx_edge(self, run_id: str, target_id: str) -> dict[str, Any]:
        # Find the edge; it might be identified by its ID
        edges = self._db.get_graph_edges(run_id)
        edge = None
        for e in edges:
            if str(e.id) == target_id:
                edge = e
                break

        if edge is None:
            return {"error": "Graph edge not found"}

        source = self._db.get_graph_node_by_id(str(edge.source_node_id))
        target = self._db.get_graph_node_by_id(str(edge.target_node_id))

        return {
            "target_type": "edge",
            "edge": edge.model_dump(mode="json"),
            "source_node": source.model_dump(mode="json") if source else None,
            "target_node": target.model_dump(mode="json") if target else None,
        }

    def _ctx_action(self, run_id: str, target_id: str) -> dict[str, Any]:
        actions = self._db.get_actions(run_id)
        action = None
        for a in actions:
            if str(a.id) == target_id:
                action = a
                break

        if action is None:
            return {"error": "Action not found"}

        # Collect referenced evidence
        evidence = []
        for eid in action.evidence_ids:
            ev = self._db.get_evidence_by_id(str(eid))
            if ev:
                evidence.append(ev.model_dump(mode="json"))

        # Target scenario
        target_scenario = None
        if action.target_scenario_id:
            sc = self._db.get_scenario_by_id(str(action.target_scenario_id))
            if sc:
                target_scenario = sc.model_dump(mode="json")

        return {
            "target_type": "action",
            "action": action.model_dump(mode="json"),
            "evidence": evidence,
            "target_scenario": target_scenario,
        }

    def _ctx_governance(self, run_id: str, target_id: str) -> dict[str, Any]:
        decision = self._db.get_governance_decision_by_id(target_id)
        if decision is None:
            return {"error": "Governance decision not found"}

        return {
            "target_type": "governance",
            "decision": decision.model_dump(mode="json"),
        }

    # ── Prompt construction ──────────────────────────────────────────

    def _build_prompt(
        self,
        target_type: str,
        context: dict[str, Any],
        history: list[InterrogationMessage],
        question: str,
        mode: AnswerMode,
    ) -> str:
        mode_instructions = {
            AnswerMode.CONCISE: "Answer in 2-3 paragraphs max.",
            AnswerMode.EVIDENCE_FIRST: (
                "Lead with evidence citations, then reasoning."
            ),
            AnswerMode.COUNTERARGUMENT_FIRST: (
                "Lead with strongest counterarguments, then assessment."
            ),
            AnswerMode.OPERATOR_SUMMARY: (
                "Bullet-point executive summary with confidence levels."
            ),
        }

        system = (
            f"You are the Pythia interrogation engine. Answer questions about this {target_type} "
            f"grounded in the provided artifacts. Cite specific evidence IDs and action sequence numbers. "
            f"If information is not in the provided context, say so."
        )

        context_str = json.dumps(context, indent=2, default=str)

        conv_lines = []
        # Include last 10 messages for conversation history
        for msg in history[:-1]:  # exclude the just-saved user message
            conv_lines.append(f"{msg.role.value.upper()}: {msg.content}")

        conv_text = "\n".join(conv_lines) if conv_lines else "(no prior messages)"

        return (
            f"SYSTEM: {system}\n\n"
            f"CONTEXT:\n{context_str}\n\n"
            f"CONVERSATION HISTORY:\n{conv_text}\n\n"
            f"ANSWER MODE: {mode.value} — {mode_instructions[mode]}\n\n"
            f"USER: {question}\n\n"
            f"ASSISTANT:"
        )
