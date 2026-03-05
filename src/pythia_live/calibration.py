"""
Calibration Engine — Brier score tracking and calibration monitoring.

Measures forecast quality using proper scoring rules:
- Brier score with Murphy decomposition
- Calibration curves
- Per-signal-type ranking
- Drift detection
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .database import PythiaDB

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #

@dataclass
class BrierResult:
    """Brier score with Murphy decomposition."""
    brier_score: float       # 0 = perfect, 1 = worst
    reliability: float       # calibration component (lower = better)
    resolution: float        # discrimination component (higher = better)
    uncertainty: float       # base rate component (irreducible)
    sample_size: int


@dataclass
class CalibrationBin:
    """A single bin of the calibration curve."""
    bin_lower: float
    bin_upper: float
    predicted_mean: float
    observed_freq: float
    count: int


@dataclass
class CalibrationCurve:
    """Full calibration curve."""
    bins: List[CalibrationBin]
    n_total: int


@dataclass
class CalibrationAlert:
    """Alert when calibration drifts."""
    alert_type: str          # "overconfident" or "underconfident"
    magnitude: float         # how far off
    recent_brier: float
    historical_brier: float
    affected_signal_types: List[str] = field(default_factory=list)


@dataclass
class CalibrationReport:
    """Complete calibration report."""
    brier: BrierResult
    curve: CalibrationCurve
    per_signal_type: Dict[str, float]  # signal_type -> brier_score
    best_signal_types: List[str]       # ranked by brier (best first)
    drift_alert: Optional[CalibrationAlert] = None


# ------------------------------------------------------------------ #
# Brier Scorer
# ------------------------------------------------------------------ #

class BrierScorer:
    """Proper scoring rule implementation."""

    @staticmethod
    def score(forecast_prob: float, actual_outcome: float) -> float:
        """Single Brier score: (forecast - outcome)^2."""
        return (forecast_prob - actual_outcome) ** 2

    @staticmethod
    def batch_score(forecasts: np.ndarray,
                    outcomes: np.ndarray) -> BrierResult:
        """
        Batch Brier score with Murphy decomposition.

        BS = reliability - resolution + uncertainty
        """
        if len(forecasts) == 0:
            return BrierResult(
                brier_score=0.0, reliability=0.0,
                resolution=0.0, uncertainty=0.0, sample_size=0,
            )

        forecasts = np.asarray(forecasts, dtype=float)
        outcomes = np.asarray(outcomes, dtype=float)

        brier = float(np.mean((forecasts - outcomes) ** 2))
        base_rate = float(np.mean(outcomes))
        uncertainty = base_rate * (1 - base_rate)

        # Bin forecasts for decomposition
        n_bins = min(10, max(2, len(forecasts) // 5))
        bin_edges = np.linspace(0, 1, n_bins + 1)

        reliability = 0.0
        resolution = 0.0

        for i in range(n_bins):
            mask = (forecasts >= bin_edges[i]) & (forecasts < bin_edges[i + 1])
            if i == n_bins - 1:
                mask = (forecasts >= bin_edges[i]) & (forecasts <= bin_edges[i + 1])

            n_k = mask.sum()
            if n_k == 0:
                continue

            frac = n_k / len(forecasts)
            forecast_mean = float(np.mean(forecasts[mask]))
            observed_freq = float(np.mean(outcomes[mask]))

            reliability += frac * (forecast_mean - observed_freq) ** 2
            resolution += frac * (observed_freq - base_rate) ** 2

        return BrierResult(
            brier_score=round(brier, 6),
            reliability=round(reliability, 6),
            resolution=round(resolution, 6),
            uncertainty=round(uncertainty, 6),
            sample_size=len(forecasts),
        )

    @staticmethod
    def calibration_curve(forecasts: np.ndarray, outcomes: np.ndarray,
                          n_bins: int = 10) -> CalibrationCurve:
        """
        Compute calibration curve — predicted vs. observed frequencies.

        "When we say 70%, does it happen 70% of the time?"
        """
        forecasts = np.asarray(forecasts, dtype=float)
        outcomes = np.asarray(outcomes, dtype=float)
        bin_edges = np.linspace(0, 1, n_bins + 1)

        bins = []
        for i in range(n_bins):
            lower = bin_edges[i]
            upper = bin_edges[i + 1]
            mask = (forecasts >= lower) & (forecasts < upper)
            if i == n_bins - 1:
                mask = (forecasts >= lower) & (forecasts <= upper)

            count = int(mask.sum())
            if count == 0:
                predicted_mean = (lower + upper) / 2
                observed_freq = 0.0
            else:
                predicted_mean = float(np.mean(forecasts[mask]))
                observed_freq = float(np.mean(outcomes[mask]))

            bins.append(CalibrationBin(
                bin_lower=round(lower, 2),
                bin_upper=round(upper, 2),
                predicted_mean=round(predicted_mean, 4),
                observed_freq=round(observed_freq, 4),
                count=count,
            ))

        return CalibrationCurve(bins=bins, n_total=len(forecasts))


# ------------------------------------------------------------------ #
# Calibration Tracker
# ------------------------------------------------------------------ #

class CalibrationTracker:
    """
    Persistent calibration monitoring backed by the database.

    Records forecasts on signal detection, resolves them on position close,
    and produces calibration reports.
    """

    def __init__(self, db: PythiaDB):
        self.db = db
        self._scorer = BrierScorer()

    def record_forecast(self, market_id: str, forecast_prob: float,
                        signal_type: str) -> int:
        """Record a forecast for later calibration. Returns forecast ID."""
        return self.db.save_forecast(market_id, forecast_prob, signal_type)

    def record_outcome(self, market_id: str, actual_outcome: float):
        """
        Resolve all unresolved forecasts for a market.

        Called when a position is closed and the outcome is known.
        """
        unresolved = self.db.get_unresolved_forecasts(market_id)
        for f in unresolved:
            self.db.resolve_forecast(f['id'], actual_outcome)

    def get_calibration_report(self, days: int = 30,
                               signal_type: Optional[str] = None) -> CalibrationReport:
        """
        Compute full calibration report.

        Args:
            days: Look-back window.
            signal_type: Optional filter.
        """
        resolved = self.db.get_resolved_forecasts(days, signal_type)

        if not resolved:
            empty_brier = BrierResult(0, 0, 0, 0, 0)
            empty_curve = CalibrationCurve([], 0)
            return CalibrationReport(
                brier=empty_brier, curve=empty_curve,
                per_signal_type={}, best_signal_types=[],
            )

        forecasts = np.array([r['forecast_prob'] for r in resolved])
        outcomes = np.array([r['actual_outcome'] for r in resolved])

        brier = self._scorer.batch_score(forecasts, outcomes)
        curve = self._scorer.calibration_curve(forecasts, outcomes)

        # Per signal type
        type_scores = {}
        types = set(r['signal_type'] for r in resolved)
        for st in types:
            st_mask = [r['signal_type'] == st for r in resolved]
            st_forecasts = forecasts[st_mask]
            st_outcomes = outcomes[st_mask]
            if len(st_forecasts) >= 3:
                type_scores[st] = round(float(np.mean(
                    (st_forecasts - st_outcomes) ** 2
                )), 4)

        best_types = sorted(type_scores.keys(), key=lambda k: type_scores[k])

        # Drift detection
        drift = self._detect_drift(days)

        return CalibrationReport(
            brier=brier,
            curve=curve,
            per_signal_type=type_scores,
            best_signal_types=best_types,
            drift_alert=drift,
        )

    def get_signal_type_ranking(self, days: int = 30) -> List[Tuple[str, float]]:
        """Rank signal types by Brier score (lower = better)."""
        report = self.get_calibration_report(days)
        return [(st, report.per_signal_type[st]) for st in report.best_signal_types]

    def _detect_drift(self, full_window_days: int = 30,
                      recent_window_days: int = 7) -> Optional[CalibrationAlert]:
        """
        Detect calibration drift by comparing recent vs. historical Brier.

        Alerts when recent forecasts are systematically worse.
        """
        historical = self.db.get_resolved_forecasts(full_window_days)
        recent = self.db.get_resolved_forecasts(recent_window_days)

        if len(historical) < 10 or len(recent) < 5:
            return None

        hist_forecasts = np.array([r['forecast_prob'] for r in historical])
        hist_outcomes = np.array([r['actual_outcome'] for r in historical])
        hist_brier = float(np.mean((hist_forecasts - hist_outcomes) ** 2))

        recent_forecasts = np.array([r['forecast_prob'] for r in recent])
        recent_outcomes = np.array([r['actual_outcome'] for r in recent])
        recent_brier = float(np.mean((recent_forecasts - recent_outcomes) ** 2))

        # Significant drift: >50% worse than historical
        if recent_brier > hist_brier * 1.5 and recent_brier > 0.1:
            # Determine type
            avg_forecast = float(np.mean(recent_forecasts))
            avg_outcome = float(np.mean(recent_outcomes))

            if avg_forecast > avg_outcome + 0.1:
                alert_type = "overconfident"
            elif avg_forecast < avg_outcome - 0.1:
                alert_type = "underconfident"
            else:
                alert_type = "degraded"

            # Find which signal types are worst
            affected = []
            types = set(r['signal_type'] for r in recent)
            for st in types:
                st_recent = [r for r in recent if r['signal_type'] == st]
                if len(st_recent) >= 3:
                    st_brier = np.mean([
                        (r['forecast_prob'] - r['actual_outcome']) ** 2
                        for r in st_recent
                    ])
                    if st_brier > hist_brier * 2:
                        affected.append(st)

            return CalibrationAlert(
                alert_type=alert_type,
                magnitude=round(recent_brier - hist_brier, 4),
                recent_brier=round(recent_brier, 4),
                historical_brier=round(hist_brier, 4),
                affected_signal_types=affected,
            )

        return None
