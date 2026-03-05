#!/usr/bin/env python3
"""Tests for the EVT risk engine module."""

import sys
import unittest

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from pythia_live.risk_engine import (
    EVTRiskModel,
    GPDFit,
    PositionSizer,
    StressTestEngine,
    compute_portfolio_risk,
)


class TestEVTRiskModel(unittest.TestCase):
    """Tests for GPD fitting and VaR/ES computation."""

    def _make_fat_tailed_returns(self, n=500, seed=42):
        """Generate fat-tailed returns from Student-t distribution."""
        rng = np.random.default_rng(seed)
        return rng.standard_t(df=3, size=n) * 0.02

    def test_fit_tail(self):
        """GPD should fit without error on fat-tailed data."""
        model = EVTRiskModel()
        returns = self._make_fat_tailed_returns()
        fit = model.fit_tail(returns)
        self.assertIsInstance(fit, GPDFit)
        self.assertGreater(fit.n_exceedances, 0)
        self.assertGreater(fit.n_total, 0)

    def test_fat_tail_detection(self):
        """Student-t(3) should be detected as fat-tailed (shape > 0)."""
        model = EVTRiskModel()
        returns = self._make_fat_tailed_returns(n=1000)
        fit = model.fit_tail(returns)
        self.assertTrue(fit.is_fat_tailed)

    def test_var_less_than_es(self):
        """Expected Shortfall should always be >= VaR."""
        model = EVTRiskModel()
        returns = self._make_fat_tailed_returns()
        model.fit_tail(returns)
        var_99 = model.var(0.99)
        es_99 = model.expected_shortfall(0.99)
        self.assertGreaterEqual(es_99, var_99)

    def test_var_ordering(self):
        """VaR at 99% should be >= VaR at 95%."""
        model = EVTRiskModel()
        returns = self._make_fat_tailed_returns()
        model.fit_tail(returns)
        var_95 = model.var(0.95)
        var_99 = model.var(0.99)
        self.assertGreaterEqual(var_99, var_95)

    def test_var_positive(self):
        """VaR should be positive (loss measure)."""
        model = EVTRiskModel()
        returns = self._make_fat_tailed_returns()
        model.fit_tail(returns)
        self.assertGreater(model.var(0.95), 0)

    def test_is_tail_event(self):
        """Very negative return should be identified as tail event."""
        model = EVTRiskModel()
        returns = self._make_fat_tailed_returns()
        model.fit_tail(returns)
        # A return of -0.20 (20% loss) should be a tail event
        self.assertTrue(model.is_tail_event(-0.20))

    def test_not_tail_event(self):
        """Small return should not be a tail event."""
        model = EVTRiskModel()
        returns = self._make_fat_tailed_returns()
        model.fit_tail(returns)
        self.assertFalse(model.is_tail_event(-0.001))

    def test_few_exceedances(self):
        """Should handle case with very few tail observations."""
        model = EVTRiskModel()
        returns = np.random.default_rng(42).normal(0, 0.01, 20)
        fit = model.fit_tail(returns)
        self.assertIsNotNone(fit)

    def test_var_without_fit_raises(self):
        """Calling VaR before fit should raise."""
        model = EVTRiskModel()
        with self.assertRaises(ValueError):
            model.var(0.99)


class TestPositionSizer(unittest.TestCase):
    """Tests for EVT-aware position sizing."""

    def test_kelly_basic(self):
        """Should return positive size for positive edge."""
        sizer = PositionSizer()
        size = sizer.kelly_with_evt(edge=0.05, win_prob=0.6, capital=10000)
        self.assertGreater(size, 0)
        self.assertLess(size, 10000)

    def test_kelly_zero_edge(self):
        """Zero edge should return zero size."""
        sizer = PositionSizer()
        size = sizer.kelly_with_evt(edge=0, win_prob=0.5, capital=10000)
        self.assertEqual(size, 0)

    def test_fat_tail_reduces_size(self):
        """Fat tails should reduce position size vs thin tails."""
        # Thin-tailed model
        thin_model = EVTRiskModel()
        thin_returns = np.random.default_rng(42).normal(0, 0.01, 500)
        thin_model.fit_tail(thin_returns)
        thin_sizer = PositionSizer(thin_model)

        # Fat-tailed model
        fat_model = EVTRiskModel()
        fat_returns = np.random.default_rng(42).standard_t(df=2, size=500) * 0.02
        fat_model.fit_tail(fat_returns)
        fat_sizer = PositionSizer(fat_model)

        thin_size = thin_sizer.kelly_with_evt(0.05, 0.6, 10000)
        fat_size = fat_sizer.kelly_with_evt(0.05, 0.6, 10000)

        self.assertGreater(thin_size, fat_size)

    def test_size_position_respects_exposure(self):
        """Should not exceed available capital minus exposure."""
        sizer = PositionSizer()
        signal = {'expected_return': 0.10, 'severity': 'CRITICAL'}
        size = sizer.size_position(signal, capital=10000, existing_exposure=7500)
        self.assertLessEqual(size, 10000 * 0.8 - 7500)

    def test_size_position_full_exposure_zero(self):
        """Should return 0 when fully exposed."""
        sizer = PositionSizer()
        signal = {'expected_return': 0.10, 'severity': 'CRITICAL'}
        size = sizer.size_position(signal, capital=10000, existing_exposure=8500)
        self.assertEqual(size, 0)


class TestStressTestEngine(unittest.TestCase):
    """Tests for stress testing."""

    def _sample_positions(self):
        return [
            {'market_id': 'A', 'side': 'yes', 'entry_price': 0.5,
             'position_size': 1000, 'market_title': 'Market A'},
            {'market_id': 'B', 'side': 'yes', 'entry_price': 0.7,
             'position_size': 2000, 'market_title': 'Market B'},
            {'market_id': 'C', 'side': 'no', 'entry_price': 0.3,
             'position_size': 500, 'market_title': 'Market C'},
        ]

    def test_run_scenario(self):
        """Should compute loss from shocks."""
        engine = StressTestEngine()
        positions = self._sample_positions()
        scenario = {
            'name': 'Test shock',
            'shocks': {'A': 0.5, 'B': 0.3},
            'probability': 0.05,
        }
        result = engine.run_scenario(positions, scenario)
        self.assertEqual(result.scenario_name, 'Test shock')
        self.assertGreater(result.portfolio_loss, 0)

    def test_reverse_stress(self):
        """Should enumerate at least 2 scenarios."""
        engine = StressTestEngine()
        positions = self._sample_positions()
        scenarios = engine.reverse_stress(positions, loss_threshold=500)
        self.assertGreaterEqual(len(scenarios), 2)

    def test_reverse_stress_empty(self):
        """Empty positions should return empty."""
        engine = StressTestEngine()
        scenarios = engine.reverse_stress([], loss_threshold=500)
        self.assertEqual(len(scenarios), 0)

    def test_all_against_scenario(self):
        """All-against scenario should have total loss = sum of sizes."""
        engine = StressTestEngine()
        positions = self._sample_positions()
        scenarios = engine.reverse_stress(positions, loss_threshold=0)
        all_against = scenarios[0]
        expected_loss = sum(p['position_size'] for p in positions)
        self.assertAlmostEqual(all_against.portfolio_loss, expected_loss)


class TestPortfolioRisk(unittest.TestCase):
    """Tests for portfolio-level risk computation."""

    def test_empty_portfolio(self):
        """Empty portfolio should have zero risk."""
        risk = compute_portfolio_risk([], {})
        self.assertEqual(risk.var_95, 0)
        self.assertEqual(risk.expected_shortfall_95, 0)

    def test_single_position(self):
        """Single position should have positive VaR."""
        positions = [{'market_id': 'A', 'position_size': 1000}]
        returns = {'A': np.random.default_rng(42).normal(0, 0.02, 100)}
        risk = compute_portfolio_risk(positions, returns)
        self.assertGreater(risk.var_95, 0)

    def test_concentration_single(self):
        """Single position should have concentration = 1.0."""
        positions = [{'market_id': 'A', 'position_size': 1000}]
        risk = compute_portfolio_risk(positions, {})
        self.assertAlmostEqual(risk.concentration_risk, 1.0)

    def test_concentration_two_equal(self):
        """Two equal positions should have concentration = 0.5."""
        positions = [
            {'market_id': 'A', 'position_size': 500},
            {'market_id': 'B', 'position_size': 500},
        ]
        risk = compute_portfolio_risk(positions, {})
        self.assertAlmostEqual(risk.concentration_risk, 0.5)


if __name__ == "__main__":
    unittest.main()
