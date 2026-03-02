"""
Pythia REST API — FastAPI application exposing Pythia intelligence endpoints.

Provides JSON endpoints for confluence events, signals, contract details,
regime state, track record, watchlists, patterns, and health status.

Run with:
    uvicorn pythia_live.api:app --host 0.0.0.0 --port 8000

Or programmatically:
    from pythia_live.api import app
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from .confluence import get_confluence_history
from .contract_detail import get_contract_detail, ContractDetail
from .database import PythiaDB
from .patterns import build_patterns, CausalPattern
from .regime import get_regime_state, RegimeState
from .track_record import get_track_record, TrackRecord, format_track_record_for_pdf
from .watchlists import WatchlistManager, Watchlist

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Configuration
# ------------------------------------------------------------------ #

DB_PATH = os.environ.get("PYTHIA_DB_PATH", "data/pythia_live.db")
WATCHLISTS_PATH = os.environ.get("PYTHIA_WATCHLISTS_PATH", "data/watchlists.json")

# API key authentication — set PYTHIA_API_KEY env var to enable
API_KEY = os.environ.get("PYTHIA_API_KEY", "")
CORS_ORIGINS = os.environ.get("PYTHIA_CORS_ORIGINS", "*").split(",")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _verify_api_key(api_key: Optional[str] = Security(_api_key_header)):
    """Verify API key if PYTHIA_API_KEY is configured. No-op if unset."""
    if not API_KEY:
        return  # Auth disabled — no key configured
    if not api_key or api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _get_db() -> PythiaDB:
    """Get a PythiaDB instance (created per request for thread safety)."""
    return PythiaDB(DB_PATH)


def _get_watchlists() -> WatchlistManager:
    """Get a WatchlistManager instance."""
    return WatchlistManager(WATCHLISTS_PATH)


# ------------------------------------------------------------------ #
# FastAPI app
# ------------------------------------------------------------------ #

app = FastAPI(
    title="Pythia API",
    version="0.1.0",
    description=(
        "Real-time prediction market intelligence engine. "
        "Cross-layer confluence detection, regime analysis, "
        "contract details, and historical track record."
    ),
    dependencies=[Depends(_verify_api_key)],
)

# CORS — configurable via PYTHIA_CORS_ORIGINS env var (default: "*" for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ #
# Pydantic models for request/response typing
# ------------------------------------------------------------------ #

class ConfluenceEventResponse(BaseModel):
    """A single confluence event."""
    id: Optional[int] = None
    event_category: str
    direction: str
    confluence_score: float
    layer_count: int
    layers: List[str] = []
    confidence: float = 0.0
    timestamp: str = ""
    suggested_assets: List[str] = []
    alert_text: str = ""


class SignalResponse(BaseModel):
    """A single signal record."""
    id: Optional[int] = None
    market_id: str = ""
    market_title: str = ""
    signal_type: str = ""
    severity: str = ""
    description: str = ""
    old_price: Optional[float] = None
    new_price: Optional[float] = None
    timestamp: str = ""


class WatchlistCreate(BaseModel):
    """Request body for creating a watchlist."""
    name: str = Field(..., min_length=1, max_length=100)
    contracts: List[str] = Field(default_factory=list)


class WatchlistResponse(BaseModel):
    """Watchlist data."""
    name: str
    contracts: List[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PatternResponse(BaseModel):
    """A causal pattern."""
    pattern_id: str
    market_category: str
    direction: str
    avg_magnitude: float
    sample_size: int
    typical_cause: str = ""
    confidence: float = 0.0
    avg_asset_reaction: float = 0.0
    avg_reaction_timeframe_hours: float = 0.0


class HealthResponse(BaseModel):
    """System health status."""
    status: str = "ok"
    version: str = "0.1.0"
    database_ok: bool = False
    markets_count: int = 0
    signals_last_hour: int = 0
    confluence_events_24h: int = 0
    last_signal_time: Optional[str] = None
    data_freshness_hours: Optional[float] = None
    timestamp: str = ""


# ------------------------------------------------------------------ #
# Endpoints
# ------------------------------------------------------------------ #

@app.get("/api/v1/confluence", response_model=List[ConfluenceEventResponse])
def get_confluence(
    min_score: float = Query(0.0, ge=0.0, le=1.0, description="Minimum confluence score"),
    hours: int = Query(24, ge=1, le=720, description="Lookback window in hours"),
) -> List[Dict[str, Any]]:
    """
    Get active confluence events.

    Returns events where multiple independent data layers agree on
    the same directional signal.
    """
    db = _get_db()
    events = get_confluence_history(db, hours=hours, min_score=min_score)

    results = []
    for evt in events:
        # Parse JSON fields
        layers = evt.get("layers", "[]")
        if isinstance(layers, str):
            try:
                layers = json.loads(layers)
            except (json.JSONDecodeError, TypeError):
                layers = []

        assets = evt.get("suggested_assets", "[]")
        if isinstance(assets, str):
            try:
                assets = json.loads(assets)
            except (json.JSONDecodeError, TypeError):
                assets = []

        results.append({
            "id": evt.get("id"),
            "event_category": evt.get("event_category", ""),
            "direction": evt.get("direction", ""),
            "confluence_score": evt.get("confluence_score", 0),
            "layer_count": evt.get("layer_count", 0),
            "layers": layers,
            "confidence": evt.get("confidence", 0),
            "timestamp": evt.get("timestamp", ""),
            "suggested_assets": assets,
            "alert_text": evt.get("alert_text", ""),
        })

    return results


@app.get("/api/v1/signals", response_model=List[SignalResponse])
def get_signals(
    watchlist: Optional[str] = Query(None, description="Watchlist name to filter by"),
    since: int = Query(1, ge=1, le=168, description="Hours to look back"),
) -> List[Dict[str, Any]]:
    """
    Get recent signals, optionally filtered by a watchlist.

    If a watchlist name is provided, only signals for markets in
    that watchlist are returned.
    """
    db = _get_db()

    try:
        df = db.get_recent_signals(hours=since)
    except Exception:
        df = None

    if df is None or df.empty:
        return []

    # If filtering by watchlist, get the contract list
    watchlist_contracts: Optional[List[str]] = None
    if watchlist:
        wm = _get_watchlists()
        wl = wm.get(watchlist)
        if wl:
            watchlist_contracts = wl.contracts

    results = []
    for _, row in df.iterrows():
        market_id = str(row.get("market_id", ""))

        # Filter by watchlist if specified
        if watchlist_contracts is not None:
            if not any(c in market_id or market_id in c for c in watchlist_contracts):
                continue

        results.append({
            "id": int(row.get("id", 0)) if row.get("id") is not None else None,
            "market_id": market_id,
            "market_title": str(row.get("title", "")),
            "signal_type": str(row.get("signal_type", "")),
            "severity": str(row.get("severity", "")),
            "description": str(row.get("description", "")),
            "old_price": _safe_float(row.get("old_price")),
            "new_price": _safe_float(row.get("new_price")),
            "timestamp": str(row.get("timestamp", "")),
        })

    return results


@app.get("/api/v1/contract/{slug}")
def get_contract(slug: str) -> Dict[str, Any]:
    """
    Get a full detail view for a prediction market contract.

    Assembles cross-platform prices, confluence layer status,
    causal attribution, historical patterns, and suggested assets.
    """
    db = _get_db()
    detail = get_contract_detail(slug, db=db)

    # Serialize dataclass to dict
    return _serialize_contract_detail(detail)


@app.get("/api/v1/regime")
def get_regime() -> Dict[str, Any]:
    """
    Get the current market regime state.

    Classifies the macro environment based on which event categories
    are simultaneously active and their intensity.
    """
    db = _get_db()
    state = get_regime_state(db=db)

    return {
        "current_regime": state.current_regime,
        "regime_description": state.regime_description,
        "category_activity": state.category_activity,
        "active_clusters": state.active_clusters,
        "total_signal_count": state.total_signal_count,
        "timestamp": state.timestamp.isoformat() if state.timestamp else "",
        "historical_comparisons": [
            {
                "regime_type": hc.regime_type,
                "occurred_at": hc.occurred_at.isoformat() if hc.occurred_at else None,
                "categories_active": hc.categories_active,
                "outcomes": hc.outcomes,
                "notes": hc.notes,
            }
            for hc in state.historical_comparisons
        ],
    }


@app.get("/api/v1/track-record")
def get_track_record_endpoint(
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
) -> Dict[str, Any]:
    """
    Get historical track record and performance metrics.

    Shows hit rates, false positive rates, lead times,
    and per-layer contribution analysis.
    """
    db = _get_db()
    record = get_track_record(days=days, db=db)

    return format_track_record_for_pdf(record)


@app.get("/api/v1/watchlists", response_model=List[WatchlistResponse])
def list_watchlists() -> List[Dict[str, Any]]:
    """List all watchlists."""
    wm = _get_watchlists()
    return [
        {
            "name": wl.name,
            "contracts": wl.contracts,
            "created_at": wl.created_at.isoformat() if wl.created_at else None,
            "updated_at": wl.updated_at.isoformat() if wl.updated_at else None,
        }
        for wl in wm.list_watchlists()
    ]


@app.post("/api/v1/watchlists", response_model=WatchlistResponse, status_code=201)
def create_watchlist(body: WatchlistCreate) -> Dict[str, Any]:
    """
    Create a new watchlist.

    If a watchlist with the same name exists, it will be overwritten.
    """
    wm = _get_watchlists()
    wl = wm.create(name=body.name, contracts=body.contracts)

    return {
        "name": wl.name,
        "contracts": wl.contracts,
        "created_at": wl.created_at.isoformat() if wl.created_at else None,
        "updated_at": wl.updated_at.isoformat() if wl.updated_at else None,
    }


@app.get("/api/v1/patterns", response_model=List[PatternResponse])
def get_patterns(
    category: Optional[str] = Query(None, description="Filter by market category"),
    min_layers: int = Query(0, ge=0, description="Minimum sample size"),
) -> List[Dict[str, Any]]:
    """
    Get historical causal patterns.

    Patterns are recurring spike behaviours grouped by category
    and direction, with confidence scores and typical causes.
    """
    db = _get_db()
    patterns = build_patterns(db)

    # Filter
    if category:
        patterns = [p for p in patterns if p.market_category == category]
    if min_layers > 0:
        patterns = [p for p in patterns if p.sample_size >= min_layers]

    return [
        {
            "pattern_id": p.pattern_id,
            "market_category": p.market_category,
            "direction": p.direction,
            "avg_magnitude": round(p.avg_magnitude, 4),
            "sample_size": p.sample_size,
            "typical_cause": p.typical_cause,
            "confidence": round(p.confidence, 3),
            "avg_asset_reaction": round(p.avg_asset_reaction, 4),
            "avg_reaction_timeframe_hours": round(p.avg_reaction_timeframe_hours, 1),
        }
        for p in patterns
    ]


@app.get("/api/v1/health", response_model=HealthResponse)
def health_check() -> Dict[str, Any]:
    """
    System health status and data freshness.

    Checks database connectivity, market count, recent signals,
    and data freshness.
    """
    result: Dict[str, Any] = {
        "status": "ok",
        "version": "0.1.0",
        "database_ok": False,
        "markets_count": 0,
        "signals_last_hour": 0,
        "confluence_events_24h": 0,
        "last_signal_time": None,
        "data_freshness_hours": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        db = _get_db()

        with sqlite3.connect(db.db_path) as conn:
            result["database_ok"] = True

            # Market count
            row = conn.execute("SELECT COUNT(*) FROM markets").fetchone()
            result["markets_count"] = row[0] if row else 0

            # Signals last hour
            row = conn.execute(
                "SELECT COUNT(*) FROM signals "
                "WHERE timestamp > datetime('now', '-1 hour')"
            ).fetchone()
            result["signals_last_hour"] = row[0] if row else 0

            # Confluence events 24h
            row = conn.execute(
                "SELECT COUNT(*) FROM confluence_events "
                "WHERE timestamp > datetime('now', '-24 hours')"
            ).fetchone()
            result["confluence_events_24h"] = row[0] if row else 0

            # Last signal time and freshness
            row = conn.execute(
                "SELECT MAX(timestamp) FROM signals"
            ).fetchone()
            if row and row[0]:
                result["last_signal_time"] = row[0]
                try:
                    last_ts = datetime.fromisoformat(str(row[0]))
                    now = datetime.now(timezone.utc)
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=timezone.utc)
                    freshness = (now - last_ts).total_seconds() / 3600.0
                    result["data_freshness_hours"] = round(freshness, 1)
                except (ValueError, TypeError):
                    pass

    except Exception as e:
        result["status"] = "degraded"
        result["database_ok"] = False
        logger.warning("Health check found issues: %s", e)

    return result


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _safe_float(val: Any) -> Optional[float]:
    """Convert a value to float, returning None for NaN/None/invalid."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None


def _serialize_contract_detail(detail: ContractDetail) -> Dict[str, Any]:
    """Convert a ContractDetail dataclass to a JSON-serialisable dict."""
    return {
        "slug": detail.slug,
        "title": detail.title,
        "platform": detail.platform,
        "current_price": detail.current_price,
        "delta_24h": detail.delta_24h,
        "volume_24h": detail.volume_24h,
        "category": detail.category,
        "cross_platform_prices": detail.cross_platform_prices,
        "confluence": {
            "score": detail.confluence_score,
            "active_layer_count": detail.active_layer_count,
            "layers": [
                {
                    "layer": ls.layer,
                    "active": ls.active,
                    "direction": ls.direction,
                    "confidence": ls.confidence,
                    "description": ls.description,
                    "last_signal_time": (
                        ls.last_signal_time.isoformat()
                        if ls.last_signal_time else None
                    ),
                }
                for ls in detail.confluence_layers
            ],
        },
        "causal_attribution": (
            {
                "most_likely_cause": detail.causal_attribution.most_likely_cause,
                "causal_chain": detail.causal_attribution.causal_chain,
                "confidence": detail.causal_attribution.confidence,
                "macro_or_idiosyncratic": detail.causal_attribution.macro_or_idiosyncratic,
                "expected_duration": detail.causal_attribution.expected_duration,
                "trading_implication": detail.causal_attribution.trading_implication,
                "alternative_explanations": detail.causal_attribution.alternative_explanations,
                "timestamp": (
                    detail.causal_attribution.timestamp.isoformat()
                    if detail.causal_attribution.timestamp else None
                ),
            }
            if detail.causal_attribution else None
        ),
        "historical_patterns": [
            {
                "pattern_id": pm.pattern_id,
                "category": pm.market_category,
                "direction": pm.direction,
                "spike_count": pm.spike_count,
                "hit_rate": pm.hit_rate,
                "avg_magnitude": pm.avg_magnitude,
                "avg_reaction": pm.avg_reaction,
                "time_to_resolution_hours": pm.time_to_resolution_hours,
            }
            for pm in detail.historical_patterns
        ],
        "suggested_assets": detail.suggested_assets,
        "asset_class": detail.asset_class,
        "asset_rationale": detail.asset_rationale,
        "correlated_markets": detail.correlated_markets,
        "last_updated": (
            detail.last_updated.isoformat() if detail.last_updated else None
        ),
    }
