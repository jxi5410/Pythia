"""
Attributor Engine — Persistent causal entities extracted from PCE attributions.

An Attributor is a named cause that persists across multiple spikes and markets.
Examples: "Fed hawkish surprise", "China stimulus", "BTC ETF approval"

Attributors are the fundamental intelligence unit in Pythia. Spikes are the
detection mechanism; attributors are the product.

Lifecycle: detected → active → fading → resolved
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Attributor extraction from PCE output
# ------------------------------------------------------------------ #

def _normalize_cause(cause_text: str) -> str:
    """Normalize a cause description for dedup matching."""
    t = cause_text.lower().strip()
    t = re.sub(r'[^a-z0-9\s]', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t


def _compute_attributor_id(name: str, category: str) -> str:
    """Deterministic hash ID for an attributor."""
    key = f"{_normalize_cause(name)}|{category}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _word_overlap(a: str, b: str) -> float:
    """Jaccard similarity between two normalized strings."""
    words_a = set(_normalize_cause(a).split())
    words_b = set(_normalize_cause(b).split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def extract_attributor(pce_result: Dict) -> Optional[Dict]:
    """
    Extract an attributor entity from a PCE attribution result.

    Args:
        pce_result: Output from attribute_spike_v2() or attribute_spike_with_governance()

    Returns:
        Attributor dict or None if attribution is too weak
    """
    attribution = pce_result.get("attribution", {})
    context = pce_result.get("context", {})

    cause = attribution.get("most_likely_cause", "")
    if not cause or cause.lower() in ("unknown", "attribution failed", ""):
        return None

    confidence = attribution.get("confidence", "LOW")
    if confidence == "LOW":
        return None

    category = context.get("category", "general")
    causal_chain = attribution.get("causal_chain", "")
    macro_or_idio = attribution.get("macro_or_idiosyncratic", "UNKNOWN")
    duration = attribution.get("expected_duration", "UNKNOWN")

    spike = context.get("spike", {})

    return {
        "attributor_id": _compute_attributor_id(cause, category),
        "name": cause[:200],
        "category": category,
        "causal_chain": causal_chain[:500],
        "macro_or_idiosyncratic": macro_or_idio,
        "expected_duration": duration,
        "confidence": confidence,
        "first_seen": spike.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "last_active": spike.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "spike_ids": [pce_result.get("spike_id")],
        "market_ids": [spike.get("market_id", "")] if spike.get("market_id") else [],
        "status": "active",
        "spike_count": 1,
        "total_magnitude": float(spike.get("magnitude", 0)),
    }


# ------------------------------------------------------------------ #
# Attributor storage and deduplication
# ------------------------------------------------------------------ #

class AttributorStore:
    """
    Manages persistent attributor entities in the database.

    Handles deduplication: if a new spike has a similar cause to an existing
    attributor, it updates that attributor instead of creating a new one.
    """

    SIMILARITY_THRESHOLD = 0.5  # Jaccard similarity for dedup

    def __init__(self, db):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self):
        """Create attributor tables if they don't exist."""
        conn = self.db._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attributors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT,
                causal_chain TEXT,
                macro_or_idiosyncratic TEXT DEFAULT 'UNKNOWN',
                expected_duration TEXT DEFAULT 'UNKNOWN',
                confidence TEXT DEFAULT 'MEDIUM',
                confidence_score REAL DEFAULT 0.5,
                first_seen TIMESTAMP,
                last_active TIMESTAMP,
                status TEXT DEFAULT 'active',
                spike_count INTEGER DEFAULT 0,
                total_magnitude REAL DEFAULT 0.0,
                avg_magnitude REAL DEFAULT 0.0,
                market_ids TEXT DEFAULT '[]',
                spike_ids TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attributors_category
            ON attributors(category)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attributors_status
            ON attributors(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attributors_last_active
            ON attributors(last_active DESC)
        """)

        # Forward signals table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS forward_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attributor_id TEXT,
                source_market_id TEXT,
                target_market_id TEXT,
                target_market_title TEXT,
                signal_type TEXT DEFAULT 'CAUSAL_PROPAGATION',
                predicted_direction TEXT,
                predicted_magnitude REAL,
                predicted_lag_hours REAL,
                confidence_score REAL,
                causal_strength REAL,
                status TEXT DEFAULT 'pending',
                actual_direction TEXT,
                actual_magnitude REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                resolved_at TIMESTAMP,
                FOREIGN KEY (attributor_id) REFERENCES attributors(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_forward_signals_attributor
            ON forward_signals(attributor_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_forward_signals_target
            ON forward_signals(target_market_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_forward_signals_status
            ON forward_signals(status)
        """)

        # User preferences table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT 'default',
                preference_key TEXT NOT NULL,
                preference_value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, preference_key)
            )
        """)

        # Narratives table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS narratives (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                attributor_ids TEXT DEFAULT '[]',
                market_ids TEXT DEFAULT '[]',
                status TEXT DEFAULT 'active',
                strength REAL DEFAULT 0.0,
                spike_count INTEGER DEFAULT 0,
                first_seen TIMESTAMP,
                last_active TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_narratives_status
            ON narratives(status)
        """)

        # Watchlist signals junction
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watchlist_name TEXT,
                market_id TEXT,
                signal_id INTEGER,
                forward_signal_id INTEGER,
                seen BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

    # ------------------------------------------------------------------ #
    # Core CRUD
    # ------------------------------------------------------------------ #

    def upsert_attributor(self, attributor: Dict) -> str:
        """
        Insert or update an attributor. If a similar one exists (by name
        similarity within same category), merge into existing.

        Returns the attributor ID.
        """
        # Check for existing similar attributor
        existing = self._find_similar(attributor["name"], attributor["category"])

        if existing:
            return self._merge_into_existing(existing, attributor)
        else:
            return self._insert_new(attributor)

    def _find_similar(self, name: str, category: str) -> Optional[Dict]:
        """Find an existing attributor with similar name in same category."""
        conn = self.db._get_conn()
        rows = conn.execute(
            "SELECT * FROM attributors WHERE category = ? AND status IN ('active', 'fading')",
            (category,)
        ).fetchall()

        if not rows:
            return None

        cols = [d[0] for d in conn.execute("PRAGMA table_info(attributors)").fetchall()]
        best_match = None
        best_score = 0.0

        for row in rows:
            row_dict = dict(zip(cols, row))
            score = _word_overlap(name, row_dict["name"])
            if score > best_score and score >= self.SIMILARITY_THRESHOLD:
                best_score = score
                best_match = row_dict

        return best_match

    def _insert_new(self, attributor: Dict) -> str:
        """Insert a new attributor."""
        aid = attributor["attributor_id"]
        conn = self.db._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO attributors
            (id, name, category, causal_chain, macro_or_idiosyncratic,
             expected_duration, confidence, confidence_score, first_seen,
             last_active, status, spike_count, total_magnitude, avg_magnitude,
             market_ids, spike_ids)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            aid,
            attributor["name"],
            attributor["category"],
            attributor.get("causal_chain", ""),
            attributor.get("macro_or_idiosyncratic", "UNKNOWN"),
            attributor.get("expected_duration", "UNKNOWN"),
            attributor.get("confidence", "MEDIUM"),
            {"HIGH": 0.85, "MEDIUM": 0.6, "LOW": 0.3}.get(attributor.get("confidence", "MEDIUM"), 0.5),
            attributor.get("first_seen"),
            attributor.get("last_active"),
            "active",
            attributor.get("spike_count", 1),
            attributor.get("total_magnitude", 0),
            attributor.get("total_magnitude", 0),
            json.dumps(attributor.get("market_ids", [])),
            json.dumps(attributor.get("spike_ids", [])),
        ))
        conn.commit()

        logger.info("New attributor: %s [%s] (id=%s)", attributor["name"][:50], attributor["category"], aid)
        return aid

    def _merge_into_existing(self, existing: Dict, new_data: Dict) -> str:
        """Merge new spike data into an existing attributor."""
        aid = existing["id"]
        conn = self.db._get_conn()

        # Merge spike and market IDs
        old_spike_ids = json.loads(existing.get("spike_ids", "[]"))
        old_market_ids = json.loads(existing.get("market_ids", "[]"))
        new_spike_ids = new_data.get("spike_ids", [])
        new_market_ids = new_data.get("market_ids", [])

        merged_spikes = list(set(old_spike_ids + [s for s in new_spike_ids if s]))
        merged_markets = list(set(old_market_ids + [m for m in new_market_ids if m]))

        new_count = existing.get("spike_count", 0) + 1
        new_total_mag = float(existing.get("total_magnitude", 0)) + float(new_data.get("total_magnitude", 0))
        new_avg = new_total_mag / max(new_count, 1)

        conn.execute("""
            UPDATE attributors SET
                last_active = ?,
                spike_count = ?,
                total_magnitude = ?,
                avg_magnitude = ?,
                market_ids = ?,
                spike_ids = ?,
                status = 'active'
            WHERE id = ?
        """, (
            new_data.get("last_active", datetime.now(timezone.utc).isoformat()),
            new_count,
            new_total_mag,
            round(new_avg, 4),
            json.dumps(merged_markets),
            json.dumps(merged_spikes),
            aid,
        ))
        conn.commit()

        logger.info("Merged into attributor: %s (count=%d)", existing["name"][:50], new_count)
        return aid

    def get_attributor(self, attributor_id: str) -> Optional[Dict]:
        """Get a single attributor by ID."""
        conn = self.db._get_conn()
        cols = [d[0] for d in conn.execute("PRAGMA table_info(attributors)").fetchall()]
        row = conn.execute("SELECT * FROM attributors WHERE id = ?", (attributor_id,)).fetchone()
        if not row:
            return None
        d = dict(zip(cols, row))
        d["market_ids"] = json.loads(d.get("market_ids", "[]"))
        d["spike_ids"] = json.loads(d.get("spike_ids", "[]"))
        return d

    def get_active_attributors(self, category: str = None, limit: int = 50) -> List[Dict]:
        """Get active attributors, optionally filtered by category."""
        conn = self.db._get_conn()
        cols = [d[0] for d in conn.execute("PRAGMA table_info(attributors)").fetchall()]

        if category:
            rows = conn.execute(
                "SELECT * FROM attributors WHERE status = 'active' AND category = ? ORDER BY last_active DESC LIMIT ?",
                (category, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM attributors WHERE status = 'active' ORDER BY last_active DESC LIMIT ?",
                (limit,)
            ).fetchall()

        results = []
        for row in rows:
            d = dict(zip(cols, row))
            d["market_ids"] = json.loads(d.get("market_ids", "[]"))
            d["spike_ids"] = json.loads(d.get("spike_ids", "[]"))
            results.append(d)
        return results

    def get_attributors_for_market(self, market_id: str) -> List[Dict]:
        """Get all attributors linked to a specific market."""
        conn = self.db._get_conn()
        cols = [d[0] for d in conn.execute("PRAGMA table_info(attributors)").fetchall()]
        rows = conn.execute(
            "SELECT * FROM attributors WHERE market_ids LIKE ? ORDER BY last_active DESC",
            (f'%{market_id}%',)
        ).fetchall()

        results = []
        for row in rows:
            d = dict(zip(cols, row))
            d["market_ids"] = json.loads(d.get("market_ids", "[]"))
            d["spike_ids"] = json.loads(d.get("spike_ids", "[]"))
            if market_id in d["market_ids"]:
                results.append(d)
        return results

    def decay_attributors(self, inactive_hours: int = 48, fade_hours: int = 24):
        """
        Update attributor lifecycle statuses.
        active → fading (after fade_hours of inactivity)
        fading → resolved (after inactive_hours of inactivity)
        """
        conn = self.db._get_conn()
        now = datetime.now(timezone.utc)
        fade_cutoff = (now - timedelta(hours=fade_hours)).isoformat()
        resolve_cutoff = (now - timedelta(hours=inactive_hours)).isoformat()

        conn.execute(
            "UPDATE attributors SET status = 'fading' WHERE status = 'active' AND last_active < ?",
            (fade_cutoff,)
        )
        conn.execute(
            "UPDATE attributors SET status = 'resolved' WHERE status = 'fading' AND last_active < ?",
            (resolve_cutoff,)
        )
        conn.commit()

    # ------------------------------------------------------------------ #
    # Forward signals
    # ------------------------------------------------------------------ #

    def save_forward_signal(self, signal: Dict) -> int:
        """Save a forward signal prediction."""
        conn = self.db._get_conn()
        cursor = conn.execute("""
            INSERT INTO forward_signals
            (attributor_id, source_market_id, target_market_id, target_market_title,
             signal_type, predicted_direction, predicted_magnitude, predicted_lag_hours,
             confidence_score, causal_strength, status, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            signal.get("attributor_id"),
            signal.get("source_market_id"),
            signal.get("target_market_id"),
            signal.get("target_market_title", ""),
            signal.get("signal_type", "CAUSAL_PROPAGATION"),
            signal.get("predicted_direction"),
            signal.get("predicted_magnitude"),
            signal.get("predicted_lag_hours"),
            signal.get("confidence_score"),
            signal.get("causal_strength"),
            signal.get("expires_at"),
        ))
        conn.commit()
        return cursor.lastrowid

    def get_pending_signals(self, market_id: str = None, min_confidence: float = 0.0) -> List[Dict]:
        """Get pending forward signals, optionally filtered by market and confidence."""
        conn = self.db._get_conn()
        cols = [d[0] for d in conn.execute("PRAGMA table_info(forward_signals)").fetchall()]

        if market_id:
            rows = conn.execute(
                """SELECT * FROM forward_signals
                   WHERE status = 'pending' AND target_market_id = ? AND confidence_score >= ?
                   ORDER BY confidence_score DESC""",
                (market_id, min_confidence)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM forward_signals
                   WHERE status = 'pending' AND confidence_score >= ?
                   ORDER BY confidence_score DESC""",
                (min_confidence,)
            ).fetchall()

        return [dict(zip(cols, row)) for row in rows]

    def resolve_signal(self, signal_id: int, actual_direction: str, actual_magnitude: float):
        """Resolve a forward signal with actual outcome."""
        conn = self.db._get_conn()
        conn.execute(
            """UPDATE forward_signals SET
                status = 'resolved', actual_direction = ?, actual_magnitude = ?,
                resolved_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (actual_direction, actual_magnitude, signal_id)
        )
        conn.commit()

    # ------------------------------------------------------------------ #
    # User preferences
    # ------------------------------------------------------------------ #

    def set_user_preference(self, key: str, value: str, user_id: str = "default"):
        """Set a user preference."""
        conn = self.db._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO user_preferences (user_id, preference_key, preference_value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, key, value))
        conn.commit()

    def get_user_preference(self, key: str, default: str = None, user_id: str = "default") -> Optional[str]:
        """Get a user preference."""
        conn = self.db._get_conn()
        row = conn.execute(
            "SELECT preference_value FROM user_preferences WHERE user_id = ? AND preference_key = ?",
            (user_id, key)
        ).fetchone()
        return row[0] if row else default

    def get_user_confidence_threshold(self, threshold_type: str, user_id: str = "default") -> float:
        """Get user's confidence threshold for a specific signal type."""
        defaults = {
            "spike_detection": 0.02,
            "attribution_confidence": 0.5,
            "signal_confidence": 0.5,
            "forward_signal_confidence": 0.4,
        }
        val = self.get_user_preference(f"threshold_{threshold_type}", user_id=user_id)
        if val is not None:
            try:
                return float(val)
            except ValueError:
                pass
        return defaults.get(threshold_type, 0.5)

    # ------------------------------------------------------------------ #
    # Narratives
    # ------------------------------------------------------------------ #

    def upsert_narrative(self, narrative: Dict) -> str:
        """Insert or update a narrative."""
        nid = narrative["id"]
        conn = self.db._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO narratives
            (id, name, description, category, attributor_ids, market_ids,
             status, strength, spike_count, first_seen, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            nid,
            narrative["name"],
            narrative.get("description", ""),
            narrative.get("category", ""),
            json.dumps(narrative.get("attributor_ids", [])),
            json.dumps(narrative.get("market_ids", [])),
            narrative.get("status", "active"),
            narrative.get("strength", 0.0),
            narrative.get("spike_count", 0),
            narrative.get("first_seen"),
            narrative.get("last_active"),
        ))
        conn.commit()
        return nid

    def get_active_narratives(self, limit: int = 20) -> List[Dict]:
        """Get active narratives sorted by strength."""
        conn = self.db._get_conn()
        cols = [d[0] for d in conn.execute("PRAGMA table_info(narratives)").fetchall()]
        rows = conn.execute(
            "SELECT * FROM narratives WHERE status = 'active' ORDER BY strength DESC LIMIT ?",
            (limit,)
        ).fetchall()

        results = []
        for row in rows:
            d = dict(zip(cols, row))
            d["attributor_ids"] = json.loads(d.get("attributor_ids", "[]"))
            d["market_ids"] = json.loads(d.get("market_ids", "[]"))
            results.append(d)
        return results
