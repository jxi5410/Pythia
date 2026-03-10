"""
Heterogeneous Effect Estimator — Learns how different events affect
different markets differently using EconML's CausalForestDML.

Examples of what this discovers:
  - "CPI surprises cause 8% moves in fed_rate markets but only 2% in crypto"
  - "Geopolitical events cause 15% moves when volume is 3x+ but only 5% at normal volume"
  - "Election news moves markets more when prior probability is 40-60% (uncertain) vs 90%+ (settled)"

Requires accumulated historical spike data (3-6 months minimum).
Designed to be trained periodically (daily/weekly) and queried at spike time.

This is P3 — the most data-hungry component. It gets better over time
as Pythia accumulates more attributed spikes.
"""

import json
import logging
import os
import pickle
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Lazy import
_econml_available = None

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")


def _check_econml():
    global _econml_available
    if _econml_available is None:
        try:
            from econml.dml import CausalForestDML
            _econml_available = True
        except ImportError:
            _econml_available = False
            logger.info("econml not installed — heterogeneous effect features disabled")
    return _econml_available


# ------------------------------------------------------------------ #
# Feature engineering from spike data
# ------------------------------------------------------------------ #

# Feature columns used for heterogeneous effect estimation
FEATURE_COLUMNS = [
    "category_fed_rate",
    "category_inflation",
    "category_election",
    "category_crypto",
    "category_trade_war",
    "category_geopolitical",
    "category_tech",
    "category_recession",
    "category_energy",
    "category_general",
    "prior_probability",       # price before spike (0-1)
    "uncertainty",             # abs(0.5 - prior_probability) — closer to 0.5 = more uncertain
    "volume_at_spike_log",     # log(volume + 1)
    "hour_of_day",             # 0-23
    "day_of_week",             # 0-6
    "n_concurrent_spikes",     # how many other markets spiked at same time
]


def _build_features_from_spikes(db, min_magnitude: float = 0.02, limit: int = 500) -> Optional[pd.DataFrame]:
    """
    Build feature matrix from historical spike events.

    Returns DataFrame with columns:
        - Features (X): market characteristics at time of spike
        - Treatment (T): whether an attributable event was found (binary)
        - Outcome (Y): magnitude of the price move
    """
    try:
        spikes_df = db.get_spike_events(min_magnitude=min_magnitude, limit=limit)
    except Exception as e:
        logger.warning("Failed to load spike events: %s", e)
        return None

    if spikes_df.empty or len(spikes_df) < 30:
        logger.info("Insufficient spike data for heterogeneous effects (%d spikes)", len(spikes_df))
        return None

    rows = []
    for _, spike in spikes_df.iterrows():
        # Parse category
        asset_class = str(spike.get("asset_class", "general")).lower()

        # Parse attribution
        attributed = spike.get("attributed_events", "[]")
        if isinstance(attributed, str):
            try:
                attributed = json.loads(attributed)
            except Exception:
                attributed = []
        has_attribution = 1 if (isinstance(attributed, list) and len(attributed) > 0) else 0

        # Parse timestamp
        ts = spike.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except Exception:
                ts = datetime.utcnow()

        prior = float(spike.get("price_before", 0.5))
        volume = float(spike.get("volume_at_spike", 0))

        row = {
            # One-hot category encoding
            "category_fed_rate": 1 if asset_class == "fed_rate" else 0,
            "category_inflation": 1 if asset_class == "inflation" else 0,
            "category_election": 1 if asset_class == "election" else 0,
            "category_crypto": 1 if asset_class == "crypto" else 0,
            "category_trade_war": 1 if asset_class == "trade_war" else 0,
            "category_geopolitical": 1 if asset_class == "geopolitical" else 0,
            "category_tech": 1 if asset_class == "tech" else 0,
            "category_recession": 1 if asset_class == "recession" else 0,
            "category_energy": 1 if asset_class == "energy" else 0,
            "category_general": 1 if asset_class not in [
                "fed_rate", "inflation", "election", "crypto",
                "trade_war", "geopolitical", "tech", "recession", "energy"
            ] else 0,
            # Continuous features
            "prior_probability": prior,
            "uncertainty": abs(0.5 - prior),
            "volume_at_spike_log": float(np.log1p(volume)),
            "hour_of_day": ts.hour if hasattr(ts, "hour") else 12,
            "day_of_week": ts.weekday() if hasattr(ts, "weekday") else 0,
            "n_concurrent_spikes": 0,  # Would need cross-referencing with other spikes
            # Treatment and outcome
            "treatment": has_attribution,
            "outcome": float(spike.get("magnitude", 0)),
        }
        rows.append(row)

    return pd.DataFrame(rows)


# ------------------------------------------------------------------ #
# Model training
# ------------------------------------------------------------------ #

def train_heterogeneous_model(
    db,
    n_estimators: int = 200,
    min_samples_leaf: int = 5,
    save: bool = True,
) -> Dict:
    """
    Train a CausalForestDML model on historical spike data.

    The model learns heterogeneous treatment effects: how the causal
    impact of an event varies by market category, uncertainty level,
    volume, and time.

    Args:
        db: PythiaDB instance
        n_estimators: Number of trees in the forest
        min_samples_leaf: Minimum samples per leaf
        save: Whether to save the trained model to disk

    Returns:
        Dict with training summary and model metadata
    """
    if not _check_econml():
        return {"error": "econml not installed", "method": "unavailable"}

    from econml.dml import CausalForestDML

    # Build features
    data = _build_features_from_spikes(db)
    if data is None:
        return {"error": "insufficient_data", "n_spikes": 0}

    n_samples = len(data)
    if n_samples < 30:
        return {"error": "insufficient_data", "n_spikes": n_samples, "min_required": 30}

    # Split into X (features), T (treatment), Y (outcome)
    X = data[FEATURE_COLUMNS].values
    T = data["treatment"].values.astype(float)
    Y = data["outcome"].values.astype(float)

    # Check treatment has variation
    if T.std() < 0.01:
        return {
            "error": "no_treatment_variation",
            "treatment_mean": float(T.mean()),
            "n_spikes": n_samples,
        }

    try:
        model = CausalForestDML(
            n_estimators=n_estimators,
            min_samples_leaf=min_samples_leaf,
            random_state=42,
        )
        model.fit(Y, T, X=X)

        # Compute overall ATE (average treatment effect)
        ate = float(model.ate(X))
        ate_interval = model.ate_interval(X, alpha=0.05)
        ate_lower = float(ate_interval[0])
        ate_upper = float(ate_interval[1])

        # Compute effects for each category to see heterogeneity
        category_effects = {}
        category_cols = [c for c in FEATURE_COLUMNS if c.startswith("category_")]
        for i, col in enumerate(category_cols):
            mask = data[col] == 1
            if mask.sum() >= 5:
                cat_X = X[mask]
                effects = model.effect(cat_X)
                cat_name = col.replace("category_", "")
                category_effects[cat_name] = {
                    "mean_effect": round(float(effects.mean()), 4),
                    "std_effect": round(float(effects.std()), 4),
                    "n_samples": int(mask.sum()),
                }

        result = {
            "method": "causal_forest_dml",
            "n_samples": n_samples,
            "n_features": len(FEATURE_COLUMNS),
            "n_estimators": n_estimators,
            "ate": round(ate, 4),
            "ate_ci_lower": round(ate_lower, 4),
            "ate_ci_upper": round(ate_upper, 4),
            "category_effects": category_effects,
            "trained_at": datetime.utcnow().isoformat(),
        }

        # Save model
        if save:
            os.makedirs(MODEL_DIR, exist_ok=True)
            model_path = os.path.join(MODEL_DIR, "heterogeneous_effects.pkl")
            with open(model_path, "wb") as f:
                pickle.dump({"model": model, "feature_columns": FEATURE_COLUMNS, "metadata": result}, f)
            result["model_path"] = model_path
            logger.info("Saved heterogeneous effects model to %s", model_path)

        logger.info(
            "Trained heterogeneous effects model: n=%d ATE=%.4f [%.4f, %.4f]",
            n_samples, ate, ate_lower, ate_upper,
        )

        return result

    except Exception as e:
        logger.error("Heterogeneous effects training failed: %s", e)
        return {"error": str(e), "method": "causal_forest_dml"}


# ------------------------------------------------------------------ #
# Model inference — predict effect for a new spike
# ------------------------------------------------------------------ #

def _load_model() -> Optional[Tuple]:
    """Load saved model from disk."""
    model_path = os.path.join(MODEL_DIR, "heterogeneous_effects.pkl")
    if not os.path.exists(model_path):
        return None
    try:
        with open(model_path, "rb") as f:
            saved = pickle.load(f)
        return saved["model"], saved["feature_columns"], saved.get("metadata", {})
    except Exception as e:
        logger.warning("Failed to load heterogeneous effects model: %s", e)
        return None


def predict_effect(
    spike_context: Dict,
    model=None,
) -> Dict:
    """
    Predict the expected causal effect size for a new spike,
    given its market characteristics.

    Uses the trained CausalForestDML model to estimate:
    "For THIS type of market, at THIS uncertainty level, with THIS volume,
    how big should the causal effect be if the attributed event is real?"

    This helps validate attributions: if the model predicts a 2% effect
    but we observe a 10% spike, either the attribution is wrong or
    something else is also happening.

    Args:
        spike_context: Context dict from build_spike_context()
        model: Optional pre-loaded model. If None, loads from disk.

    Returns:
        Dict with predicted effect, confidence interval, and comparison
        to observed magnitude.
    """
    if not _check_econml():
        return {"error": "econml not installed"}

    # Load model if not provided
    if model is None:
        loaded = _load_model()
        if loaded is None:
            return {"error": "no_trained_model", "hint": "Run train_heterogeneous_model() first"}
        model, feature_columns, metadata = loaded
    else:
        feature_columns = FEATURE_COLUMNS
        metadata = {}

    spike = spike_context.get("spike", {})
    category = spike_context.get("category", "general")

    # Build feature vector
    prior = float(spike.get("price_before", 0.5))
    volume = float(spike.get("volume", 0))
    ts = spike.get("timestamp")
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except Exception:
            ts = datetime.utcnow()

    features = {
        "category_fed_rate": 1 if category == "fed_rate" else 0,
        "category_inflation": 1 if category == "inflation" else 0,
        "category_election": 1 if category == "election" else 0,
        "category_crypto": 1 if category == "crypto" else 0,
        "category_trade_war": 1 if category == "trade_war" else 0,
        "category_geopolitical": 1 if category == "geopolitical" else 0,
        "category_tech": 1 if category == "tech" else 0,
        "category_recession": 1 if category == "recession" else 0,
        "category_energy": 1 if category == "energy" else 0,
        "category_general": 1 if category not in [
            "fed_rate", "inflation", "election", "crypto",
            "trade_war", "geopolitical", "tech", "recession", "energy"
        ] else 0,
        "prior_probability": prior,
        "uncertainty": abs(0.5 - prior),
        "volume_at_spike_log": float(np.log1p(volume)),
        "hour_of_day": ts.hour if hasattr(ts, "hour") else 12,
        "day_of_week": ts.weekday() if hasattr(ts, "weekday") else 0,
        "n_concurrent_spikes": len(spike_context.get("correlated_spikes", [])),
    }

    X = np.array([[features[col] for col in feature_columns]])

    try:
        predicted_effect = float(model.effect(X)[0])
        effect_interval = model.effect_interval(X, alpha=0.05)
        ci_lower = float(effect_interval[0][0])
        ci_upper = float(effect_interval[1][0])

        observed_magnitude = float(spike.get("magnitude", 0))

        # Compare predicted vs observed
        if predicted_effect > 0 and observed_magnitude > 0:
            ratio = observed_magnitude / predicted_effect
            if ratio > 3.0:
                anomaly = "MUCH_LARGER_THAN_EXPECTED"
            elif ratio > 1.5:
                anomaly = "LARGER_THAN_EXPECTED"
            elif ratio < 0.3:
                anomaly = "MUCH_SMALLER_THAN_EXPECTED"
            elif ratio < 0.7:
                anomaly = "SMALLER_THAN_EXPECTED"
            else:
                anomaly = "CONSISTENT"
        else:
            ratio = None
            anomaly = "INSUFFICIENT_DATA"

        result = {
            "predicted_effect": round(predicted_effect, 4),
            "ci_lower": round(ci_lower, 4),
            "ci_upper": round(ci_upper, 4),
            "observed_magnitude": round(observed_magnitude, 4),
            "observed_vs_predicted_ratio": round(ratio, 2) if ratio else None,
            "anomaly_flag": anomaly,
            "category": category,
            "prior_probability": prior,
            "uncertainty": round(abs(0.5 - prior), 3),
            "model_trained_at": metadata.get("trained_at", "unknown"),
            "model_n_samples": metadata.get("n_samples", 0),
        }

        logger.info(
            "Predicted effect: %.4f [%.4f, %.4f] vs observed %.4f — %s",
            predicted_effect, ci_lower, ci_upper, observed_magnitude, anomaly,
        )

        return result

    except Exception as e:
        logger.error("Effect prediction failed: %s", e)
        return {"error": str(e)}


# ------------------------------------------------------------------ #
# Summary: what has the model learned?
# ------------------------------------------------------------------ #

def get_model_insights() -> Dict:
    """
    Return a summary of what the heterogeneous effects model has learned.
    Useful for dashboards and portfolio demos.
    """
    loaded = _load_model()
    if loaded is None:
        return {"error": "no_trained_model"}

    model, feature_columns, metadata = loaded

    return {
        "model_type": "CausalForestDML",
        "trained_at": metadata.get("trained_at"),
        "n_samples": metadata.get("n_samples"),
        "average_treatment_effect": metadata.get("ate"),
        "ate_confidence_interval": [
            metadata.get("ate_ci_lower"),
            metadata.get("ate_ci_upper"),
        ],
        "category_effects": metadata.get("category_effects", {}),
        "feature_columns": feature_columns,
        "interpretation": (
            "The model estimates how different market categories respond differently "
            "to causal events. Categories with higher mean_effect see larger price moves "
            "when an attributable event occurs. Categories with high std_effect show more "
            "variable responses (harder to predict)."
        ),
    }
