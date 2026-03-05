#!/usr/bin/env python3
"""Tests for the probability engine module."""

import sys
import unittest

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from pythia_live.probability_engine import (
    ProbabilityModel,
    JumpDiffusionSimulator,
    EnsembleWeighter,
    ProbabilityEngineManager,
)


class TestProbabilityModel(unittest.TestCase):
    """Tests for Beta distribution model."""

    def test_fit_recovers_mean(self):
        """Fitting data centered around 0.6 should produce mean near 0.6."""
        rng = np.random.default_rng(42)
        prices = rng.beta(6, 4, size=200)  # mean = 6/10 = 0.6
        model = ProbabilityModel()
        model.fit(prices)
        self.assertAlmostEqual(model.mean, 0.6, delta=0.05)

    def test_anomaly_score_extreme_high(self):
        """Price at 0.99 on uniform-ish data should have high anomaly score."""
        prices = np.linspace(0.3, 0.7, 50)
        model = ProbabilityModel()
        model.fit(prices)
        score = model.anomaly_score(0.99)
        self.assertGreater(score, 0.95)

    def test_anomaly_score_extreme_low(self):
        """Price at 0.01 on uniform-ish data should have low anomaly score."""
        prices = np.linspace(0.3, 0.7, 50)
        model = ProbabilityModel()
        model.fit(prices)
        score = model.anomaly_score(0.01)
        self.assertLess(score, 0.05)

    def test_anomaly_score_typical(self):
        """Median price should have score near 0.5."""
        rng = np.random.default_rng(42)
        prices = rng.beta(5, 5, size=200)  # symmetric around 0.5
        model = ProbabilityModel()
        model.fit(prices)
        score = model.anomaly_score(0.5)
        self.assertAlmostEqual(score, 0.5, delta=0.15)

    def test_credible_interval(self):
        """95% CI should be within [0, 1]."""
        model = ProbabilityModel(alpha=5.0, beta_param=5.0)
        lower, upper = model.credible_interval(0.05)
        self.assertGreater(lower, 0)
        self.assertLess(upper, 1)
        self.assertLess(lower, upper)

    def test_conjugate_update(self):
        """Online update should change alpha/beta."""
        model = ProbabilityModel(alpha=2.0, beta_param=2.0)
        old_alpha = model.alpha
        model.update(0.8)
        self.assertGreater(model.alpha, old_alpha)
        self.assertEqual(model.n_observations, 1)

    def test_to_from_dict(self):
        """Round-trip serialization."""
        model = ProbabilityModel(alpha=3.5, beta_param=2.1)
        model._n_observations = 42
        d = model.to_dict()
        restored = ProbabilityModel.from_dict(d)
        self.assertAlmostEqual(restored.alpha, 3.5)
        self.assertAlmostEqual(restored.beta_param, 2.1)
        self.assertEqual(restored.n_observations, 42)

    def test_fit_degenerate_data(self):
        """Constant prices should not crash."""
        prices = np.full(20, 0.5)
        model = ProbabilityModel()
        result = model.fit(prices)
        self.assertIn('alpha', result)


class TestJumpDiffusionSimulator(unittest.TestCase):
    """Tests for Merton jump-diffusion simulator."""

    def test_paths_bounded(self):
        """All simulated paths should stay in [0.001, 0.999]."""
        sim = JumpDiffusionSimulator(mu=0.0, sigma=0.05)
        paths = sim.simulate_paths(0.5, dt=1/24, n_steps=24, n_paths=500)
        self.assertTrue(np.all(paths >= 0.001))
        self.assertTrue(np.all(paths <= 0.999))

    def test_paths_shape(self):
        """Output shape should be (n_paths, n_steps + 1)."""
        sim = JumpDiffusionSimulator()
        paths = sim.simulate_paths(0.5, dt=1/24, n_steps=10, n_paths=100)
        self.assertEqual(paths.shape, (100, 11))

    def test_paths_start_at_current(self):
        """First column should equal current price."""
        sim = JumpDiffusionSimulator()
        paths = sim.simulate_paths(0.7, n_paths=50)
        np.testing.assert_array_almost_equal(paths[:, 0], 0.7)

    def test_calibrate(self):
        """Calibrate should set mu and sigma from data."""
        rng = np.random.default_rng(42)
        prices = 0.5 + np.cumsum(rng.normal(0, 0.01, 100))
        prices = np.clip(prices, 0.01, 0.99)
        sim = JumpDiffusionSimulator()
        sim.calibrate(prices)
        self.assertNotEqual(sim.sigma, 0.02)  # Should have changed from default

    def test_calibrate_short_series(self):
        """Calibrate with too few points should not crash."""
        sim = JumpDiffusionSimulator()
        sim.calibrate(np.array([0.5, 0.6]))
        # Should remain at defaults
        self.assertEqual(sim.sigma, 0.02)


class TestEnsembleWeighter(unittest.TestCase):
    """Tests for inverse-variance ensemble weighting."""

    def test_single_estimate(self):
        """Single estimate should return that estimate."""
        ew = EnsembleWeighter()
        ew.add_estimate("model_a", 0.7, 0.9)
        self.assertAlmostEqual(ew.weighted_probability(), 0.7)

    def test_high_confidence_dominates(self):
        """Higher confidence estimate should dominate."""
        ew = EnsembleWeighter()
        ew.add_estimate("low_conf", 0.3, 0.1)
        ew.add_estimate("high_conf", 0.8, 0.95)
        result = ew.weighted_probability()
        self.assertGreater(result, 0.6)  # Closer to 0.8 than 0.3

    def test_equal_confidence(self):
        """Equal confidence should give simple average."""
        ew = EnsembleWeighter()
        ew.add_estimate("a", 0.4, 0.5)
        ew.add_estimate("b", 0.6, 0.5)
        result = ew.weighted_probability()
        self.assertAlmostEqual(result, 0.5, delta=0.01)

    def test_disagreement_score(self):
        """Disagreement should be high when estimates differ."""
        ew = EnsembleWeighter()
        ew.add_estimate("a", 0.2, 0.8)
        ew.add_estimate("b", 0.8, 0.8)
        self.assertGreater(ew.disagreement_score(), 0.2)

    def test_no_disagreement(self):
        """Disagreement should be zero with one estimate."""
        ew = EnsembleWeighter()
        ew.add_estimate("a", 0.5, 0.9)
        self.assertEqual(ew.disagreement_score(), 0.0)

    def test_empty_returns_half(self):
        """Empty weighter should return 0.5."""
        ew = EnsembleWeighter()
        self.assertEqual(ew.weighted_probability(), 0.5)


class TestProbabilityEngineManager(unittest.TestCase):
    """Tests for the top-level manager."""

    def test_evaluate_signal(self):
        """Should return AnomalyResult for sufficient data."""
        manager = ProbabilityEngineManager()
        rng = np.random.default_rng(42)
        prices = rng.beta(5, 5, size=50)
        market_data = {'id': 'test_market', 'yes_price': 0.95}
        result = manager.evaluate_signal(market_data, prices)
        self.assertIsNotNone(result)
        self.assertTrue(result.is_anomalous)  # 0.95 should be anomalous

    def test_evaluate_signal_insufficient_data(self):
        """Should return None for too little data."""
        manager = ProbabilityEngineManager()
        market_data = {'id': 'test_market', 'yes_price': 0.5}
        result = manager.evaluate_signal(market_data, np.array([0.5, 0.6]))
        self.assertIsNone(result)

    def test_simulate_scenarios(self):
        """Should return SimulationResult."""
        manager = ProbabilityEngineManager()
        rng = np.random.default_rng(42)
        prices = rng.beta(5, 5, size=50)
        result = manager.simulate_scenarios('test', 0.5, prices, hours_ahead=12)
        self.assertIsNotNone(result)
        self.assertEqual(result.n_paths, 1000)
        self.assertGreater(result.percentile_95, result.percentile_5)

    def test_model_caching(self):
        """Same market ID should return cached model."""
        manager = ProbabilityEngineManager()
        model_a = manager.get_or_create_model('market_1')
        model_b = manager.get_or_create_model('market_1')
        self.assertIs(model_a, model_b)

    def test_different_markets(self):
        """Different market IDs should return different models."""
        manager = ProbabilityEngineManager()
        model_a = manager.get_or_create_model('market_1')
        model_b = manager.get_or_create_model('market_2')
        self.assertIsNot(model_a, model_b)


if __name__ == "__main__":
    unittest.main()
