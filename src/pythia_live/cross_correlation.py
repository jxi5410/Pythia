"""
Cross-Correlation Engine — Statistical correlation replacing keyword matching.

Computes Spearman rank correlations on actual price series, detects
correlation breakdowns via Fisher z-test, and provides SVD-based
factor model for market clustering.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as sp_stats

from .database import PythiaDB

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #

@dataclass
class CorrelatedPair:
    """A statistically correlated market pair."""
    market_id_a: str
    market_id_b: str
    spearman_rho: float
    p_value: float
    n_observations: int
    rolling_corr_7d: float = 0.0


@dataclass
class CorrelationMatrix:
    """Full pairwise correlation matrix."""
    market_ids: List[str]
    spearman_matrix: np.ndarray
    p_value_matrix: np.ndarray


@dataclass
class CorrelationBreakdown:
    """Detected correlation regime change."""
    market_id_a: str
    market_id_b: str
    historical_corr: float
    recent_corr: float
    z_score: float
    description: str


@dataclass
class FactorModel:
    """SVD-based factor decomposition."""
    n_factors: int
    factor_loadings: np.ndarray    # (n_markets, n_factors)
    explained_variance: List[float]
    market_ids: List[str]
    factor_names: List[str]        # named by top-loading markets


# ------------------------------------------------------------------ #
# Cross-Correlation Engine
# ------------------------------------------------------------------ #

class CrossCorrelationEngine:
    """
    Statistical correlation engine using Spearman rank correlation
    on actual price series.
    """

    def __init__(self, db: PythiaDB, min_observations: int = 20):
        self.db = db
        self.min_observations = min_observations
        self._cache: Dict[Tuple[str, str], CorrelatedPair] = {}

    def compute_correlation_matrix(self, market_ids: List[str],
                                    hours: int = 168) -> Optional[CorrelationMatrix]:
        """
        Compute Spearman correlation matrix from hourly-resampled prices.

        Args:
            market_ids: List of market IDs to correlate.
            hours: Lookback window.

        Returns:
            CorrelationMatrix or None if insufficient data.
        """
        if len(market_ids) < 2:
            return None

        # Fetch price series for all markets
        price_series = {}
        for mid in market_ids:
            df = self.db.get_returns_series(mid, hours=hours)
            if len(df) >= self.min_observations:
                price_series[mid] = df['yes_price'].values

        valid_ids = list(price_series.keys())
        if len(valid_ids) < 2:
            return None

        # Align series to common length (truncate to shortest)
        min_len = min(len(s) for s in price_series.values())
        if min_len < self.min_observations:
            return None

        n = len(valid_ids)
        rho_matrix = np.eye(n)
        p_matrix = np.zeros((n, n))

        for i in range(n):
            for j in range(i + 1, n):
                series_a = price_series[valid_ids[i]][-min_len:]
                series_b = price_series[valid_ids[j]][-min_len:]

                rho, pval = sp_stats.spearmanr(series_a, series_b)
                rho_matrix[i, j] = rho_matrix[j, i] = float(rho)
                p_matrix[i, j] = p_matrix[j, i] = float(pval)

        return CorrelationMatrix(
            market_ids=valid_ids,
            spearman_matrix=rho_matrix,
            p_value_matrix=p_matrix,
        )

    def find_statistically_correlated(self, market_id: str,
                                       min_correlation: float = 0.3,
                                       max_pvalue: float = 0.05,
                                       hours: int = 168) -> List[CorrelatedPair]:
        """
        Find markets statistically correlated with the given market.

        Replaces keyword overlap with actual Spearman correlation.
        """
        target_df = self.db.get_returns_series(market_id, hours=hours)
        if len(target_df) < self.min_observations:
            return []

        target_prices = target_df['yes_price'].values

        # Get all markets with enough price data
        all_markets = self.db.get_liquid_markets()
        if all_markets.empty:
            return []

        results = []
        for _, market in all_markets.iterrows():
            other_id = market['id']
            if other_id == market_id:
                continue

            other_df = self.db.get_returns_series(other_id, hours=hours)
            if len(other_df) < self.min_observations:
                continue

            other_prices = other_df['yes_price'].values
            common_len = min(len(target_prices), len(other_prices))
            if common_len < self.min_observations:
                continue

            a = target_prices[-common_len:]
            b = other_prices[-common_len:]

            rho, pval = sp_stats.spearmanr(a, b)

            if abs(rho) >= min_correlation and pval <= max_pvalue:
                # Compute rolling 7d correlation
                rolling_len = min(common_len, 168)  # 7 days hourly
                if rolling_len >= self.min_observations:
                    rolling_rho, _ = sp_stats.spearmanr(
                        a[-rolling_len:], b[-rolling_len:]
                    )
                else:
                    rolling_rho = rho

                pair = CorrelatedPair(
                    market_id_a=market_id,
                    market_id_b=other_id,
                    spearman_rho=float(rho),
                    p_value=float(pval),
                    n_observations=common_len,
                    rolling_corr_7d=float(rolling_rho),
                )
                results.append(pair)

                # Cache and persist
                self._cache[(market_id, other_id)] = pair
                self.db.save_correlation({
                    'market_id_a': market_id,
                    'market_id_b': other_id,
                    'spearman_rho': float(rho),
                    'p_value': float(pval),
                    'rolling_corr_7d': float(rolling_rho),
                    'n_observations': common_len,
                })

        results.sort(key=lambda p: abs(p.spearman_rho), reverse=True)
        return results

    def detect_correlation_breaks(self, market_id: str,
                                   correlated_ids: List[str],
                                   hours: int = 168,
                                   recent_hours: int = 24) -> List[CorrelationBreakdown]:
        """
        Detect correlation regime changes using Fisher z-test.

        Compares full-window correlation to recent-window correlation.
        """
        breakdowns = []
        target_df = self.db.get_returns_series(market_id, hours=hours)
        if len(target_df) < self.min_observations:
            return breakdowns

        target_prices = target_df['yes_price'].values

        for other_id in correlated_ids:
            other_df = self.db.get_returns_series(other_id, hours=hours)
            if len(other_df) < self.min_observations:
                continue

            other_prices = other_df['yes_price'].values
            common_len = min(len(target_prices), len(other_prices))
            if common_len < self.min_observations * 2:
                continue

            a_full = target_prices[-common_len:]
            b_full = other_prices[-common_len:]
            rho_full, _ = sp_stats.spearmanr(a_full, b_full)

            # Recent window
            recent_len = min(common_len, recent_hours)
            if recent_len < 10:
                continue
            a_recent = target_prices[-recent_len:]
            b_recent = other_prices[-recent_len:]
            rho_recent, _ = sp_stats.spearmanr(a_recent, b_recent)

            # Fisher z-test for difference in correlations
            z_score = self._fisher_z_test(
                rho_full, common_len, rho_recent, recent_len
            )

            if abs(z_score) > 2.0:  # Significant at ~95%
                breakdowns.append(CorrelationBreakdown(
                    market_id_a=market_id,
                    market_id_b=other_id,
                    historical_corr=float(rho_full),
                    recent_corr=float(rho_recent),
                    z_score=float(z_score),
                    description=(
                        f"Correlation shifted from {rho_full:.2f} to {rho_recent:.2f} "
                        f"(z={z_score:.1f})"
                    ),
                ))

        return breakdowns

    def tail_dependence_estimate(self, returns_a: np.ndarray,
                                  returns_b: np.ndarray,
                                  quantile: float = 0.05) -> float:
        """
        Empirical tail dependence coefficient.

        P(Y > F_Y^{-1}(1-q) | X > F_X^{-1}(1-q))

        Measures whether extreme events in both series co-occur.
        """
        if len(returns_a) < 20 or len(returns_b) < 20:
            return 0.0

        n = min(len(returns_a), len(returns_b))
        a = returns_a[-n:]
        b = returns_b[-n:]

        threshold_a = np.percentile(a, (1 - quantile) * 100)
        threshold_b = np.percentile(b, (1 - quantile) * 100)

        both_extreme = np.sum((a > threshold_a) & (b > threshold_b))
        a_extreme = np.sum(a > threshold_a)

        if a_extreme == 0:
            return 0.0

        return float(both_extreme / a_extreme)

    def compute_factor_exposures(self, market_ids: List[str],
                                  hours: int = 168,
                                  n_factors: int = 3) -> Optional[FactorModel]:
        """
        SVD-based factor model — identifies common factors driving markets.

        Uses numpy.linalg.svd (no sklearn needed).
        """
        # Build returns matrix
        returns_dict = {}
        for mid in market_ids:
            df = self.db.get_returns_series(mid, hours=hours)
            if len(df) >= self.min_observations and 'returns' in df.columns:
                returns_dict[mid] = df['returns'].values

        valid_ids = list(returns_dict.keys())
        if len(valid_ids) < 3:
            return None

        # Align to common length
        min_len = min(len(r) for r in returns_dict.values())
        if min_len < self.min_observations:
            return None

        # Build matrix (n_observations x n_markets)
        matrix = np.column_stack([
            returns_dict[mid][-min_len:] for mid in valid_ids
        ])

        # Standardize
        means = matrix.mean(axis=0)
        stds = matrix.std(axis=0)
        stds[stds == 0] = 1
        standardized = (matrix - means) / stds

        # SVD
        U, S, Vt = np.linalg.svd(standardized, full_matrices=False)

        n_factors = min(n_factors, len(valid_ids))
        loadings = Vt[:n_factors, :].T  # (n_markets, n_factors)

        # Explained variance
        total_var = np.sum(S ** 2)
        explained = [(S[i] ** 2 / total_var) for i in range(n_factors)]

        # Name factors by top-loading market
        factor_names = []
        for f in range(n_factors):
            top_idx = np.argmax(np.abs(loadings[:, f]))
            factor_names.append(f"Factor_{f+1}_{valid_ids[top_idx][:15]}")

        return FactorModel(
            n_factors=n_factors,
            factor_loadings=loadings,
            explained_variance=explained,
            market_ids=valid_ids,
            factor_names=factor_names,
        )

    def get_correlation_cluster(self, market_id: str,
                                 min_correlation: float = 0.5) -> List[str]:
        """
        Simple agglomerative clustering: group markets with corr > threshold.
        """
        cached = self.db.get_correlations(market_id, min_abs_corr=min_correlation)
        cluster = set()
        for pair in cached:
            if pair['market_id_a'] == market_id:
                cluster.add(pair['market_id_b'])
            else:
                cluster.add(pair['market_id_a'])
        return list(cluster)

    @staticmethod
    def _fisher_z_test(r1: float, n1: int, r2: float, n2: int) -> float:
        """
        Fisher z-test for the difference between two correlations.

        Returns z-score. |z| > 1.96 is significant at 95%.
        """
        # Clip to avoid arctanh singularity
        r1 = np.clip(r1, -0.999, 0.999)
        r2 = np.clip(r2, -0.999, 0.999)

        z1 = np.arctanh(r1)
        z2 = np.arctanh(r2)

        se = np.sqrt(1 / max(n1 - 3, 1) + 1 / max(n2 - 3, 1))
        if se == 0:
            return 0.0

        return float((z1 - z2) / se)
