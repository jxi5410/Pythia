"""
Forward Signal Engine — Generates predictive signals by propagating
attributors through the PCMCI causal graph.

When an attributor fires on Market A, this engine:
1. Looks up the causal graph for markets caused by A (with lag)
2. Uses the heterogeneous effects model to predict magnitude
3. Generates time-stamped forward signals for each downstream market
4. Saves signals to DB for alerting and outcome tracking

This is the core "actionable intelligence" feature — the difference
between explaining the past and predicting what happens next.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def propagate_signals(
    attributor: Dict,
    source_spike: Dict,
    attributor_store,
    db,
    causal_graph=None,
    het_model=None,
    user_id: str = "default",
) -> List[Dict]:
    """
    Generate forward signals by walking the causal graph from the source market.

    Args:
        attributor: The attributor entity that fired
        source_spike: The spike context dict
        attributor_store: AttributorStore instance for saving signals
        db: PythiaDB instance
        causal_graph: Pre-computed CausalGraph from causal_discovery module.
                      If None, attempts to compute one.
        het_model: Pre-loaded heterogeneous effects model. If None, loads from disk.
        user_id: User ID for confidence threshold lookup

    Returns:
        List of forward signal dicts that were saved
    """
    source_market_id = source_spike.get("spike", {}).get("market_id", "")
    if not source_market_id:
        market_ids = attributor.get("market_ids", [])
        source_market_id = market_ids[0] if market_ids else ""

    if not source_market_id:
        logger.warning("No source market ID for forward propagation")
        return []

    # Get user's confidence threshold
    min_confidence = attributor_store.get_user_confidence_threshold(
        "forward_signal_confidence", user_id=user_id
    )

    # Step 1: Get causal links from this market
    downstream = _get_downstream_markets(source_market_id, db, causal_graph)

    if not downstream:
        logger.debug("No downstream markets found for %s", source_market_id[:20])
        return []

    # Step 2: Generate signals for each downstream market
    signals = []
    source_direction = source_spike.get("spike", {}).get("direction", "up")
    source_magnitude = float(source_spike.get("spike", {}).get("magnitude", 0))

    for target in downstream:
        target_market_id = target["market_id"]
        lag_hours = target.get("lag_hours", 1)
        causal_strength = target.get("strength", 0.5)

        # Step 3: Predict magnitude using heterogeneous effects model
        predicted_magnitude = _predict_target_magnitude(
            source_magnitude, causal_strength, target, het_model, db
        )

        # Predict direction based on causal relationship sign
        # Positive causal strength = same direction, negative = opposite
        if causal_strength >= 0:
            predicted_direction = source_direction
        else:
            predicted_direction = "down" if source_direction == "up" else "up"

        # Compute confidence: attributor confidence * causal strength * data quality
        attr_confidence = {"HIGH": 0.85, "MEDIUM": 0.6, "LOW": 0.3}.get(
            attributor.get("confidence", "MEDIUM"), 0.5
        )
        signal_confidence = attr_confidence * min(abs(causal_strength), 1.0)

        # Filter by user threshold
        if signal_confidence < min_confidence:
            continue

        # Get target market title
        target_title = _get_market_title(target_market_id, db)

        # Expiry: signal valid for 2x the predicted lag
        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=lag_hours * 2)
        ).isoformat()

        signal = {
            "attributor_id": attributor.get("id", attributor.get("attributor_id", "")),
            "source_market_id": source_market_id,
            "target_market_id": target_market_id,
            "target_market_title": target_title,
            "signal_type": "CAUSAL_PROPAGATION",
            "predicted_direction": predicted_direction,
            "predicted_magnitude": round(predicted_magnitude, 4),
            "predicted_lag_hours": lag_hours,
            "confidence_score": round(signal_confidence, 3),
            "causal_strength": round(causal_strength, 4),
            "expires_at": expires_at,
        }

        # Save to DB
        signal_id = attributor_store.save_forward_signal(signal)
        signal["id"] = signal_id
        signals.append(signal)

        logger.info(
            "Forward signal: %s → %s (%s %.1f%% in %dh, conf=%.2f)",
            source_market_id[:15],
            target_market_id[:15],
            predicted_direction,
            predicted_magnitude * 100,
            lag_hours,
            signal_confidence,
        )

    logger.info(
        "Generated %d forward signals from attributor '%s'",
        len(signals), attributor.get("name", "?")[:40],
    )

    return signals


def _get_downstream_markets(
    source_market_id: str,
    db,
    causal_graph=None,
) -> List[Dict]:
    """
    Find markets causally downstream of the source.

    Uses PCMCI causal graph if available, falls back to correlation data.
    """
    # Try causal graph first (PCMCI — directional)
    if causal_graph is not None:
        effects = causal_graph.get_effects_of(source_market_id)
        if effects:
            return [
                {
                    "market_id": link.target_market,
                    "lag_hours": link.lag_hours,
                    "strength": link.strength,
                    "method": "pcmci",
                }
                for link in effects
            ]

    # Try to load from causal_discovery module
    try:
        from .causal_discovery import discover_causal_graph_pcmci

        # Get correlated markets to include in graph
        corr_markets = []
        pairs = db.get_correlations(market_id=source_market_id)
        for p in pairs[:15]:
            other = p["market_id_b"] if p["market_id_a"] == source_market_id else p["market_id_a"]
            corr_markets.append(other)

        if corr_markets:
            market_ids = [source_market_id] + corr_markets
            graph = discover_causal_graph_pcmci(db, market_ids, hours=168, max_lag=6)
            effects = graph.get_effects_of(source_market_id)
            if effects:
                return [
                    {
                        "market_id": link.target_market,
                        "lag_hours": link.lag_hours,
                        "strength": link.strength,
                        "method": "pcmci",
                    }
                    for link in effects
                ]
    except (ImportError, Exception) as e:
        logger.debug("PCMCI graph computation failed: %s", e)

    # Fallback: use correlation data (non-directional)
    pairs = db.get_correlations(market_id=source_market_id)
    fallback = []
    for p in pairs:
        rho = float(p.get("spearman_rho", 0))
        pval = float(p.get("p_value", 1))
        if abs(rho) >= 0.3 and pval <= 0.05:
            other = p["market_id_b"] if p["market_id_a"] == source_market_id else p["market_id_a"]
            fallback.append({
                "market_id": other,
                "lag_hours": 1,  # Unknown lag with correlation
                "strength": rho,
                "method": "correlation_fallback",
            })

    return fallback[:10]


def _predict_target_magnitude(
    source_magnitude: float,
    causal_strength: float,
    target_info: Dict,
    het_model=None,
    db=None,
) -> float:
    """
    Predict how much the target market will move.

    Uses heterogeneous effects model if available, otherwise
    scales source magnitude by causal strength.
    """
    # Try EconML model
    if het_model is not None:
        try:
            from .heterogeneous_effects import predict_effect

            # Build a minimal context for the target market
            target_context = {
                "category": "general",
                "spike": {
                    "price_before": 0.5,
                    "volume": 0,
                    "magnitude": source_magnitude * abs(causal_strength),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                "correlated_spikes": [],
            }
            prediction = predict_effect(target_context, model=het_model)
            if prediction.get("predicted_effect") is not None:
                return abs(float(prediction["predicted_effect"]))
        except Exception as e:
            logger.debug("EconML prediction failed: %s", e)

    # Fallback: linear scaling
    return source_magnitude * abs(causal_strength) * 0.7  # 0.7 dampening factor


def _get_market_title(market_id: str, db) -> str:
    """Look up market title from DB."""
    try:
        market = db.get_market(market_id)
        if market:
            return market.get("title", "")
    except Exception:
        pass
    return ""


# ------------------------------------------------------------------ #
# Outcome tracking — resolve forward signals against actual prices
# ------------------------------------------------------------------ #

def check_signal_outcomes(attributor_store, db, lookback_hours: int = 24):
    """
    Check pending forward signals against actual price movements.
    Called periodically (e.g., hourly) to track prediction accuracy.
    """
    pending = attributor_store.get_pending_signals()
    resolved = 0
    correct = 0

    for signal in pending:
        target_id = signal.get("target_market_id")
        created_at = signal.get("created_at", "")
        predicted_lag = float(signal.get("predicted_lag_hours", 1))

        # Check if enough time has passed
        try:
            created_ts = datetime.fromisoformat(created_at)
        except Exception:
            continue

        elapsed = (datetime.now(timezone.utc) - created_ts.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        if elapsed < predicted_lag:
            continue  # Not yet time to evaluate

        # Check if signal has expired
        expires_at = signal.get("expires_at", "")
        if expires_at:
            try:
                expires_ts = datetime.fromisoformat(expires_at)
                if datetime.now(timezone.utc) > expires_ts.replace(tzinfo=timezone.utc):
                    attributor_store.resolve_signal(signal["id"], "expired", 0.0)
                    resolved += 1
                    continue
            except Exception:
                pass

        # Get actual price movement
        try:
            history = db.get_market_history(target_id, hours=int(predicted_lag) + 2)
            if history.empty or len(history) < 2:
                continue

            prices = history["yes_price"].astype(float).values
            actual_change = prices[-1] - prices[0]
            actual_direction = "up" if actual_change > 0 else "down"
            actual_magnitude = abs(actual_change)

            predicted_direction = signal.get("predicted_direction", "")
            direction_correct = actual_direction == predicted_direction

            attributor_store.resolve_signal(
                signal["id"], actual_direction, actual_magnitude
            )
            resolved += 1
            if direction_correct:
                correct += 1

        except Exception as e:
            logger.debug("Failed to check outcome for signal %d: %s", signal["id"], e)

    if resolved > 0:
        accuracy = correct / resolved * 100
        logger.info(
            "Signal outcomes: %d resolved, %d correct (%.0f%%)",
            resolved, correct, accuracy,
        )

    return {"resolved": resolved, "correct": correct}


# ------------------------------------------------------------------ #
# Narrative clustering
# ------------------------------------------------------------------ #

def cluster_attributors_into_narratives(attributor_store) -> List[Dict]:
    """
    Auto-cluster active attributors into narratives by category and
    keyword similarity. Creates or updates narrative entities.
    """
    active = attributor_store.get_active_attributors(limit=100)
    if not active:
        return []

    # Group by category
    by_category = {}
    for attr in active:
        cat = attr.get("category", "general")
        by_category.setdefault(cat, []).append(attr)

    narratives = []

    for category, attrs in by_category.items():
        if len(attrs) < 1:
            continue

        # Within each category, cluster by name similarity
        clusters = _cluster_by_similarity(attrs, threshold=0.3)

        for cluster in clusters:
            if not cluster:
                continue

            # Build narrative from cluster
            primary = cluster[0]  # Highest spike count
            all_market_ids = set()
            all_attributor_ids = []
            total_spikes = 0

            for attr in cluster:
                all_attributor_ids.append(attr["id"])
                all_market_ids.update(attr.get("market_ids", []))
                total_spikes += attr.get("spike_count", 0)

            # Narrative strength = spike_count * avg_confidence
            avg_conf = sum(
                float(a.get("confidence_score", 0.5)) for a in cluster
            ) / len(cluster)
            strength = total_spikes * avg_conf

            narrative_id = hashlib.sha256(
                f"{category}|{'|'.join(sorted(all_attributor_ids))}".encode()
            ).hexdigest()[:16]

            narrative = {
                "id": narrative_id,
                "name": primary["name"][:100],
                "description": f"{len(cluster)} related attributors in {category}",
                "category": category,
                "attributor_ids": all_attributor_ids,
                "market_ids": list(all_market_ids),
                "status": "active",
                "strength": round(strength, 2),
                "spike_count": total_spikes,
                "first_seen": min(a.get("first_seen", "") for a in cluster),
                "last_active": max(a.get("last_active", "") for a in cluster),
            }

            attributor_store.upsert_narrative(narrative)
            narratives.append(narrative)

    logger.info("Clustered %d attributors into %d narratives", len(active), len(narratives))
    return narratives


def _cluster_by_similarity(attrs: List[Dict], threshold: float = 0.3) -> List[List[Dict]]:
    """Simple agglomerative clustering by name similarity."""
    # Sort by spike count descending (most active first)
    attrs = sorted(attrs, key=lambda a: a.get("spike_count", 0), reverse=True)

    clusters = []
    used = set()

    for i, a in enumerate(attrs):
        if i in used:
            continue

        cluster = [a]
        used.add(i)

        for j in range(i + 1, len(attrs)):
            if j in used:
                continue
            if _word_overlap(a["name"], attrs[j]["name"]) >= threshold:
                cluster.append(attrs[j])
                used.add(j)

        clusters.append(cluster)

    return clusters


# Import needed for narrative clustering
import hashlib

def _word_overlap(a: str, b: str) -> float:
    """Jaccard similarity."""
    import re
    norm = lambda t: set(re.sub(r'[^a-z0-9\s]', '', t.lower()).split())
    wa, wb = norm(a), norm(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)
