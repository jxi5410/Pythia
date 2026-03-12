import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def ensure_attribution_tables(db: Any) -> None:
    conn = db._get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attribution_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spike_id INTEGER,
            engine TEXT NOT NULL,
            engine_version TEXT,
            mode TEXT,
            attribution_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attribution_runs_spike_engine
        ON attribution_runs(spike_id, engine)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attribution_comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spike_id INTEGER,
            primary_engine TEXT,
            shadow_engine TEXT,
            primary_confidence TEXT,
            shadow_confidence TEXT,
            primary_cause TEXT,
            shadow_cause TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attribution_comparisons_spike
        ON attribution_comparisons(spike_id)
        """
    )
    conn.commit()


def persist_attribution_run(db: Any, mode: str, result: Dict[str, Any]) -> None:
    try:
        ensure_attribution_tables(db)
        conn = db._get_conn()
        conn.execute(
            """
            INSERT INTO attribution_runs (spike_id, engine, engine_version, mode, attribution_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                result.get("spike_id"),
                result.get("engine", "unknown"),
                result.get("engine_version", ""),
                mode,
                json.dumps(result),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed persisting attribution run: %s", exc)


def persist_shadow_comparison(db: Any, spike_id: int, primary: Dict[str, Any], shadow: Dict[str, Any]) -> None:
    try:
        ensure_attribution_tables(db)
        conn = db._get_conn()
        conn.execute(
            """
            INSERT INTO attribution_comparisons (
                spike_id, primary_engine, shadow_engine,
                primary_confidence, shadow_confidence,
                primary_cause, shadow_cause, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                spike_id,
                primary.get("engine", "pce_v2"),
                shadow.get("engine", "rce_v1"),
                primary.get("attribution", {}).get("confidence", ""),
                shadow.get("attribution", {}).get("confidence", ""),
                primary.get("attribution", {}).get("most_likely_cause", ""),
                shadow.get("attribution", {}).get("most_likely_cause", ""),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed persisting shadow comparison: %s", exc)
