"""
Regime Engine — Detects the current market regime from confluence activity.

Classifies the macro environment by analysing which event categories are
simultaneously active, how intense the activity is, and what historical
precedents exist for similar clusters.

Predefined regime types:
  - risk_off: broad flight to safety across multiple categories
  - policy_uncertainty: fed_rate + recession + tariffs active together
  - geopolitical_shock: geopolitical + defense + energy spike simultaneously
  - crypto_event: crypto_regulation or crypto on-chain signals dominating
  - calm: low activity across the board
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from .confluence import (
    EVENT_CATEGORIES,
    VALID_LAYERS,
    get_confluence_history,
)
from .database import PythiaDB

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Regime taxonomy
# ------------------------------------------------------------------ #

REGIME_CLUSTERS: Dict[str, Dict] = {
    "policy_uncertainty": {
        "categories": {"fed_rate", "recession", "tariffs"},
        "min_active": 2,
        "description": "Monetary/fiscal policy uncertainty driving multiple asset repricing",
    },
    "geopolitical_shock": {
        "categories": {"geopolitical", "defense", "energy"},
        "min_active": 2,
        "description": "Geopolitical escalation with energy and defense implications",
    },
    "risk_off": {
        "categories": {"recession", "geopolitical", "government_shutdown"},
        "min_active": 2,
        "description": "Broad risk-off sentiment — flight to safety assets",
    },
    "crypto_event": {
        "categories": {"crypto_regulation"},
        "min_active": 1,
        "description": "Crypto-specific regulatory or on-chain event driving volatility",
    },
    "china_macro_shock": {
        "categories": {"china_macro", "tariffs"},
        "min_active": 2,
        "description": "China macro stress spilling into global trade concerns",
    },
    "tech_regulatory": {
        "categories": {"tech_regulation", "earnings_macro"},
        "min_active": 2,
        "description": "Big tech under regulatory pressure alongside earnings stress",
    },
    "calm": {
        "categories": set(),  # Assigned when no clusters match
        "min_active": 0,
        "description": "Low activity across all categories — normal market conditions",
    },
}

# Historical regime outcomes — what typically happens to key assets
# when each regime cluster has been detected in the past.
# Values are approximate median moves over the subsequent 48 hours.
HISTORICAL_REGIME_OUTCOMES: Dict[str, Dict] = {
    "policy_uncertainty": {
        "SPX": {"median_move_pct": -1.2, "direction": "down", "confidence": "medium"},
        "TLT": {"median_move_pct": +1.5, "direction": "up", "confidence": "medium"},
        "VIX": {"median_move_pct": +8.0, "direction": "up", "confidence": "high"},
        "DXY": {"median_move_pct": +0.3, "direction": "up", "confidence": "low"},
    },
    "geopolitical_shock": {
        "SPX": {"median_move_pct": -2.0, "direction": "down", "confidence": "high"},
        "GLD": {"median_move_pct": +1.8, "direction": "up", "confidence": "high"},
        "USO": {"median_move_pct": +3.5, "direction": "up", "confidence": "medium"},
        "VIX": {"median_move_pct": +15.0, "direction": "up", "confidence": "high"},
    },
    "risk_off": {
        "SPX": {"median_move_pct": -1.8, "direction": "down", "confidence": "high"},
        "TLT": {"median_move_pct": +2.0, "direction": "up", "confidence": "high"},
        "HYG": {"median_move_pct": -0.8, "direction": "down", "confidence": "medium"},
        "VIX": {"median_move_pct": +12.0, "direction": "up", "confidence": "high"},
    },
    "crypto_event": {
        "BTC": {"median_move_pct": -5.0, "direction": "variable", "confidence": "medium"},
        "ETH": {"median_move_pct": -6.0, "direction": "variable", "confidence": "medium"},
        "COIN": {"median_move_pct": -4.0, "direction": "variable", "confidence": "low"},
    },
    "china_macro_shock": {
        "FXI": {"median_move_pct": -3.0, "direction": "down", "confidence": "high"},
        "EEM": {"median_move_pct": -2.0, "direction": "down", "confidence": "medium"},
        "SPX": {"median_move_pct": -0.8, "direction": "down", "confidence": "low"},
        "USDCNY": {"median_move_pct": +0.5, "direction": "up", "confidence": "medium"},
    },
    "tech_regulatory": {
        "QQQ": {"median_move_pct": -1.5, "direction": "down", "confidence": "medium"},
        "META": {"median_move_pct": -2.5, "direction": "down", "confidence": "medium"},
        "GOOGL": {"median_move_pct": -2.0, "direction": "down", "confidence": "medium"},
    },
    "calm": {
        "SPX": {"median_move_pct": +0.2, "direction": "flat", "confidence": "low"},
        "VIX": {"median_move_pct": -2.0, "direction": "down", "confidence": "low"},
    },
}


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #

@dataclass
class HistoricalComparison:
    """A past regime instance with its outcomes."""
    regime_type: str
    occurred_at: Optional[datetime] = None
    categories_active: List[str] = field(default_factory=list)
    outcomes: Dict[str, Dict] = field(default_factory=dict)
    notes: str = ""


@dataclass
class RegimeState:
    """
    Current market regime snapshot.

    Attributes:
        current_regime: Classified regime type (e.g. "policy_uncertainty").
        regime_description: Human-readable explanation.
        category_activity: Activity level (0.0–1.0) per event category.
        active_clusters: List of co-moving category clusters currently detected.
        historical_comparisons: Past similar regimes with their outcomes.
        total_signal_count: Total active signals across all categories.
        timestamp: When this regime state was computed.
    """
    current_regime: str
    regime_description: str = ""
    category_activity: Dict[str, float] = field(default_factory=dict)
    active_clusters: List[List[str]] = field(default_factory=list)
    historical_comparisons: List[HistoricalComparison] = field(default_factory=list)
    total_signal_count: int = 0
    timestamp: Optional[datetime] = None


# ------------------------------------------------------------------ #
# Activity calculation
# ------------------------------------------------------------------ #

def _compute_category_activity(
    db: PythiaDB, hours: int = 24
) -> Tuple[Dict[str, float], int]:
    """
    Calculate activity level (0.0–1.0) per event category based on
    recent confluence events and signals.

    Activity level considers:
      - Number of confluence events in the window
      - Average confluence score
      - Number of distinct layers that fired

    Returns:
        (category_activity dict, total_signal_count)
    """
    events = get_confluence_history(db, hours=hours, min_score=0.0)

    # Group by category
    category_stats: Dict[str, Dict] = {}
    total_signals = 0

    for evt in events:
        cat = evt.get("event_category", "unknown")
        if cat not in category_stats:
            category_stats[cat] = {
                "count": 0,
                "total_score": 0.0,
                "max_layers": 0,
            }
        category_stats[cat]["count"] += 1
        category_stats[cat]["total_score"] += evt.get("confluence_score", 0)
        category_stats[cat]["max_layers"] = max(
            category_stats[cat]["max_layers"],
            evt.get("layer_count", 0),
        )
        total_signals += evt.get("layer_count", 0)

    # Also count raw signals from the signals table
    try:
        with sqlite3.connect(db.db_path) as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM signals "
                "WHERE timestamp > datetime('now', ?)",
                (f"-{hours} hours",),
            ).fetchone()
            if rows:
                total_signals += rows[0]
    except Exception:
        pass

    # Normalize to 0-1 activity level
    # Heuristic: 5+ events = activity 1.0, 1 event = 0.2, 0 = 0.0
    activity: Dict[str, float] = {}
    for cat in EVENT_CATEGORIES:
        stats = category_stats.get(cat)
        if not stats or stats["count"] == 0:
            activity[cat] = 0.0
            continue

        count_factor = min(1.0, stats["count"] / 5.0)
        avg_score = stats["total_score"] / stats["count"]
        layer_factor = min(1.0, stats["max_layers"] / 5.0)

        # Weighted combination
        level = 0.4 * count_factor + 0.35 * avg_score + 0.25 * layer_factor
        activity[cat] = round(min(1.0, max(0.0, level)), 3)

    return activity, total_signals


# ------------------------------------------------------------------ #
# Cluster detection
# ------------------------------------------------------------------ #

def _detect_active_clusters(
    activity: Dict[str, float],
    threshold: float = 0.15,
) -> Tuple[List[List[str]], str]:
    """
    Detect which predefined clusters are currently active.

    A cluster is active when enough of its constituent categories
    exceed the activity threshold.

    Returns:
        (list_of_active_clusters, best_regime_type)
    """
    active_cats: Set[str] = {
        cat for cat, level in activity.items() if level >= threshold
    }

    matched_clusters: List[Tuple[str, List[str], float]] = []

    for regime_type, cluster_def in REGIME_CLUSTERS.items():
        if regime_type == "calm":
            continue

        required_cats: Set[str] = cluster_def["categories"]
        min_active: int = cluster_def["min_active"]
        overlap = required_cats & active_cats

        if len(overlap) >= min_active:
            # Score by how many categories are active and their combined level
            combined_level = sum(activity.get(c, 0) for c in overlap)
            matched_clusters.append((
                regime_type,
                sorted(overlap),
                combined_level,
            ))

    if not matched_clusters:
        return [], "calm"

    # Sort by combined activity level
    matched_clusters.sort(key=lambda x: x[2], reverse=True)

    clusters = [mc[1] for mc in matched_clusters]
    best_regime = matched_clusters[0][0]

    return clusters, best_regime


# ------------------------------------------------------------------ #
# Historical comparison
# ------------------------------------------------------------------ #

def _lookup_historical_comparisons(
    regime_type: str,
    db: PythiaDB,
) -> List[HistoricalComparison]:
    """
    Look up historical instances of the same regime type.

    Checks the confluence_events table for past clusters matching
    the current regime pattern, and retrieves what happened next
    from the predefined outcome data.
    """
    comparisons: List[HistoricalComparison] = []

    # Use predefined historical outcomes
    outcomes = HISTORICAL_REGIME_OUTCOMES.get(regime_type, {})
    if outcomes:
        comparisons.append(HistoricalComparison(
            regime_type=regime_type,
            occurred_at=None,  # Aggregate historical data
            categories_active=sorted(
                REGIME_CLUSTERS.get(regime_type, {}).get("categories", set())
            ),
            outcomes=outcomes,
            notes=(
                REGIME_CLUSTERS.get(regime_type, {}).get("description", "")
                + " — based on historical median moves within 48h."
            ),
        ))

    # Also check DB for past confluence events matching this regime
    try:
        events = get_confluence_history(db, hours=720, min_score=0.3)  # 30 days

        regime_cats = REGIME_CLUSTERS.get(regime_type, {}).get("categories", set())
        if not regime_cats:
            return comparisons

        # Find past windows where these categories were simultaneously active
        # Group events by 24h windows
        windows: Dict[str, List[Dict]] = {}
        for evt in events:
            ts = evt.get("timestamp", "")
            if not ts:
                continue
            day_key = str(ts)[:10]  # YYYY-MM-DD
            windows.setdefault(day_key, []).append(evt)

        for day_key, day_events in sorted(windows.items(), reverse=True)[:5]:
            day_cats = {e.get("event_category") for e in day_events}
            overlap = regime_cats & day_cats
            if len(overlap) >= REGIME_CLUSTERS.get(regime_type, {}).get("min_active", 2):
                avg_score = sum(
                    e.get("confluence_score", 0) for e in day_events
                ) / max(len(day_events), 1)

                comparisons.append(HistoricalComparison(
                    regime_type=regime_type,
                    occurred_at=datetime.fromisoformat(day_key) if day_key else None,
                    categories_active=sorted(overlap),
                    outcomes=outcomes,
                    notes=f"Detected on {day_key}: {len(day_events)} events, avg score {avg_score:.2f}",
                ))

    except Exception as e:
        logger.debug("Historical comparison DB lookup failed: %s", e)

    return comparisons[:5]  # Cap at 5 comparisons


# ------------------------------------------------------------------ #
# Main API
# ------------------------------------------------------------------ #

def get_regime_state(
    db: Optional[PythiaDB] = None,
    db_path: str = "data/pythia_live.db",
    lookback_hours: int = 24,
) -> RegimeState:
    """
    Compute the current market regime state.

    Analyses recent confluence events to determine:
    1. Activity level per event category (0.0–1.0)
    2. Which category clusters are co-moving
    3. The best-matching regime classification
    4. Historical comparisons for the matched regime

    Args:
        db: Optional pre-initialised PythiaDB instance.
        db_path: Path to the database file (used if ``db`` is None).
        lookback_hours: How far back to look for signals.

    Returns:
        RegimeState with full classification and historical context.
    """
    if db is None:
        db = PythiaDB(db_path)

    now = datetime.now(timezone.utc)

    # --- 1. Category activity ---
    activity, total_signals = _compute_category_activity(db, hours=lookback_hours)

    # --- 2. Cluster detection ---
    clusters, regime_type = _detect_active_clusters(activity)

    # --- 3. Regime description ---
    regime_desc = REGIME_CLUSTERS.get(regime_type, {}).get(
        "description", "Unknown regime state"
    )

    # --- 4. Historical comparisons ---
    comparisons = _lookup_historical_comparisons(regime_type, db)

    return RegimeState(
        current_regime=regime_type,
        regime_description=regime_desc,
        category_activity=activity,
        active_clusters=clusters,
        historical_comparisons=comparisons,
        total_signal_count=total_signals,
        timestamp=now,
    )


# ------------------------------------------------------------------ #
# Formatting helpers (for display / API consumption)
# ------------------------------------------------------------------ #

def format_regime_heatmap(state: RegimeState) -> str:
    """
    Format the regime state as a text-based heatmap.

    Uses block characters to show activity level per category:
      ████████░░ = 0.8 activity
      ██░░░░░░░░ = 0.2 activity

    Returns:
        Multi-line string suitable for Telegram or terminal.
    """
    lines = [
        f"🌍 REGIME: {state.current_regime.upper().replace('_', ' ')}",
        f"   {state.regime_description}",
        "",
        "Category Activity (24h):",
    ]

    # Sort categories by activity level descending
    sorted_cats = sorted(
        state.category_activity.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    for cat, level in sorted_cats:
        bar_len = 10
        filled = round(level * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        # Activity label
        if level >= 0.7:
            label = "🔴"
        elif level >= 0.4:
            label = "🟡"
        elif level > 0:
            label = "🟢"
        else:
            label = "⚪"

        cat_display = cat.replace("_", " ").title()
        lines.append(f"  {label} {cat_display:20s} {bar} {level:.0%}")

    if state.active_clusters:
        lines.append("")
        lines.append("Active Clusters:")
        for cluster in state.active_clusters:
            cluster_str = " + ".join(c.replace("_", " ") for c in cluster)
            lines.append(f"  ⚡ {cluster_str}")

    if state.historical_comparisons:
        lines.append("")
        lines.append("Historical Precedent (48h outlook):")
        comp = state.historical_comparisons[0]
        for asset, outcome in comp.outcomes.items():
            sign = "+" if outcome["median_move_pct"] > 0 else ""
            conf = outcome.get("confidence", "?")
            lines.append(
                f"  • {asset}: {sign}{outcome['median_move_pct']:.1f}% "
                f"({conf} confidence)"
            )

    lines.append(f"\nTotal signals: {state.total_signal_count}")

    return "\n".join(lines)
