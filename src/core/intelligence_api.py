"""
Pythia Intelligence API — Endpoints for attributors, forward signals,
narratives, user preferences, and on-demand spike analysis.

Mount this as a sub-router on the main FastAPI app.

Usage in api.py:
    from .intelligence_api import intelligence_router
    app.include_router(intelligence_router)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .database import PythiaDB
from .config import Config

logger = logging.getLogger(__name__)

intelligence_router = APIRouter(prefix="/api/v1", tags=["intelligence"])


# ------------------------------------------------------------------ #
# Lazy singletons
# ------------------------------------------------------------------ #

_attributor_store = None
_db = None


def _get_db() -> PythiaDB:
    global _db
    if _db is None:
        _db = PythiaDB(Config.DB_PATH)
    return _db


def _get_store():
    global _attributor_store
    if _attributor_store is None:
        from .attributor_engine import AttributorStore
        _attributor_store = AttributorStore(_get_db())
    return _attributor_store


# ------------------------------------------------------------------ #
# Response models
# ------------------------------------------------------------------ #

class AttributorResponse(BaseModel):
    id: str
    name: str
    category: Optional[str] = None
    causal_chain: Optional[str] = None
    confidence: Optional[str] = None
    confidence_score: Optional[float] = None
    status: Optional[str] = None
    spike_count: Optional[int] = None
    avg_magnitude: Optional[float] = None
    market_ids: Optional[List[str]] = None
    first_seen: Optional[str] = None
    last_active: Optional[str] = None


class ForwardSignalResponse(BaseModel):
    id: Optional[int] = None
    attributor_id: Optional[str] = None
    source_market_id: Optional[str] = None
    target_market_id: Optional[str] = None
    target_market_title: Optional[str] = None
    predicted_direction: Optional[str] = None
    predicted_magnitude: Optional[float] = None
    predicted_lag_hours: Optional[float] = None
    confidence_score: Optional[float] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None


class NarrativeResponse(BaseModel):
    id: str
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    strength: Optional[float] = None
    spike_count: Optional[int] = None
    attributor_ids: Optional[List[str]] = None
    market_ids: Optional[List[str]] = None
    status: Optional[str] = None


class SpikeAnalysisResponse(BaseModel):
    market_id: str
    market_title: Optional[str] = None
    spikes: Optional[List[Dict[str, Any]]] = None
    attributors: Optional[List[Dict[str, Any]]] = None
    forward_signals: Optional[List[Dict[str, Any]]] = None
    price_history: Optional[List[Dict[str, Any]]] = None


class UserPreferenceRequest(BaseModel):
    key: str
    value: str


# ------------------------------------------------------------------ #
# Attributor endpoints
# ------------------------------------------------------------------ #

@intelligence_router.get("/attributors", response_model=List[AttributorResponse])
def list_attributors(
    category: Optional[str] = None,
    status: Optional[str] = Query("active", description="Filter by status: active, fading, resolved"),
    limit: int = Query(50, le=200),
):
    """List attributors — persistent causal entities tracked across markets."""
    store = _get_store()
    if status == "active":
        attributors = store.get_active_attributors(category=category, limit=limit)
    else:
        # Query all statuses
        conn = store.db._get_conn()
        cols = [d[0] for d in conn.execute("PRAGMA table_info(attributors)").fetchall()]
        query = "SELECT * FROM attributors"
        params = []
        conditions = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY last_active DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        attributors = []
        for row in rows:
            d = dict(zip(cols, row))
            d["market_ids"] = json.loads(d.get("market_ids", "[]"))
            d["spike_ids"] = json.loads(d.get("spike_ids", "[]"))
            attributors.append(d)

    return attributors


@intelligence_router.get("/attributors/{attributor_id}", response_model=AttributorResponse)
def get_attributor(attributor_id: str):
    """Get a single attributor by ID."""
    store = _get_store()
    attr = store.get_attributor(attributor_id)
    if not attr:
        raise HTTPException(status_code=404, detail="Attributor not found")
    return attr


@intelligence_router.get("/markets/{market_id}/attributors", response_model=List[AttributorResponse])
def get_market_attributors(market_id: str):
    """Get all attributors linked to a specific market."""
    store = _get_store()
    return store.get_attributors_for_market(market_id)


# ------------------------------------------------------------------ #
# Forward signal endpoints
# ------------------------------------------------------------------ #

@intelligence_router.get("/signals/forward", response_model=List[ForwardSignalResponse])
def list_forward_signals(
    market_id: Optional[str] = None,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    status: str = Query("pending"),
):
    """List forward signals — predictive signals from attributor propagation."""
    store = _get_store()
    if status == "pending":
        return store.get_pending_signals(market_id=market_id, min_confidence=min_confidence)
    else:
        conn = store.db._get_conn()
        cols = [d[0] for d in conn.execute("PRAGMA table_info(forward_signals)").fetchall()]
        query = "SELECT * FROM forward_signals WHERE status = ? AND confidence_score >= ?"
        params = [status, min_confidence]
        if market_id:
            query += " AND target_market_id = ?"
            params.append(market_id)
        query += " ORDER BY created_at DESC LIMIT 100"
        rows = conn.execute(query, params).fetchall()
        return [dict(zip(cols, row)) for row in rows]


# ------------------------------------------------------------------ #
# Narrative endpoints
# ------------------------------------------------------------------ #

@intelligence_router.get("/narratives", response_model=List[NarrativeResponse])
def list_narratives(limit: int = Query(20, le=50)):
    """List active narratives — auto-clustered groups of related attributors."""
    store = _get_store()
    return store.get_active_narratives(limit=limit)


# ------------------------------------------------------------------ #
# On-demand spike analysis
# ------------------------------------------------------------------ #

@intelligence_router.get("/analyze/{market_id}", response_model=SpikeAnalysisResponse)
def analyze_market(
    market_id: str,
    hours: int = Query(720, description="Price history lookback in hours (default 30 days)"),
    spike_threshold: float = Query(0.02, description="Minimum spike magnitude"),
):
    """
    On-demand analysis for any market — fetches history, detects spikes,
    returns attributors and forward signals. For unmonitored markets.
    """
    db = _get_db()
    store = _get_store()

    # Get market info
    market = db.get_market(market_id)
    market_title = market.get("title", "") if market else ""

    # Get price history
    history_df = db.get_market_history(market_id, hours=hours)
    price_history = []
    if not history_df.empty:
        for _, row in history_df.iterrows():
            price_history.append({
                "timestamp": str(row.get("timestamp", "")),
                "yes_price": float(row.get("yes_price", 0)),
                "volume": float(row.get("volume", 0)) if "volume" in row else 0,
            })

    # Get spikes for this market
    try:
        spikes_df = db.get_spike_events(market_id=market_id, min_magnitude=spike_threshold, limit=100)
        spikes = []
        for _, row in spikes_df.iterrows():
            spikes.append({
                "id": int(row.get("id", 0)),
                "timestamp": str(row.get("timestamp", "")),
                "direction": row.get("direction", ""),
                "magnitude": float(row.get("magnitude", 0)),
                "price_before": float(row.get("price_before", 0)),
                "price_after": float(row.get("price_after", 0)),
                "asset_class": row.get("asset_class", ""),
            })
    except Exception:
        spikes = []

    # Get attributors for this market
    attributors = store.get_attributors_for_market(market_id)

    # Get forward signals targeting this market
    forward_signals = store.get_pending_signals(market_id=market_id)

    return {
        "market_id": market_id,
        "market_title": market_title,
        "spikes": spikes,
        "attributors": attributors,
        "forward_signals": forward_signals,
        "price_history": price_history,
    }


# ------------------------------------------------------------------ #
# User preference endpoints
# ------------------------------------------------------------------ #

@intelligence_router.get("/preferences")
def list_preferences(user_id: str = "default"):
    """Get all user preferences."""
    store = _get_store()
    conn = store.db._get_conn()
    rows = conn.execute(
        "SELECT preference_key, preference_value, updated_at FROM user_preferences WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    return [{"key": r[0], "value": r[1], "updated_at": r[2]} for r in rows]


@intelligence_router.post("/preferences")
def set_preference(pref: UserPreferenceRequest, user_id: str = "default"):
    """Set a user preference (e.g., confidence thresholds)."""
    store = _get_store()
    store.set_user_preference(pref.key, pref.value, user_id=user_id)
    return {"status": "ok", "key": pref.key, "value": pref.value}


@intelligence_router.post("/preferences/thresholds")
def set_thresholds(
    spike_detection: Optional[float] = None,
    attribution_confidence: Optional[float] = None,
    signal_confidence: Optional[float] = None,
    forward_signal_confidence: Optional[float] = None,
    user_id: str = "default",
):
    """Set confidence thresholds for different signal types."""
    store = _get_store()
    updated = {}
    if spike_detection is not None:
        store.set_user_preference("threshold_spike_detection", str(spike_detection), user_id)
        updated["spike_detection"] = spike_detection
    if attribution_confidence is not None:
        store.set_user_preference("threshold_attribution_confidence", str(attribution_confidence), user_id)
        updated["attribution_confidence"] = attribution_confidence
    if signal_confidence is not None:
        store.set_user_preference("threshold_signal_confidence", str(signal_confidence), user_id)
        updated["signal_confidence"] = signal_confidence
    if forward_signal_confidence is not None:
        store.set_user_preference("threshold_forward_signal_confidence", str(forward_signal_confidence), user_id)
        updated["forward_signal_confidence"] = forward_signal_confidence
    return {"status": "ok", "updated": updated}


# ------------------------------------------------------------------ #
# Watchlist signal integration
# ------------------------------------------------------------------ #

@intelligence_router.get("/watchlists/{watchlist_name}/signals")
def get_watchlist_signals(
    watchlist_name: str,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """Get all pending forward signals for markets in a watchlist."""
    from .watchlists import WatchlistManager
    wm = WatchlistManager()
    wl = wm.get(watchlist_name)
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    store = _get_store()
    all_signals = []
    for market_id in wl.contracts:
        signals = store.get_pending_signals(market_id=market_id, min_confidence=min_confidence)
        all_signals.extend(signals)

    all_signals.sort(key=lambda s: s.get("confidence_score", 0), reverse=True)
    return all_signals


# ------------------------------------------------------------------ #
# Feedback endpoint (for self-learning)
# ------------------------------------------------------------------ #

@intelligence_router.post("/feedback")
def submit_feedback(
    spike_id: Optional[int] = None,
    attributor_id: Optional[str] = None,
    signal_id: Optional[int] = None,
    feedback_type: str = Query(..., description="correct, wrong, partial"),
    details: str = "",
    user_id: str = "default",
):
    """
    Submit feedback on attributions or signals.
    Used by BACE self-learning loop.
    """
    from .feedback import log_feedback

    if spike_id:
        log_feedback(spike_id, feedback_type, details)

    # Also adjust attributor confidence based on feedback
    if attributor_id and feedback_type in ("wrong", "correct"):
        store = _get_store()
        attr = store.get_attributor(attributor_id)
        if attr:
            conn = store.db._get_conn()
            current_score = float(attr.get("confidence_score", 0.5))
            if feedback_type == "correct":
                new_score = min(1.0, current_score + 0.05)
            else:
                new_score = max(0.1, current_score - 0.1)
            conn.execute(
                "UPDATE attributors SET confidence_score = ? WHERE id = ?",
                (new_score, attributor_id)
            )
            conn.commit()

    return {"status": "ok", "feedback_type": feedback_type}
