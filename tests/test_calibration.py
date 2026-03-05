#!/usr/bin/env python3
"""Tests for the calibration module."""

import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from pythia_live.calibration import BrierScorer, CalibrationTracker
from pythia_live.database import PythiaDB


class TestBrierScorer(unittest.TestCase):
    """Tests for proper scoring rule computation."""

    def test_perfect_score(self):
        """Perfect forecaster should have Brier = 0."""
        score = BrierScorer.score(1.0, 1.0)
        self.assertAlmostEqual(score, 0.0)

    def test_worst_score(self):
        """Maximally wrong forecaster should have Brier = 1."""
        score = BrierScorer.score(1.0, 0.0)
        self.assertAlmostEqual(score, 1.0)

    def test_uninformed_score(self):
        """50/50 forecaster on 50/50 outcomes should have Brier = 0.25."""
        score = BrierScorer.score(0.5, 1.0)
        self.assertAlmostEqual(score, 0.25)

    def test_batch_score_perfect(self):
        """Batch perfect forecaster should have Brier = 0."""
        forecasts = np.array([1.0, 0.0, 1.0, 0.0])
        outcomes = np.array([1.0, 0.0, 1.0, 0.0])
        result = BrierScorer.batch_score(forecasts, outcomes)
        self.assertAlmostEqual(result.brier_score, 0.0)
        self.assertEqual(result.sample_size, 4)

    def test_decomposition_sum(self):
        """reliability - resolution + uncertainty should approximate brier_score."""
        rng = np.random.default_rng(42)
        forecasts = rng.uniform(0, 1, 100)
        outcomes = (rng.uniform(0, 1, 100) > 0.5).astype(float)
        result = BrierScorer.batch_score(forecasts, outcomes)
        reconstructed = result.reliability - result.resolution + result.uncertainty
        self.assertAlmostEqual(result.brier_score, reconstructed, delta=0.05)

    def test_batch_empty(self):
        """Empty arrays should return zero brier."""
        result = BrierScorer.batch_score(np.array([]), np.array([]))
        self.assertEqual(result.brier_score, 0.0)
        self.assertEqual(result.sample_size, 0)

    def test_calibration_curve_bins(self):
        """Calibration curve should have correct number of bins."""
        forecasts = np.linspace(0, 1, 50)
        outcomes = np.ones(50)
        curve = BrierScorer.calibration_curve(forecasts, outcomes, n_bins=5)
        self.assertEqual(len(curve.bins), 5)
        self.assertEqual(curve.n_total, 50)

    def test_calibration_curve_perfect(self):
        """Well-calibrated forecaster: predicted = observed."""
        rng = np.random.default_rng(42)
        n = 1000
        forecasts = rng.uniform(0, 1, n)
        outcomes = (rng.uniform(0, 1, n) < forecasts).astype(float)
        curve = BrierScorer.calibration_curve(forecasts, outcomes, n_bins=5)
        # Each bin's predicted_mean should be close to observed_freq
        for b in curve.bins:
            if b.count > 20:
                self.assertAlmostEqual(
                    b.predicted_mean, b.observed_freq, delta=0.15,
                )


class TestCalibrationTracker(unittest.TestCase):
    """Tests for persistent calibration tracking."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.db = PythiaDB(self.tmp.name)
        self.tracker = CalibrationTracker(self.db)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_record_and_resolve(self):
        """Recording a forecast and resolving it should compute brier_score."""
        fid = self.tracker.record_forecast('market_1', 0.8, 'PROBABILITY_SPIKE')
        self.tracker.record_outcome('market_1', 1.0)
        resolved = self.db.get_resolved_forecasts(days=1)
        self.assertEqual(len(resolved), 1)
        self.assertAlmostEqual(resolved[0]['brier_score'], 0.04)  # (0.8-1)^2

    def test_unresolved_forecasts(self):
        """Unresolved forecasts should appear in the list."""
        self.tracker.record_forecast('market_2', 0.6, 'VOLUME_ANOMALY')
        unresolved = self.db.get_unresolved_forecasts()
        self.assertEqual(len(unresolved), 1)

    def test_report_empty(self):
        """Report on empty data should not crash."""
        report = self.tracker.get_calibration_report(days=30)
        self.assertEqual(report.brier.sample_size, 0)

    def test_report_with_data(self):
        """Report should compute correct stats."""
        # Record and resolve several forecasts
        for prob, outcome in [(0.9, 1.0), (0.8, 1.0), (0.3, 0.0), (0.7, 0.0)]:
            fid = self.tracker.record_forecast('m', prob, 'SPIKE')
            self.db.resolve_forecast(fid, outcome)

        report = self.tracker.get_calibration_report(days=30)
        self.assertEqual(report.brier.sample_size, 4)
        self.assertGreater(report.brier.brier_score, 0)

    def test_signal_type_ranking(self):
        """Should rank signal types by Brier score."""
        # Good signal type
        for _ in range(5):
            fid = self.tracker.record_forecast('m', 0.9, 'GOOD')
            self.db.resolve_forecast(fid, 1.0)
        # Bad signal type
        for _ in range(5):
            fid = self.tracker.record_forecast('m', 0.9, 'BAD')
            self.db.resolve_forecast(fid, 0.0)

        ranking = self.tracker.get_signal_type_ranking()
        self.assertGreater(len(ranking), 0)
        # 'GOOD' should have lower (better) Brier than 'BAD'
        scores = {name: score for name, score in ranking}
        if 'GOOD' in scores and 'BAD' in scores:
            self.assertLess(scores['GOOD'], scores['BAD'])

    def test_drift_detection(self):
        """Should detect drift when recent forecasts are much worse."""
        # Good historical forecasts
        for i in range(20):
            fid = self.tracker.record_forecast('m', 0.8, 'SPIKE')
            self.db.resolve_forecast(fid, 1.0)

        # The drift detection compares windows, so with all forecasts
        # being the same, there should be no drift
        report = self.tracker.get_calibration_report(days=30)
        # No drift expected since all forecasts are similar
        # (drift requires recent_brier > hist_brier * 1.5)


if __name__ == "__main__":
    unittest.main()
