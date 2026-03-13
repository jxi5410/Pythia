"""
GraphManager — records graph mutations as deltas, reconstructs full graph
state from stored deltas, and saves point-in-time snapshots.

All graph mutations flow through record_delta() so that every change is
persisted as an ordered, replayable delta stream.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from src.core.models import (
    GraphDelta,
    GraphDeltaType,
    GraphEdge,
    GraphEntityType,
    GraphNode,
    GraphSnapshot,
)
from src.core.persistence import RunRepository


class GraphManager:
    """Manages graph state via an append-only delta log."""

    def __init__(self, db: RunRepository) -> None:
        self._db = db

    # ── Record a single delta ────────────────────────────────────────

    def record_delta(
        self,
        run_id: UUID | str,
        delta_type: str | GraphDeltaType,
        target_id: UUID | str,
        payload: dict[str, Any],
        sequence: int,
    ) -> GraphDelta:
        """Record a graph mutation delta and persist it.

        Also materialises the corresponding graph_node or graph_edge row
        for NODE_CREATED / EDGE_CREATED deltas so that the reconstructed
        graph can be queried directly from the node/edge tables.
        """
        run_uuid = UUID(str(run_id))
        target_uuid = UUID(str(target_id))

        if isinstance(delta_type, str):
            delta_type = GraphDeltaType(delta_type)

        delta = GraphDelta(
            run_id=run_uuid,
            delta_type=delta_type,
            target_id=target_uuid,
            sequence_number=sequence,
            payload=payload,
        )
        self._db.save_graph_delta(delta)

        # Materialise node/edge rows for creation deltas
        if delta_type == GraphDeltaType.NODE_CREATED:
            self._materialise_node(run_uuid, target_uuid, payload, sequence)
        elif delta_type == GraphDeltaType.EDGE_CREATED:
            self._materialise_edge(run_uuid, target_uuid, payload, sequence)

        return delta

    # ── Reconstruct full graph from stored nodes/edges ───────────────

    def get_run_graph(self, run_id: str) -> dict[str, Any]:
        """Return the full graph state: nodes and edges."""
        nodes = self._db.get_graph_nodes(run_id)
        edges = self._db.get_graph_edges(run_id)
        return {
            "nodes": [n.model_dump(mode="json") for n in nodes],
            "edges": [e.model_dump(mode="json") for e in edges],
        }

    # ── Get raw deltas ───────────────────────────────────────────────

    def get_deltas(
        self, run_id: str, after_sequence: int = 0,
    ) -> list[GraphDelta]:
        # Repository uses > semantics, so subtract 1 to include after_sequence
        return self._db.get_graph_deltas(run_id, after_sequence=after_sequence - 1)

    # ── Snapshot current graph state ─────────────────────────────────

    def save_snapshot(self, run_id: str) -> GraphSnapshot:
        """Save a point-in-time snapshot of the full graph."""
        run_uuid = UUID(run_id)
        nodes = self._db.get_graph_nodes(run_id)
        edges = self._db.get_graph_edges(run_id)
        deltas = self._db.get_graph_deltas(run_id)

        max_seq = max((d.sequence_number for d in deltas), default=0)

        snapshot = GraphSnapshot(
            run_id=run_uuid,
            node_count=len(nodes),
            edge_count=len(edges),
            delta_sequence_at=max_seq,
            nodes_json={"nodes": [n.model_dump(mode="json") for n in nodes]},
            edges_json={"edges": [e.model_dump(mode="json") for e in edges]},
        )
        self._db.save_graph_snapshot(snapshot)
        return snapshot

    # ── Batch recording (for ontology extraction) ────────────────────

    def record_ontology(
        self,
        run_id: UUID,
        ontology_data: dict[str, Any],
        sequence_base: int,
    ) -> tuple[list[GraphNode], list[GraphEdge], list[GraphDelta]]:
        """Record ontology entities and relationships as graph deltas.

        Returns the created (nodes, edges, deltas) for downstream use.
        This replaces direct calls to _ontology_to_graph_models + manual
        delta persistence in the orchestrator.
        """
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        deltas: list[GraphDelta] = []
        seq = sequence_base

        entity_id_map: dict[str, UUID] = {}

        for ent in ontology_data.get("entities", []):
            node_id = uuid4()
            entity_id_map[ent.get("id", ent.get("name", ""))] = node_id

            entity_type = GraphEntityType.PERSON
            raw_type = ent.get("entity_type", ent.get("type", ""))
            for gt in GraphEntityType:
                if gt.value == raw_type:
                    entity_type = gt
                    break

            payload = {
                "entity_type": entity_type.value,
                "label": ent.get("name", ""),
                "description": ent.get("description", ""),
                "search_terms": ent.get("search_terms", []),
                "relevance_score": ent.get("relevance_score", 0.0),
            }

            delta = self.record_delta(
                run_id, GraphDeltaType.NODE_CREATED, node_id, payload, seq,
            )
            deltas.append(delta)

            node = self._db.get_graph_node_by_id(str(node_id))
            if node:
                nodes.append(node)
            seq += 1

        for rel in ontology_data.get("relationships", []):
            src_id = entity_id_map.get(rel.get("source_id", ""))
            tgt_id = entity_id_map.get(rel.get("target_id", ""))
            if not src_id or not tgt_id:
                continue

            edge_id = uuid4()
            payload = {
                "source": str(src_id),
                "target": str(tgt_id),
                "type": rel.get("relationship_type", "related_to"),
                "weight": rel.get("strength", 0.5),
                "description": rel.get("description", ""),
                "temporal_order": rel.get("temporal_order"),
            }

            delta = self.record_delta(
                run_id, GraphDeltaType.EDGE_CREATED, edge_id, payload, seq,
            )
            deltas.append(delta)

            edge = self._db.get_graph_edges_by_node(str(src_id))
            for e in edge:
                if str(e.id) == str(edge_id):
                    edges.append(e)
                    break
            seq += 1

        return nodes, edges, deltas

    # ── Internal helpers ─────────────────────────────────────────────

    def _materialise_node(
        self,
        run_id: UUID,
        node_id: UUID,
        payload: dict[str, Any],
        sequence: int,
    ) -> None:
        entity_type = GraphEntityType.PERSON
        raw_type = payload.get("entity_type", "")
        for gt in GraphEntityType:
            if gt.value == raw_type:
                entity_type = gt
                break

        node = GraphNode(
            id=node_id,
            run_id=run_id,
            entity_type=entity_type,
            label=payload.get("label", ""),
            properties={
                k: v for k, v in payload.items()
                if k not in ("entity_type", "label")
            },
            created_at_sequence=sequence,
        )
        self._db.save_graph_node(node)

    def _materialise_edge(
        self,
        run_id: UUID,
        edge_id: UUID,
        payload: dict[str, Any],
        sequence: int,
    ) -> None:
        source_str = payload.get("source", "")
        target_str = payload.get("target", "")
        if not source_str or not target_str:
            return

        edge = GraphEdge(
            id=edge_id,
            run_id=run_id,
            source_node_id=UUID(source_str),
            target_node_id=UUID(target_str),
            relationship_type=payload.get("type", "related_to"),
            weight=payload.get("weight", 0.5),
            properties={
                k: v for k, v in payload.items()
                if k not in ("source", "target", "type", "weight")
            },
            created_at_sequence=sequence,
        )
        self._db.save_graph_edge(edge)
