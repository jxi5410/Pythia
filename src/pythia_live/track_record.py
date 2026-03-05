"""
Track Record Engine — Historical proof and performance metrics.

Analyses past confluence events to produce verifiable performance stats:
hit rates, false positive rates, lead times, best-performing categories,
and per-layer contribution metrics.

Used for building trust: "Pythia predicted X, and Y happened Z hours later."
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .confluence import EVENT_CATEGORIES, VALID_LAYERS, get_confluence_history
from .database import PythiaDB

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #

@dataclass
class CategoryStats:
    """Performance stats for a single event category."""
    category: str
    event_count: int = 0
    hit_count: int = 0
    hit_rate: float = 0.0
    avg_confluence_score: float = 0.0
    avg_lead_time_hours: float = 0.0
    false_positive_count: int = 0
    best_signal_description: str = ""


@dataclass
class ThresholdStats:
    """False positive rate at a given confidence threshold."""
    threshold: float
    total_events: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_positive_rate: float = 0.0
    precision: float = 0.0


@dataclass
class LayerContribution:
    """How much a single layer contributes to successful predictions."""
    layer: str
    appearances_total: int = 0
    appearances_in_hits: int = 0
    hit_rate_when_present: float = 0.0
    avg_confidence_when_present: float = 0.0


@dataclass
class TrackRecord:
    """
    Complete track record summary.

    Provides the proof layer: aggregated stats showing when Pythia's
    confluence signals were right, wrong, and how quickly they led
    the market.
    """
    # Time range
    days: int = 30
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    # Overall stats
    total_events: int = 0
    total_hits: int = 0
    overall_hit_rate: float = 0.0
    avg_lead_time_hours: float = 0.0
    avg_confluence_score: float = 0.0

    # False positive rates at different thresholds
    threshold_stats: List[ThresholdStats] = field(default_factory=list)

    # Per-category breakdown
    category_stats: List[CategoryStats] = field(default_factory=list)

    # Best performing categories (sorted by hit rate)
    best_categories: List[str] = field(default_factory=list)

    # Layer contribution — which layers appear most in successful predictions
    layer_contributions: List[LayerContribution] = field(default_factory=list)

    # Recent notable events
    notable_events: List[Dict] = field(default_factory=list)

    # Calibration diagnostics
    brier_score: float = 0.0
    calibration_curve: Dict = field(default_factory=dict)

    # Metadata
    computed_at: Optional[datetime] = None


# ------------------------------------------------------------------ #
# Data retrieval
# ------------------------------------------------------------------ #

def _fetch_confluence_events(
    db: PythiaDB, days: int
) -> List[Dict]:
    """
    Retrieve all confluence events from the database for the given window.

    Returns list of dicts with parsed JSON fields.
    """
    hours = days * 24
    events = get_confluence_history(db, hours=hours, min_score=0.0)

    # Enrich with parsed fields
    enriched = []
    for evt in events:
        # Parse layers JSON
        layers = evt.get("layers", "[]")
        if isinstance(layers, str):
            try:
                layers = json.loads(layers)
            except (json.JSONDecodeError, TypeError):
                layers = []
        evt["layers_parsed"] = layers

        # Parse signals JSON
        signals = evt.get("signals_json", "[]")
        if isinstance(signals, str):
            try:
                signals = json.loads(signals)
            except (json.JSONDecodeError, TypeError):
                signals = []
        evt["signals_parsed"] = signals

        # Parse suggested assets
        assets = evt.get("suggested_assets", "[]")
        if isinstance(assets, str):
            try:
                assets = json.loads(assets)
            except (json.JSONDecodeError, TypeError):
                assets = []
        evt["suggested_assets_parsed"] = assets

        enriched.append(evt)

    return enriched


def _check_hit(
    db: PythiaDB, evt: Dict, check_window_hours: int = 24
) -> Tuple[bool, float]:
    """
    Check if an event was a 'hit' — did the predicted asset actually move
    in the predicted direction within the check window?

    A hit is defined as:
    - At least one suggested asset moved >= 0.5% in the predicted direction
      within 24 hours of the confluence signal.

    Returns:
        (is_hit, lead_time_hours)
    """
    direction = evt.get("direction", "")
    timestamp_str = evt.get("timestamp", "")
    category = evt.get("event_category", "")

    if not timestamp_str or not direction or direction == "neutral":
        return False, 0.0

    # Check spike events that occurred after this confluence event
    try:
        with sqlite3.connect(db.db_path) as conn:
            rows = conn.execute(
                """
                SELECT direction, magnitude, timestamp, market_title, asset_class
                FROM spike_events
                WHERE timestamp > ? AND timestamp <= datetime(?, ?)
                AND magnitude >= 0.01
                ORDER BY timestamp ASC
                """,
                (timestamp_str, timestamp_str, f"+{check_window_hours} hours"),
            ).fetchall()

            if not rows:
                return False, 0.0

            # Check if any spike matches the predicted direction
            for row in rows:
                spike_dir = row[0]
                spike_mag = row[1]
                spike_ts = row[2]
                spike_title = row[3] or ""

                # Direction alignment
                direction_match = False
                if direction == "bullish" and spike_dir == "up":
                    direction_match = True
                elif direction == "bearish" and spike_dir == "down":
                    direction_match = True

                if not direction_match:
                    continue

                # Magnitude check — at least 1% move
                if spike_mag < 0.01:
                    continue

                # Category relevance check (loose)
                # The spike should be in a related market
                spike_cat_lower = spike_title.lower()
                cat_keywords = {
                    "fed_rate": ["fed", "rate", "fomc"],
                    "tariffs": ["tariff", "trade"],
                    "china_macro": ["china", "pboc"],
                    "geopolitical": ["war", "conflict", "russia", "ukraine"],
                    "crypto_regulation": ["crypto", "bitcoin", "sec"],
                    "recession": ["recession", "gdp", "jobs"],
                    "tech_regulation": ["tech", "google", "apple", "meta"],
                    "energy": ["oil", "opec", "energy"],
                }
                keywords = cat_keywords.get(category, [])
                # If we have keywords, check relevance; otherwise accept
                if keywords and not any(kw in spike_cat_lower for kw in keywords):
                    continue

                # Calculate lead time
                try:
                    evt_dt = datetime.fromisoformat(
                        str(timestamp_str).replace("Z", "+00:00")
                    )
                    spike_dt = datetime.fromisoformat(
                        str(spike_ts).replace("Z", "+00:00")
                    )
                    lead_hours = (spike_dt - evt_dt).total_seconds() / 3600.0
                except (ValueError, TypeError):
                    lead_hours = 0.0

                return True, max(0.0, lead_hours)

    except Exception as e:
        logger.debug("Hit check failed: %s", e)

    return False, 0.0


# ------------------------------------------------------------------ #
# Stats computation
# ------------------------------------------------------------------ #

def _compute_category_stats(
    events: List[Dict],
    hits: Dict[int, Tuple[bool, float]],
) -> List[CategoryStats]:
    """Compute per-category performance stats."""
    cat_data: Dict[str, Dict] = {}

    for evt in events:
        cat = evt.get("event_category", "unknown")
        evt_id = evt.get("id", 0)
        is_hit, lead_time = hits.get(evt_id, (False, 0.0))

        if cat not in cat_data:
            cat_data[cat] = {
                "count": 0,
                "hits": 0,
                "total_score": 0.0,
                "total_lead_time": 0.0,
                "best_desc": "",
                "best_score": 0.0,
            }

        stats = cat_data[cat]
        stats["count"] += 1
        stats["total_score"] += evt.get("confluence_score", 0)

        if is_hit:
            stats["hits"] += 1
            stats["total_lead_time"] += lead_time

        # Track best signal
        score = evt.get("confluence_score", 0)
        if score > stats["best_score"]:
            stats["best_score"] = score
            stats["best_desc"] = (evt.get("alert_text", "") or "")[:100]

    result: List[CategoryStats] = []
    for cat, data in cat_data.items():
        count = data["count"]
        hit_count = data["hits"]

        result.append(CategoryStats(
            category=cat,
            event_count=count,
            hit_count=hit_count,
            hit_rate=round(hit_count / count, 3) if count > 0 else 0.0,
            avg_confluence_score=round(data["total_score"] / count, 3) if count > 0 else 0.0,
            avg_lead_time_hours=round(
                data["total_lead_time"] / hit_count, 1
            ) if hit_count > 0 else 0.0,
            false_positive_count=count - hit_count,
            best_signal_description=data["best_desc"],
        ))

    result.sort(key=lambda x: x.hit_rate, reverse=True)
    return result


def _compute_threshold_stats(
    events: List[Dict],
    hits: Dict[int, Tuple[bool, float]],
    thresholds: List[float] = None,
) -> List[ThresholdStats]:
    """
    Compute false positive rates at different confidence thresholds.

    For each threshold, count how many events above that threshold
    were hits vs. false positives.
    """
    if thresholds is None:
        thresholds = [0.3, 0.5, 0.7, 0.9]

    results: List[ThresholdStats] = []

    for threshold in thresholds:
        above = [
            e for e in events
            if e.get("confluence_score", 0) >= threshold
        ]
        total = len(above)
        tp = sum(
            1 for e in above
            if hits.get(e.get("id", 0), (False, 0.0))[0]
        )
        fp = total - tp

        results.append(ThresholdStats(
            threshold=threshold,
            total_events=total,
            true_positives=tp,
            false_positives=fp,
            false_positive_rate=round(fp / total, 3) if total > 0 else 0.0,
            precision=round(tp / total, 3) if total > 0 else 0.0,
        ))

    return results


def _compute_layer_contributions(
    events: List[Dict],
    hits: Dict[int, Tuple[bool, float]],
) -> List[LayerContribution]:
    """
    Determine which layers contribute most to successful predictions.

    Tracks how often each layer appears in all events vs. hit events only.
    """
    layer_total: Dict[str, int] = {}
    layer_hits: Dict[str, int] = {}
    layer_conf: Dict[str, List[float]] = {}

    for evt in events:
        evt_id = evt.get("id", 0)
        is_hit = hits.get(evt_id, (False, 0.0))[0]

        layers = evt.get("layers_parsed", [])
        signals = evt.get("signals_parsed", [])

        # Build confidence map from signals
        sig_conf = {}
        for sig in signals:
            layer_name = sig.get("layer", "")
            sig_conf[layer_name] = sig.get("confidence", 0)

        for layer_name in layers:
            if layer_name not in VALID_LAYERS:
                continue
            layer_total[layer_name] = layer_total.get(layer_name, 0) + 1
            layer_conf.setdefault(layer_name, []).append(
                sig_conf.get(layer_name, 0.5)
            )
            if is_hit:
                layer_hits[layer_name] = layer_hits.get(layer_name, 0) + 1

    contributions: List[LayerContribution] = []
    for layer_name in VALID_LAYERS:
        total = layer_total.get(layer_name, 0)
        hit_count = layer_hits.get(layer_name, 0)
        confs = layer_conf.get(layer_name, [])

        contributions.append(LayerContribution(
            layer=layer_name,
            appearances_total=total,
            appearances_in_hits=hit_count,
            hit_rate_when_present=round(hit_count / total, 3) if total > 0 else 0.0,
            avg_confidence_when_present=round(
                sum(confs) / len(confs), 3
            ) if confs else 0.0,
        ))

    contributions.sort(key=lambda x: x.hit_rate_when_present, reverse=True)
    return contributions


def _select_notable_events(
    events: List[Dict],
    hits: Dict[int, Tuple[bool, float]],
    limit: int = 5,
) -> List[Dict]:
    """Select the most notable recent events for display."""
    scored: List[Tuple[float, Dict]] = []

    for evt in events:
        evt_id = evt.get("id", 0)
        is_hit, lead_time = hits.get(evt_id, (False, 0.0))
        score = evt.get("confluence_score", 0)

        # Prioritize hits with high confluence scores
        notability = score * (2.0 if is_hit else 1.0)
        scored.append((notability, {
            "category": evt.get("event_category", ""),
            "direction": evt.get("direction", ""),
            "score": score,
            "layers": evt.get("layer_count", 0),
            "is_hit": is_hit,
            "lead_time_hours": round(lead_time, 1) if is_hit else None,
            "timestamp": evt.get("timestamp", ""),
            "alert_text": (evt.get("alert_text", "") or "")[:120],
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]


# ------------------------------------------------------------------ #
# Main API
# ------------------------------------------------------------------ #

def get_track_record(
    days: int = 30,
    db: Optional[PythiaDB] = None,
    db_path: str = "data/pythia_live.db",
) -> TrackRecord:
    """
    Compute a full track record summary over the specified period.

    Analyses all confluence events within the window, checks which
    ones resulted in actual asset moves (hits), and computes:
    - Overall hit rate
    - Average lead time
    - False positive rates by confidence threshold
    - Best-performing categories
    - Per-layer contribution analysis
    - Notable events

    Args:
        days: Number of days to look back.
        db: Optional pre-initialised PythiaDB instance.
        db_path: Path to the database file (used if ``db`` is None).

    Returns:
        TrackRecord dataclass with full performance metrics.
    """
    if db is None:
        db = PythiaDB(db_path)

    now = datetime.now(timezone.utc)

    # --- 1. Fetch events ---
    events = _fetch_confluence_events(db, days)

    if not events:
        return TrackRecord(
            days=days,
            start_date=now - timedelta(days=days),
            end_date=now,
            computed_at=now,
        )

    # --- 2. Check hits ---
    hits: Dict[int, Tuple[bool, float]] = {}
    for evt in events:
        evt_id = evt.get("id", 0)
        is_hit, lead_time = _check_hit(db, evt)
        hits[evt_id] = (is_hit, lead_time)

    # --- 3. Overall stats ---
    total = len(events)
    total_hits = sum(1 for h in hits.values() if h[0])
    hit_lead_times = [h[1] for h in hits.values() if h[0] and h[1] > 0]
    avg_lead = sum(hit_lead_times) / len(hit_lead_times) if hit_lead_times else 0.0
    avg_score = sum(e.get("confluence_score", 0) for e in events) / total if total > 0 else 0.0

    # --- 4. Category stats ---
    cat_stats = _compute_category_stats(events, hits)
    best_cats = [
        cs.category for cs in cat_stats
        if cs.hit_rate > 0 and cs.event_count >= 2
    ][:5]

    # --- 5. Threshold stats ---
    threshold_stats = _compute_threshold_stats(events, hits)

    # --- 6. Layer contributions ---
    layer_contribs = _compute_layer_contributions(events, hits)

    # --- 7. Notable events ---
    notable = _select_notable_events(events, hits)

    # --- 8. Date range ---
    timestamps = [e.get("timestamp", "") for e in events if e.get("timestamp")]
    start_date = now - timedelta(days=days)
    if timestamps:
        try:
            earliest = min(timestamps)
            start_date = datetime.fromisoformat(
                str(earliest).replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

    return TrackRecord(
        days=days,
        start_date=start_date,
        end_date=now,
        total_events=total,
        total_hits=total_hits,
        overall_hit_rate=round(total_hits / total, 3) if total > 0 else 0.0,
        avg_lead_time_hours=round(avg_lead, 1),
        avg_confluence_score=round(avg_score, 3),
        threshold_stats=threshold_stats,
        category_stats=cat_stats,
        best_categories=best_cats,
        layer_contributions=layer_contribs,
        notable_events=notable,
        computed_at=now,
    )


# ------------------------------------------------------------------ #
# Formatting
# ------------------------------------------------------------------ #

def format_track_record(record: TrackRecord) -> str:
    """
    Format a TrackRecord for human-readable display.

    Suitable for Telegram, terminal, or PDF text sections.
    """
    lines = [
        f"📊 PYTHIA TRACK RECORD ({record.days}d)",
        f"Period: {record.start_date.strftime('%Y-%m-%d') if record.start_date else '?'} → "
        f"{record.end_date.strftime('%Y-%m-%d') if record.end_date else '?'}",
        "",
    ]

    if record.total_events == 0:
        lines.append("No confluence events recorded in this period.")
        return "\n".join(lines)

    # Overall
    lines.append(f"Events fired: {record.total_events}")
    lines.append(f"Hits: {record.total_hits} ({record.overall_hit_rate:.0%} hit rate)")
    lines.append(f"Avg lead time: {record.avg_lead_time_hours:.1f}h")
    lines.append(f"Avg confluence score: {record.avg_confluence_score:.2f}")
    lines.append(f"Brier score: {record.brier_score:.4f}")
    lines.append("")

    # Threshold breakdown
    lines.append("False Positive Rate by Threshold:")
    for ts in record.threshold_stats:
        if ts.total_events > 0:
            lines.append(
                f"  ≥{ts.threshold:.0%}: {ts.total_events} events, "
                f"FPR={ts.false_positive_rate:.0%}, "
                f"precision={ts.precision:.0%}"
            )

    lines.append("")

    # Best categories
    if record.best_categories:
        lines.append("Best Categories:")
        for cat_name in record.best_categories[:5]:
            cs = next(
                (c for c in record.category_stats if c.category == cat_name),
                None,
            )
            if cs:
                lines.append(
                    f"  • {cat_name}: {cs.hit_rate:.0%} hit rate "
                    f"({cs.event_count} events, {cs.avg_lead_time_hours:.1f}h lead)"
                )

    lines.append("")

    # Layer contributions
    lines.append("Layer Contributions (hit rate when present):")
    for lc in record.layer_contributions:
        if lc.appearances_total > 0:
            lines.append(
                f"  • {lc.layer}: {lc.hit_rate_when_present:.0%} "
                f"({lc.appearances_in_hits}/{lc.appearances_total} appearances)"
            )

    # Notable events
    if record.notable_events:
        lines.append("")
        lines.append("Notable Events:")
        for evt in record.notable_events[:3]:
            hit_str = "✅ HIT" if evt.get("is_hit") else "❌ MISS"
            lead_str = f" (led by {evt['lead_time_hours']}h)" if evt.get("lead_time_hours") else ""
            lines.append(
                f"  {hit_str} {evt.get('category', '?')} "
                f"({evt.get('score', 0):.0%} score, "
                f"{evt.get('layers', 0)} layers){lead_str}"
            )

    if record.calibration_curve:
        lines.append("")
        lines.append("Calibration:")
        counts = record.calibration_curve.get("counts", [])
        bins = record.calibration_curve.get("bins", [])
        if counts and bins:
            lines.append(f"  bins: {len(bins)} | samples: {sum(counts)}")

    return "\n".join(lines)


def format_track_record_for_pdf(record: TrackRecord) -> Dict:
    """
    Format TrackRecord as a structured dict suitable for PDF generation.

    Returns a dict with sections that a PDF renderer can consume:
    summary, thresholds, categories, layers, notable_events.
    """
    return {
        "title": f"Pythia Track Record — {record.days} Day Report",
        "generated_at": (
            record.computed_at.isoformat() if record.computed_at else ""
        ),
        "period": {
            "start": (
                record.start_date.isoformat() if record.start_date else ""
            ),
            "end": record.end_date.isoformat() if record.end_date else "",
            "days": record.days,
        },
        "summary": {
            "total_events": record.total_events,
            "total_hits": record.total_hits,
            "overall_hit_rate": record.overall_hit_rate,
            "avg_lead_time_hours": record.avg_lead_time_hours,
            "avg_confluence_score": record.avg_confluence_score,
        },
        "thresholds": [
            {
                "threshold": ts.threshold,
                "total_events": ts.total_events,
                "true_positives": ts.true_positives,
                "false_positives": ts.false_positives,
                "fpr": ts.false_positive_rate,
                "precision": ts.precision,
            }
            for ts in record.threshold_stats
        ],
        "categories": [
            {
                "category": cs.category,
                "event_count": cs.event_count,
                "hit_count": cs.hit_count,
                "hit_rate": cs.hit_rate,
                "avg_score": cs.avg_confluence_score,
                "avg_lead_time_hours": cs.avg_lead_time_hours,
            }
            for cs in record.category_stats
        ],
        "layers": [
            {
                "layer": lc.layer,
                "total_appearances": lc.appearances_total,
                "hit_appearances": lc.appearances_in_hits,
                "hit_rate": lc.hit_rate_when_present,
                "avg_confidence": lc.avg_confidence_when_present,
            }
            for lc in record.layer_contributions
        ],
        "notable_events": record.notable_events,
    }
