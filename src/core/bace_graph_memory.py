"""
BACE Graph Memory — Persistent entity-relationship storage for causal attribution.

Stores entities, relationships, and attribution facts from each BACE run.
When the same market or related entities appear in future attributions,
the engine has prior context — which causes were previously identified,
which were debunked, and how entities relate to each other.

Storage: SQLite (same DB as Pythia's main database). No external services.

Tables:
  graph_entities      — entities extracted by bace_ontology
  graph_relationships — typed relationships between entities
  graph_facts         — temporal facts (valid_at / invalid_at for evolution tracking)
  graph_attributions  — summary of each BACE run's outcome for a market
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Schema ──────────────────────────────────────────────────────────

GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'unknown',
    description TEXT DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    occurrence_count INTEGER DEFAULT 1,
    metadata TEXT DEFAULT '{}',
    UNIQUE(name, entity_type)
);

CREATE TABLE IF NOT EXISTS graph_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    relationship_type TEXT NOT NULL DEFAULT 'related_to',
    description TEXT DEFAULT '',
    weight REAL DEFAULT 1.0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    occurrence_count INTEGER DEFAULT 1,
    metadata TEXT DEFAULT '{}',
    UNIQUE(source_entity, target_entity, relationship_type)
);

CREATE TABLE IF NOT EXISTS graph_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    valid_at TEXT,
    invalid_at TEXT,
    source_run_id TEXT,
    confidence REAL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS graph_attributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    market_id TEXT NOT NULL,
    market_title TEXT NOT NULL,
    spike_timestamp TEXT,
    spike_direction TEXT,
    spike_magnitude REAL,
    top_cause TEXT,
    top_confidence REAL,
    scenario_count INTEGER DEFAULT 1,
    scenarios TEXT DEFAULT '[]',
    agents_spawned INTEGER DEFAULT 0,
    elapsed_seconds REAL DEFAULT 0,
    decision TEXT DEFAULT 'UNKNOWN',
    created_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_graph_entities_name ON graph_entities(name);
CREATE INDEX IF NOT EXISTS idx_graph_relationships_source ON graph_relationships(source_entity);
CREATE INDEX IF NOT EXISTS idx_graph_relationships_target ON graph_relationships(target_entity);
CREATE INDEX IF NOT EXISTS idx_graph_facts_subject ON graph_facts(subject);
CREATE INDEX IF NOT EXISTS idx_graph_attributions_market ON graph_attributions(market_id);
"""


# ─── Graph Memory Class ──────────────────────────────────────────────

class BACEGraphMemory:
    """Persistent graph memory for BACE attribution runs."""

    def __init__(self, db_path: str = "pythia.db"):
        self.db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(GRAPH_SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.db_path)

    # ── Entity operations ────────────────────────────────────────────

    def upsert_entity(self, name: str, entity_type: str = "unknown",
                      description: str = "", metadata: Optional[Dict] = None):
        """Insert or update an entity. Increments occurrence_count on conflict."""
        now = datetime.now(timezone.utc).isoformat()
        meta = json.dumps(metadata or {})
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO graph_entities (name, entity_type, description, first_seen, last_seen, occurrence_count, metadata)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(name, entity_type) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    occurrence_count = occurrence_count + 1,
                    description = CASE WHEN length(excluded.description) > length(description) THEN excluded.description ELSE description END,
                    metadata = excluded.metadata
            """, (name, entity_type, description, now, now, meta))

    def upsert_entities_batch(self, entities: List[Dict]):
        """Batch upsert entities from ontology extraction."""
        for e in entities:
            self.upsert_entity(
                name=e.get("name", ""),
                entity_type=e.get("entity_type", e.get("type", "unknown")),
                description=e.get("description", e.get("summary", "")),
                metadata=e.get("metadata"),
            )

    def get_entity(self, name: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM graph_entities WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            if row:
                cols = [d[0] for d in conn.execute("SELECT * FROM graph_entities LIMIT 0").description]
                return dict(zip(cols, row))
        return None

    def search_entities(self, query: str, limit: int = 20) -> List[Dict]:
        """Search entities by name substring."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_entities WHERE name LIKE ? COLLATE NOCASE ORDER BY occurrence_count DESC LIMIT ?",
                (f"%{query}%", limit)
            ).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM graph_entities LIMIT 0").description]
            return [dict(zip(cols, r)) for r in rows]

    def get_all_entities(self, limit: int = 500) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_entities ORDER BY occurrence_count DESC LIMIT ?", (limit,)
            ).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM graph_entities LIMIT 0").description]
            return [dict(zip(cols, r)) for r in rows]

    # ── Relationship operations ──────────────────────────────────────

    def upsert_relationship(self, source: str, target: str,
                            rel_type: str = "related_to",
                            description: str = "", weight: float = 1.0,
                            metadata: Optional[Dict] = None):
        now = datetime.now(timezone.utc).isoformat()
        meta = json.dumps(metadata or {})
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO graph_relationships (source_entity, target_entity, relationship_type, description, weight, first_seen, last_seen, occurrence_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(source_entity, target_entity, relationship_type) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    occurrence_count = occurrence_count + 1,
                    weight = (weight + excluded.weight) / 2.0,
                    description = CASE WHEN length(excluded.description) > length(description) THEN excluded.description ELSE description END
            """, (source, target, rel_type, description, weight, now, now, meta))

    def upsert_relationships_batch(self, relationships: List[Dict]):
        for r in relationships:
            self.upsert_relationship(
                source=r.get("source", r.get("source_entity", "")),
                target=r.get("target", r.get("target_entity", "")),
                rel_type=r.get("type", r.get("relationship_type", "related_to")),
                description=r.get("description", ""),
                weight=r.get("weight", 1.0),
            )

    def get_relationships_for(self, entity_name: str) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM graph_relationships
                WHERE source_entity = ? COLLATE NOCASE OR target_entity = ? COLLATE NOCASE
                ORDER BY weight DESC
            """, (entity_name, entity_name)).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM graph_relationships LIMIT 0").description]
            return [dict(zip(cols, r)) for r in rows]

    # ── Fact operations ──────────────────────────────────────────────

    def add_fact(self, subject: str, predicate: str, obj: str,
                 valid_at: Optional[str] = None, confidence: float = 0.5,
                 source_run_id: str = "", metadata: Optional[Dict] = None):
        now = datetime.now(timezone.utc).isoformat()
        meta = json.dumps(metadata or {})
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO graph_facts (subject, predicate, object, valid_at, source_run_id, confidence, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (subject, predicate, obj, valid_at, source_run_id, confidence, now, meta))

    def get_facts_for(self, subject: str, active_only: bool = True) -> List[Dict]:
        with self._conn() as conn:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM graph_facts WHERE subject = ? COLLATE NOCASE AND invalid_at IS NULL ORDER BY confidence DESC",
                    (subject,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM graph_facts WHERE subject = ? COLLATE NOCASE ORDER BY created_at DESC",
                    (subject,)
                ).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM graph_facts LIMIT 0").description]
            return [dict(zip(cols, r)) for r in rows]

    def invalidate_fact(self, fact_id: int):
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute("UPDATE graph_facts SET invalid_at = ? WHERE id = ?", (now, fact_id))

    # ── Attribution log ──────────────────────────────────────────────

    def log_attribution(self, run_id: str, market_id: str, market_title: str,
                        spike_timestamp: str = "", spike_direction: str = "",
                        spike_magnitude: float = 0.0,
                        top_cause: str = "", top_confidence: float = 0.0,
                        scenario_count: int = 1, scenarios: Optional[List] = None,
                        agents_spawned: int = 0, elapsed_seconds: float = 0.0,
                        decision: str = "UNKNOWN", metadata: Optional[Dict] = None):
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO graph_attributions
                (run_id, market_id, market_title, spike_timestamp, spike_direction, spike_magnitude,
                 top_cause, top_confidence, scenario_count, scenarios, agents_spawned,
                 elapsed_seconds, decision, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, market_id, market_title, spike_timestamp, spike_direction,
                  spike_magnitude, top_cause, top_confidence, scenario_count,
                  json.dumps(scenarios or []), agents_spawned, elapsed_seconds,
                  decision, now, json.dumps(metadata or {})))

    def get_prior_attributions(self, market_id: str, limit: int = 5) -> List[Dict]:
        """Get prior BACE runs for this market — provides historical context."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM graph_attributions WHERE market_id = ?
                ORDER BY created_at DESC LIMIT ?
            """, (market_id, limit)).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM graph_attributions LIMIT 0").description]
            return [dict(zip(cols, r)) for r in rows]

    def get_related_attributions(self, entity_names: List[str], limit: int = 10) -> List[Dict]:
        """Find prior attributions that involved any of these entities."""
        if not entity_names:
            return []
        placeholders = ",".join(["?"] * len(entity_names))
        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT DISTINCT a.* FROM graph_attributions a
                JOIN graph_facts f ON f.source_run_id = a.run_id
                WHERE f.subject IN ({placeholders})
                ORDER BY a.created_at DESC LIMIT ?
            """, entity_names + [limit]).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM graph_attributions LIMIT 0").description]
            return [dict(zip(cols, r)) for r in rows]

    # ── Graph stats ──────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        with self._conn() as conn:
            entities = conn.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0]
            relationships = conn.execute("SELECT COUNT(*) FROM graph_relationships").fetchone()[0]
            facts = conn.execute("SELECT COUNT(*) FROM graph_facts WHERE invalid_at IS NULL").fetchone()[0]
            attributions = conn.execute("SELECT COUNT(*) FROM graph_attributions").fetchone()[0]
        return {
            "entities": entities,
            "relationships": relationships,
            "active_facts": facts,
            "attributions": attributions,
        }

    # ── Bulk ingest from BACE run ────────────────────────────────────

    def ingest_from_ontology(self, ontology):
        """Ingest entities and relationships from a bace_ontology CausalOntology object."""
        from dataclasses import asdict
        entities = [asdict(e) for e in getattr(ontology, "entities", [])]
        relationships = [asdict(r) for r in getattr(ontology, "relationships", [])]
        self.upsert_entities_batch(entities)
        self.upsert_relationships_batch(relationships)
        logger.info("Graph memory: ingested %d entities, %d relationships",
                     len(entities), len(relationships))

    def ingest_from_result(self, run_id: str, result: Dict):
        """Ingest facts from a completed BACE result."""
        market_title = result.get("context", {}).get("market_title", "")
        for h in result.get("agent_hypotheses", []):
            if h.get("status") == "survived" and h.get("confidence", 0) >= 0.3:
                self.add_fact(
                    subject=market_title or h.get("agent", ""),
                    predicate="caused_by",
                    obj=h.get("cause", h.get("hypothesis", ""))[:200],
                    confidence=h.get("confidence", 0.5),
                    source_run_id=run_id,
                )
        # Log the attribution summary
        spike = result.get("context", {}).get("spike", {})
        best = result.get("agent_hypotheses", [{}])[0] if result.get("agent_hypotheses") else {}
        scenarios = result.get("scenarios", [])
        self.log_attribution(
            run_id=run_id,
            market_id=result.get("context", {}).get("market_id", ""),
            market_title=market_title,
            spike_timestamp=spike.get("timestamp", ""),
            spike_direction=spike.get("direction", ""),
            spike_magnitude=float(spike.get("magnitude", 0)),
            top_cause=best.get("cause", best.get("hypothesis", ""))[:200],
            top_confidence=float(best.get("confidence", 0)),
            scenario_count=len(scenarios),
            scenarios=[{"label": s.get("label", ""), "confidence": s.get("confidence", 0)} for s in scenarios],
            agents_spawned=result.get("agents_spawned", 0),
            elapsed_seconds=result.get("elapsed_seconds", 0),
            decision=result.get("decision", "UNKNOWN"),
        )
        logger.info("Graph memory: logged attribution %s for %s", run_id, market_title[:40])
