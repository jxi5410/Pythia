"""
Counterfactual Spike Validator — Uses Bayesian structural time-series
(Google CausalImpact) to test whether a detected spike is statistically
significant or within normal variance.

How it works:
  1. Takes the spiking market's price history as the "treatment" series
  2. Takes correlated markets that did NOT spike as "control" series
  3. Builds a synthetic counterfactual: "what would have happened without the event?"
  4. Tests whether the observed spike exceeds the counterfactual prediction interval

Insert between spike detection and LLM attribution to filter false positives.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Lazy import — CausalImpact is optional dependency
_CausalImpact = None


def _get_causal_impact():
    global _CausalImpact
    if _CausalImpact is None:
        try:
            # Patch pandas 2.0+ compatibility (applymap → map)
            if not hasattr(pd.DataFrame, "applymap"):
                pd.DataFrame.applymap = pd.DataFrame.map
            from causalimpact import CausalImpact
            _CausalImpact = CausalImpact
        except ImportError:
            _CausalImpact = False  # Mark as unavailable
        except Exception as e:
            logger.warning("CausalImpact import failed: %s", e)
            _CausalImpact = False
    if _CausalImpact is False:
        return None
    return _CausalImpact


def _load_hourly_series(db, market_id: str, hours: int = 168) -> pd.Series:
    """Load market price history as hourly-resampled series."""
    df = db.get_market_history(market_id, hours=hours)
    if df.empty or "timestamp" not in df or "yes_price" not in df:
        return pd.Series(dtype=float)

    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    series = pd.Series(df["yes_price"].astype(float).values, index=ts)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series.resample("1h").last().ffill().dropna()


def _find_control_markets(
    db,
    target_market_id: str,
    spike_timestamp: datetime,
    spike_magnitude: float,
    min_correlation: float = 0.3,
    max_controls: int = 5,
) -> List[str]:
    """
    Find markets correlated with the target that did NOT spike at the same time.
    These serve as the synthetic control group.
    """
    # Get correlated markets from DB
    pairs = db.get_correlations(market_id=target_market_id)
    if not pairs:
        return []

    # Sort by absolute correlation strength
    pairs.sort(key=lambda r: abs(float(r.get("spearman_rho", 0))), reverse=True)

    controls = []
    for row in pairs:
        rho = float(row.get("spearman_rho", 0))
        if abs(rho) < min_correlation:
            continue

        other_id = (
            row["market_id_b"]
            if row["market_id_a"] == target_market_id
            else row["market_id_a"]
        )

        # Check if this market also spiked (if so, it's not a valid control)
        other_history = db.get_market_history(other_id, hours=4)
        if other_history.empty or len(other_history) < 2:
            continue

        prices = other_history["yes_price"].astype(float).values
        other_magnitude = abs(prices[-1] - prices[0])

        # Control market should NOT have spiked significantly
        if other_magnitude < spike_magnitude * 0.5:
            controls.append(other_id)

        if len(controls) >= max_controls:
            break

    return controls


def validate_spike(
    db,
    market_id: str,
    spike_timestamp: datetime,
    spike_magnitude: float,
    pre_period_hours: int = 168,
    post_period_hours: int = 6,
    control_market_ids: Optional[List[str]] = None,
) -> Dict:
    """
    Use CausalImpact to test whether a spike is statistically significant.

    Args:
        db: PythiaDB instance
        market_id: The market that spiked
        spike_timestamp: When the spike was detected
        spike_magnitude: Absolute price change (0-1)
        pre_period_hours: Training window before spike (default 7 days)
        post_period_hours: Observation window after spike (default 6h)
        control_market_ids: Optional explicit control markets. If None,
                           auto-discovers from correlation data.

    Returns:
        Dict with:
            is_significant: bool — whether the spike is real
            p_value: float — posterior probability of no effect
            cumulative_effect: float — estimated causal effect size
            relative_effect_pct: float — effect as % of pre-period mean
            ci_lower: float — 95% CI lower bound
            ci_upper: float — 95% CI upper bound
            n_controls: int — number of control series used
            method: str — "causal_impact" or "fallback_zscore"
    """
    if isinstance(spike_timestamp, str):
        spike_timestamp = pd.Timestamp(spike_timestamp)

    # Load target series
    target = _load_hourly_series(db, market_id, hours=pre_period_hours + post_period_hours)
    if len(target) < 24:
        logger.warning("Insufficient data for CausalImpact (%d points)", len(target))
        return _fallback_zscore(target, spike_timestamp, spike_magnitude)

    # Find or use control markets
    if control_market_ids is None:
        control_market_ids = _find_control_markets(
            db, market_id, spike_timestamp, spike_magnitude
        )

    # Load control series
    controls = {}
    for cid in control_market_ids:
        s = _load_hourly_series(db, cid, hours=pre_period_hours + post_period_hours)
        if len(s) >= 24:
            controls[cid] = s

    if not controls:
        logger.info("No valid control markets — falling back to z-score method")
        return _fallback_zscore(target, spike_timestamp, spike_magnitude)

    # Build aligned panel: target + controls
    panel = pd.DataFrame({"target": target})
    for cid, series in controls.items():
        panel[cid] = series
    panel = panel.dropna().sort_index()

    if len(panel) < 24:
        return _fallback_zscore(target, spike_timestamp, spike_magnitude)

    # Define pre/post periods
    spike_ts = pd.Timestamp(spike_timestamp, tz="UTC")
    pre_start = panel.index[0]
    pre_end = spike_ts - timedelta(hours=1)
    post_start = spike_ts
    post_end = panel.index[-1]

    # Ensure periods are within data range
    if pre_end <= pre_start or post_start >= post_end:
        return _fallback_zscore(target, spike_timestamp, spike_magnitude)

    pre_period = [pre_start, pre_end]
    post_period = [post_start, post_end]

    try:
        CausalImpact = _get_causal_impact()
        if CausalImpact is None:
            logger.info("CausalImpact not available — using z-score fallback")
            return _fallback_zscore(target, spike_timestamp, spike_magnitude)
        ci = CausalImpact(panel, pre_period, post_period)
        summary = ci.summary_data

        avg = summary.get("average", {})
        cum = summary.get("cumulative", {})

        p_value = float(avg.get("p_value", 1.0))
        abs_effect = float(avg.get("abs_effect", 0.0))
        rel_effect = float(avg.get("rel_effect", 0.0))
        ci_lower = float(avg.get("abs_effect_lower", 0.0))
        ci_upper = float(avg.get("abs_effect_upper", 0.0))

        is_significant = p_value < 0.05

        result = {
            "is_significant": is_significant,
            "p_value": round(p_value, 4),
            "cumulative_effect": round(abs_effect, 4),
            "relative_effect_pct": round(rel_effect * 100, 2),
            "ci_lower": round(ci_lower, 4),
            "ci_upper": round(ci_upper, 4),
            "n_controls": len(controls),
            "control_markets": list(controls.keys()),
            "method": "causal_impact",
            "pre_period_points": len(panel.loc[pre_start:pre_end]),
            "post_period_points": len(panel.loc[post_start:post_end]),
        }

        logger.info(
            "CausalImpact: significant=%s p=%.4f effect=%.4f (%.1f%%) controls=%d",
            is_significant, p_value, abs_effect, rel_effect * 100, len(controls),
        )

        return result

    except Exception as e:
        logger.warning("CausalImpact failed: %s — falling back to z-score", e)
        return _fallback_zscore(target, spike_timestamp, spike_magnitude)


def _fallback_zscore(
    series: pd.Series,
    spike_timestamp: datetime,
    spike_magnitude: float,
) -> Dict:
    """
    Fallback validation when CausalImpact can't run (no controls, insufficient data).
    Uses simple z-score of the price change vs historical volatility.
    """
    if series.empty or len(series) < 10:
        return {
            "is_significant": True,  # Can't disprove, let it through
            "p_value": None,
            "cumulative_effect": float(spike_magnitude),
            "relative_effect_pct": None,
            "ci_lower": None,
            "ci_upper": None,
            "n_controls": 0,
            "method": "insufficient_data",
        }

    # Compute hourly returns
    returns = series.diff().dropna()
    if len(returns) < 10:
        return {
            "is_significant": True,
            "p_value": None,
            "cumulative_effect": float(spike_magnitude),
            "method": "insufficient_data",
            "n_controls": 0,
        }

    mean_return = float(returns.mean())
    std_return = float(returns.std())

    if std_return < 1e-8:
        z_score = 0.0
    else:
        z_score = (spike_magnitude - mean_return) / std_return

    # Two-tailed p-value
    from scipy.stats import norm
    p_value = 2 * (1 - norm.cdf(abs(z_score)))

    is_significant = abs(z_score) >= 2.0  # ~95% confidence

    result = {
        "is_significant": is_significant,
        "p_value": round(p_value, 4),
        "z_score": round(z_score, 2),
        "cumulative_effect": float(spike_magnitude),
        "historical_volatility": round(std_return, 4),
        "relative_effect_pct": round(spike_magnitude / max(abs(mean_return), 1e-8) * 100, 1),
        "ci_lower": None,
        "ci_upper": None,
        "n_controls": 0,
        "method": "fallback_zscore",
    }

    logger.info(
        "Z-score fallback: significant=%s z=%.2f p=%.4f vol=%.4f",
        is_significant, z_score, p_value, std_return,
    )

    return result
