#!/usr/bin/env python3
"""Tests for the cross-correlation engine module."""

import sys
import unittest

import numpy as np
from scipy import stats as sp_stats

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from pythia_live.cross_correlation import CrossCorrelationEngine


class TestSpearmanCorrelation(unittest.TestCase):
    """Tests for pairwise Spearman correlation."""

    def test_perfect_correlation(self):
        """Perfectly correlated series should have rho = 1.0."""
        a = np.linspace(0.1, 0.9, 50)
        b = a.copy()
        rho, pval = sp_stats.spearmanr(a, b)
        self.assertAlmostEqual(rho, 1.0)
        self.assertLess(pval, 0.01)

    def test_perfect_negative_correlation(self):
        """Perfectly inversely correlated series should have rho = -1.0."""
        a = np.linspace(0.1, 0.9, 50)
        b = 1.0 - a
        rho, pval = sp_stats.spearmanr(a, b)
        self.assertAlmostEqual(rho, -1.0)

    def test_uncorrelated(self):
        """Random independent series should have |rho| < 0.3 and p > 0.05."""
        rng = np.random.default_rng(42)
        a = rng.uniform(0, 1, 100)
        b = rng.uniform(0, 1, 100)
        rho, pval = sp_stats.spearmanr(a, b)
        self.assertLess(abs(rho), 0.3)
        self.assertGreater(pval, 0.05)


class TestFisherZTest(unittest.TestCase):
    """Tests for Fisher z-test for correlation difference."""

    def test_same_correlation(self):
        """Same correlations should have z ≈ 0."""
        z = CrossCorrelationEngine._fisher_z_test(0.7, 100, 0.7, 100)
        self.assertAlmostEqual(z, 0.0, delta=0.01)

    def test_different_correlations(self):
        """Very different correlations should have |z| > 2."""
        z = CrossCorrelationEngine._fisher_z_test(0.9, 100, 0.1, 100)
        self.assertGreater(abs(z), 2.0)

    def test_small_sample(self):
        """Small samples should produce smaller z (less significant)."""
        z_large = CrossCorrelationEngine._fisher_z_test(0.8, 200, 0.3, 200)
        z_small = CrossCorrelationEngine._fisher_z_test(0.8, 10, 0.3, 10)
        self.assertGreater(abs(z_large), abs(z_small))


class TestTailDependence(unittest.TestCase):
    """Tests for empirical tail dependence estimation."""

    def test_independent_series(self):
        """Independent series should have low tail dependence."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 1000)
        b = rng.normal(0, 1, 1000)
        engine = CrossCorrelationEngine.__new__(CrossCorrelationEngine)
        td = engine.tail_dependence_estimate(a, b, quantile=0.05)
        self.assertLess(td, 0.3)

    def test_dependent_series(self):
        """Correlated series should have higher tail dependence."""
        rng = np.random.default_rng(42)
        common = rng.normal(0, 1, 1000)
        a = common + rng.normal(0, 0.1, 1000)
        b = common + rng.normal(0, 0.1, 1000)
        engine = CrossCorrelationEngine.__new__(CrossCorrelationEngine)
        td = engine.tail_dependence_estimate(a, b, quantile=0.05)
        self.assertGreater(td, 0.3)

    def test_short_series(self):
        """Short series should return 0."""
        engine = CrossCorrelationEngine.__new__(CrossCorrelationEngine)
        td = engine.tail_dependence_estimate(
            np.array([1, 2, 3]), np.array([1, 2, 3]), quantile=0.05,
        )
        self.assertEqual(td, 0.0)


class TestFactorModel(unittest.TestCase):
    """Tests for SVD-based factor model."""

    def test_single_factor_recovery(self):
        """Markets driven by a single factor should show one dominant factor."""
        # This is a pure unit test of SVD, not using the DB-backed method
        rng = np.random.default_rng(42)
        n = 100
        factor = rng.normal(0, 1, n)
        # 5 markets all driven by same factor + noise
        matrix = np.column_stack([
            factor + rng.normal(0, 0.1, n) for _ in range(5)
        ])
        means = matrix.mean(axis=0)
        stds = matrix.std(axis=0)
        stds[stds == 0] = 1
        standardized = (matrix - means) / stds

        U, S, Vt = np.linalg.svd(standardized, full_matrices=False)
        total_var = np.sum(S ** 2)
        first_factor_var = S[0] ** 2 / total_var

        # First factor should explain most variance
        self.assertGreater(first_factor_var, 0.7)


class TestCorrelationCluster(unittest.TestCase):
    """Tests for agglomerative clustering."""

    def test_cluster_from_empty_cache(self):
        """Should return empty list with no cached correlations."""
        # Create minimal engine without DB
        import os
        import tempfile
        from pythia_live.database import PythiaDB
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        tmp.close()
        try:
            db = PythiaDB(tmp.name)
            engine = CrossCorrelationEngine(db)
            cluster = engine.get_correlation_cluster('nonexistent')
            self.assertEqual(cluster, [])
        finally:
            os.unlink(tmp.name)

    def test_cluster_with_saved_correlations(self):
        """Saved correlations should appear in cluster."""
        import os
        import tempfile
        from pythia_live.database import PythiaDB
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        tmp.close()
        try:
            db = PythiaDB(tmp.name)
            db.save_correlation({
                'market_id_a': 'A',
                'market_id_b': 'B',
                'spearman_rho': 0.8,
                'p_value': 0.001,
                'rolling_corr_7d': 0.75,
                'n_observations': 50,
            })
            engine = CrossCorrelationEngine(db)
            cluster = engine.get_correlation_cluster('A', min_correlation=0.5)
            self.assertIn('B', cluster)
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
