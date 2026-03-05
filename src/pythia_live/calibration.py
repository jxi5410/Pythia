"""Forecast calibration scoring and tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from .database import PythiaDB


class BrierScorer:
    @staticmethod
    def score(forecast_prob: float, actual_outcome: int) -> float:
        p = float(np.clip(forecast_prob, 0.0, 1.0))
        y = 1.0 if int(actual_outcome) else 0.0
        return float((p - y) ** 2)

    @staticmethod
    def batch_score(forecasts: List[float], outcomes: List[int], n_bins: int = 10) -> Dict:
        if not forecasts:
            return {
                "brier_score": 0.0,
                "reliability": 0.0,
                "resolution": 0.0,
                "uncertainty": 0.0,
            }

        p = np.clip(np.asarray(forecasts, dtype=float), 0.0, 1.0)
        y = np.asarray(outcomes, dtype=float)
        bs = float(np.mean((p - y) ** 2))

        bins = np.linspace(0.0, 1.0, n_bins + 1)
        idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
        y_bar = float(np.mean(y))

        reliability = 0.0
        resolution = 0.0
        for b in range(n_bins):
            mask = idx == b
            if not np.any(mask):
                continue
            w = float(np.mean(mask))
            p_bin = float(np.mean(p[mask]))
            y_bin = float(np.mean(y[mask]))
            reliability += w * (p_bin - y_bin) ** 2
            resolution += w * (y_bin - y_bar) ** 2

        uncertainty = y_bar * (1.0 - y_bar)
        return {
            "brier_score": bs,
            "reliability": float(reliability),
            "resolution": float(resolution),
            "uncertainty": float(uncertainty),
        }

    @staticmethod
    def calibration_curve(forecasts: List[float], outcomes: List[int], n_bins: int = 10) -> Dict:
        if not forecasts:
            return {
                "bins": [],
                "observed_freq": [],
                "predicted_freq": [],
                "counts": [],
            }

        p = np.clip(np.asarray(forecasts, dtype=float), 0.0, 1.0)
        y = np.asarray(outcomes, dtype=float)
        bins = np.linspace(0.0, 1.0, n_bins + 1)
        idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)

        observed, predicted, counts = [], [], []
        centers = []
        for b in range(n_bins):
            mask = idx == b
            c = int(np.sum(mask))
            if c == 0:
                continue
            lo = float(bins[b])
            hi = float(bins[b + 1])
            centers.append((lo + hi) / 2.0)
            observed.append(float(np.mean(y[mask])))
            predicted.append(float(np.mean(p[mask])))
            counts.append(c)

        return {
            "bins": centers,
            "observed_freq": observed,
            "predicted_freq": predicted,
            "counts": counts,
        }


@dataclass
class CalibrationTracker:
    db: PythiaDB

    def record_forecast(self, market_id: str, forecast_prob: float, signal_type: str, metadata: Optional[Dict] = None) -> int:
        return self.db.save_forecast(
            market_id=market_id,
            forecast_prob=float(np.clip(forecast_prob, 0.0, 1.0)),
            signal_type=signal_type,
            metadata=metadata or {},
        )

    def record_outcome(
        self,
        market_id: str,
        actual_outcome: int,
        forecast_id: Optional[int] = None,
        signal_type: Optional[str] = None,
    ) -> Optional[int]:
        target_id = forecast_id
        if target_id is None:
            unresolved = self.db.get_unresolved_forecasts(market_id=market_id, signal_type=signal_type)
            if not unresolved:
                return None
            # resolve latest unresolved forecast to avoid random matching
            target_id = unresolved[0]["id"]

        return self.db.resolve_forecast(target_id, int(actual_outcome))

    def get_calibration_report(self, days: int = 30, signal_type: Optional[str] = None) -> Dict:
        outcomes = self.db.get_signal_outcomes(days=days, signal_type=signal_type)
        forecasts = [row["forecast_prob"] for row in outcomes]
        actuals = [row["actual_outcome"] for row in outcomes]

        summary = BrierScorer.batch_score(forecasts, actuals)
        curve = BrierScorer.calibration_curve(forecasts, actuals)

        return {
            "days": days,
            "count": len(outcomes),
            "brier": summary,
            "curve": curve,
            "ranking": self.get_signal_type_ranking(days=days),
        }

    def get_signal_type_ranking(self, days: int = 30) -> List[Dict]:
        out = []
        by_type = self.db.get_signal_outcomes_by_type(days=days)
        for signal_type, rows in by_type.items():
            forecasts = [r["forecast_prob"] for r in rows]
            actuals = [r["actual_outcome"] for r in rows]
            brier = BrierScorer.batch_score(forecasts, actuals)["brier_score"]
            out.append({"signal_type": signal_type, "brier_score": brier, "count": len(rows)})
        out.sort(key=lambda x: x["brier_score"])
        return out

    def detect_calibration_drift(self, window_days: int = 7) -> Dict:
        recent = self.db.get_signal_outcomes(days=window_days)
        baseline = self.db.get_signal_outcomes(days=90)

        if len(recent) < 20 or len(baseline) < 50:
            return {"drifting": False, "reason": "insufficient_data"}

        r_brier = BrierScorer.batch_score([r["forecast_prob"] for r in recent], [r["actual_outcome"] for r in recent])["brier_score"]
        b_brier = BrierScorer.batch_score([r["forecast_prob"] for r in baseline], [r["actual_outcome"] for r in baseline])["brier_score"]

        delta = r_brier - b_brier
        drifting = delta > 0.05

        return {
            "drifting": drifting,
            "recent_brier": r_brier,
            "baseline_brier": b_brier,
            "delta": delta,
            "bias": "overconfident" if drifting else "stable",
            "checked_at": datetime.now().isoformat(),
        }
