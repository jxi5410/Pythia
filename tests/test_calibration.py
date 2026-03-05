import sqlite3
import tempfile

import numpy as np

from pythia_live.calibration import BrierScorer, CalibrationTracker
from pythia_live.database import PythiaDB


def test_brier_perfect_forecaster():
    assert BrierScorer.score(1.0, 1) == 0.0
    assert BrierScorer.score(0.0, 0) == 0.0


def test_murphy_decomposition_identity():
    forecasts = [0.1, 0.2, 0.8, 0.9]
    outcomes = [0, 0, 1, 1]
    out = BrierScorer.batch_score(forecasts, outcomes, n_bins=4)
    lhs = out["reliability"] - out["resolution"] + out["uncertainty"]
    assert abs(lhs - out["brier_score"]) < 1e-2


def test_calibration_curve_bins():
    forecasts = [0.1, 0.15, 0.8, 0.85]
    outcomes = [0, 0, 1, 1]
    curve = BrierScorer.calibration_curve(forecasts, outcomes, n_bins=4)
    assert sum(curve["counts"]) == 4
    assert len(curve["observed_freq"]) == len(curve["predicted_freq"])


def test_db_roundtrip_forecast_resolve():
    with tempfile.TemporaryDirectory() as td:
        db = PythiaDB(f"{td}/cali.db")
        tracker = CalibrationTracker(db)

        fid = tracker.record_forecast("m1", 0.7, "PROBABILITY_SPIKE")
        resolved = tracker.record_outcome("m1", actual_outcome=1, forecast_id=fid)
        assert resolved == fid

        rows = db.get_signal_outcomes(days=30)
        assert len(rows) == 1
        assert rows[0]["brier_score"] == (0.7 - 1.0) ** 2


def test_drift_detection_overconfidence():
    with tempfile.TemporaryDirectory() as td:
        db = PythiaDB(f"{td}/drift.db")
        tracker = CalibrationTracker(db)

        # Baseline: relatively calibrated
        for i in range(80):
            fid = tracker.record_forecast(f"m{i}", 0.55, "S")
            tracker.record_outcome(f"m{i}", int(i % 2 == 0), forecast_id=fid)

        # Recent: strongly overconfident + wrong
        for i in range(30):
            fid = tracker.record_forecast(f"r{i}", 0.95, "S")
            tracker.record_outcome(f"r{i}", 0, forecast_id=fid)

        # Force baseline records older than recent window
        with sqlite3.connect(db.db_path) as conn:
            conn.execute(
                """
                UPDATE forecasts
                SET created_at = datetime('now', '-30 days')
                WHERE market_id LIKE 'm%'
                """
            )
            conn.commit()

        drift = tracker.detect_calibration_drift(window_days=7)
        assert drift["drifting"] is True
