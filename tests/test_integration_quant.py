#!/usr/bin/env python3
"""Integration tests for the quant simulation layer."""

import os
import sys
import tempfile
import unittest
from datetime import datetime

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from pythia_live.database import PythiaDB
from pythia_live.probability_engine import ProbabilityEngineManager
from pythia_live.risk_engine import EVTRiskModel, PositionSizer
from pythia_live.calibration import CalibrationTracker, BrierScorer
from pythia_live.cross_correlation import CrossCorrelationEngine
from pythia_live.detector import Signal


class TestEndToEnd(unittest.TestCase):
    """End-to-end: price history -> fit -> detect -> size -> forecast -> resolve -> brier."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.db = PythiaDB(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_full_pipeline(self):
        """Run the full quant pipeline on synthetic data."""
        rng = np.random.default_rng(42)

        # 1. Generate synthetic price history
        prices = rng.beta(5, 5, size=100)

        # 2. Fit probability model
        manager = ProbabilityEngineManager(self.db)
        market_data = {'id': 'test_market', 'yes_price': 0.95}
        anomaly = manager.evaluate_signal(market_data, prices)
        self.assertIsNotNone(anomaly)
        self.assertTrue(anomaly.is_anomalous)  # 0.95 is extreme for Beta(5,5)

        # 3. Size position using EVT
        returns = np.diff(np.log(np.clip(prices, 0.01, 0.99)))
        evt = EVTRiskModel()
        evt.fit_tail(returns)
        sizer = PositionSizer(evt)
        signal = {'expected_return': 0.05, 'severity': 'HIGH'}
        size = sizer.size_position(signal, capital=10000, existing_exposure=0)
        self.assertGreater(size, 0)
        self.assertLess(size, 10000)

        # 4. Record forecast for calibration
        tracker = CalibrationTracker(self.db)
        fid = tracker.record_forecast('test_market', 0.95, 'PROBABILITY_SPIKE')

        # 5. Resolve forecast
        tracker.record_outcome('test_market', 1.0)

        # 6. Check Brier score
        report = tracker.get_calibration_report(days=1)
        self.assertEqual(report.brier.sample_size, 1)
        self.assertAlmostEqual(report.brier.brier_score, (0.95 - 1.0)**2, places=4)


class TestSignalBackwardCompat(unittest.TestCase):
    """Verify Signal dataclass is backward compatible."""

    def test_signal_without_probability_context(self):
        """Old-style Signal creation should still work."""
        signal = Signal(
            market_id='test',
            market_title='Test Market',
            timestamp=datetime.now(),
            signal_type='PROBABILITY_SPIKE',
            severity='HIGH',
            description='Test',
            old_price=0.5,
            new_price=0.6,
            expected_return=0.05,
            metadata={'test': True},
        )
        self.assertEqual(signal.probability_context, {})
        self.assertEqual(signal.correlated_markets, [])

    def test_signal_with_probability_context(self):
        """New-style Signal with probability_context should work."""
        signal = Signal(
            market_id='test',
            market_title='Test Market',
            timestamp=datetime.now(),
            signal_type='PROBABILITY_SPIKE',
            severity='HIGH',
            description='Test',
            old_price=0.5,
            new_price=0.6,
            expected_return=0.05,
            metadata={'test': True},
            probability_context={'anomaly_score': 0.99},
        )
        self.assertEqual(signal.probability_context['anomaly_score'], 0.99)


class TestFatTailPositionReduction(unittest.TestCase):
    """Paper trading positions should be smaller under fat-tailed regime."""

    def test_fat_vs_thin_sizing(self):
        """Fat-tailed returns should produce smaller positions."""
        rng = np.random.default_rng(42)

        # Thin tails (normal)
        thin_returns = rng.normal(0, 0.01, 500)
        thin_evt = EVTRiskModel()
        thin_evt.fit_tail(thin_returns)
        thin_sizer = PositionSizer(thin_evt)

        # Fat tails (Student-t df=2)
        fat_returns = rng.standard_t(df=2, size=500) * 0.01
        fat_evt = EVTRiskModel()
        fat_evt.fit_tail(fat_returns)
        fat_sizer = PositionSizer(fat_evt)

        signal = {'expected_return': 0.05, 'severity': 'HIGH'}
        thin_size = thin_sizer.size_position(signal, 10000, 0)
        fat_size = fat_sizer.size_position(signal, 10000, 0)

        self.assertGreater(thin_size, fat_size,
                           "Fat-tailed regime should produce smaller positions")


class TestCorrelationAdjustedConfluence(unittest.TestCase):
    """Correlation-adjusted confluence should reduce score for correlated layers."""

    def test_correlated_discount(self):
        """Correlated layers should produce lower effective layer count."""
        from pythia_live.confluence import ConfluenceScorer, Signal as CSignal
        from datetime import timezone

        # Without correlation clusters
        scorer_no_corr = ConfluenceScorer(min_layers=2)
        # With correlation clusters: equities and fixed_income are correlated
        scorer_with_corr = ConfluenceScorer(
            min_layers=2,
            correlation_clusters={'equities': ['fixed_income']},
        )

        now = datetime.now(timezone.utc)
        signals = [
            CSignal(layer='equities', direction='bullish', event_category='fed_rate',
                    confidence=0.8, timestamp=now, description='Test'),
            CSignal(layer='fixed_income', direction='bullish', event_category='fed_rate',
                    confidence=0.8, timestamp=now, description='Test'),
            CSignal(layer='twitter', direction='bullish', event_category='fed_rate',
                    confidence=0.8, timestamp=now, description='Test'),
        ]

        event_no_corr = scorer_no_corr.score(signals)
        event_with_corr = scorer_with_corr.score(signals)

        # Correlated version should have lower or equal score
        self.assertLessEqual(
            event_with_corr.confluence_score,
            event_no_corr.confluence_score,
        )


class TestDatabaseSchema(unittest.TestCase):
    """Verify new database tables are created correctly."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.db = PythiaDB(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_probability_models_table(self):
        """Should be able to save and retrieve probability models."""
        self.db.save_probability_model('test', {
            'alpha': 5.0, 'beta_param': 3.0, 'n_observations': 100,
        })
        model = self.db.get_probability_model('test')
        self.assertIsNotNone(model)
        self.assertAlmostEqual(model['alpha'], 5.0)

    def test_forecasts_table(self):
        """Should be able to save and resolve forecasts."""
        fid = self.db.save_forecast('m1', 0.7, 'SPIKE')
        self.db.resolve_forecast(fid, 1.0)
        resolved = self.db.get_resolved_forecasts(days=1)
        self.assertEqual(len(resolved), 1)
        self.assertAlmostEqual(resolved[0]['brier_score'], 0.09)

    def test_risk_snapshots_table(self):
        """Should be able to save risk snapshots."""
        self.db.save_risk_snapshot({
            'portfolio_var_95': 0.05,
            'portfolio_var_99': 0.08,
            'n_positions': 3,
        })
        # No crash = success

    def test_correlation_pairs_table(self):
        """Should be able to save and retrieve correlations."""
        self.db.save_correlation({
            'market_id_a': 'A', 'market_id_b': 'B',
            'spearman_rho': 0.75, 'p_value': 0.001,
            'rolling_corr_7d': 0.7, 'n_observations': 100,
        })
        pairs = self.db.get_correlations('A', min_abs_corr=0.5)
        self.assertEqual(len(pairs), 1)
        self.assertAlmostEqual(pairs[0]['spearman_rho'], 0.75)


if __name__ == "__main__":
    unittest.main()
