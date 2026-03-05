"""
EVT Risk Engine — Extreme Value Theory for tail risk management.

Replaces fixed-percentage stops with GPD-fitted VaR/Expected Shortfall,
stress testing, and EVT-aware position sizing.
"""

import json
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
class GPDFit:
    """Generalized Pareto Distribution fit result."""
    threshold: float
    shape_xi: float         # GPD shape (xi)
    scale_sigma: float      # GPD scale (sigma)
    n_exceedances: int
    n_total: int
    ks_pvalue: float        # Kolmogorov-Smirnov goodness of fit

    @property
    def is_fat_tailed(self) -> bool:
        """Shape > 0 indicates fat tails (Fréchet domain)."""
        return self.shape_xi > 0


@dataclass
class PortfolioRisk:
    """Portfolio-level risk metrics."""
    var_95: float
    var_99: float
    expected_shortfall_95: float
    expected_shortfall_99: float
    individual_vars: Dict[str, float] = field(default_factory=dict)
    concentration_risk: float = 0.0  # Herfindahl index


@dataclass
class StressScenario:
    """Result of a stress test scenario."""
    scenario_name: str
    portfolio_loss: float
    probability_estimate: float
    worst_positions: List[str] = field(default_factory=list)


@dataclass
class LiquidityRisk:
    """Liquidity risk assessment for a position."""
    market_id: str
    estimated_slippage_pct: float
    risk_adjusted_size: float


# ------------------------------------------------------------------ #
# EVT Risk Model
# ------------------------------------------------------------------ #

class EVTRiskModel:
    """
    Extreme Value Theory risk model using Peaks Over Threshold (POT).

    Fits a Generalized Pareto Distribution to loss exceedances above
    a high threshold (e.g., 90th percentile of absolute returns).
    """

    def __init__(self):
        self._fit: Optional[GPDFit] = None
        self._returns: Optional[np.ndarray] = None

    def fit_tail(self, returns: np.ndarray,
                 threshold_percentile: float = 0.90) -> GPDFit:
        """
        Fit GPD to tail exceedances.

        Args:
            returns: Array of return observations.
            threshold_percentile: Percentile for POT threshold.

        Returns:
            GPDFit with fitted parameters.
        """
        losses = -returns  # Work with losses (positive = bad)
        self._returns = returns

        threshold = float(np.percentile(losses, threshold_percentile * 100))
        exceedances = losses[losses > threshold] - threshold

        if len(exceedances) < 3:
            # Not enough data — use normal approximation
            self._fit = GPDFit(
                threshold=threshold,
                shape_xi=0.0,
                scale_sigma=float(np.std(losses)),
                n_exceedances=len(exceedances),
                n_total=len(returns),
                ks_pvalue=0.0,
            )
            return self._fit

        # Fit GPD using scipy
        shape, loc, scale = sp_stats.genpareto.fit(exceedances, floc=0)

        # KS test for goodness of fit
        ks_stat, ks_pvalue = sp_stats.kstest(
            exceedances, 'genpareto', args=(shape, 0, scale)
        )

        self._fit = GPDFit(
            threshold=threshold,
            shape_xi=float(shape),
            scale_sigma=float(scale),
            n_exceedances=len(exceedances),
            n_total=len(returns),
            ks_pvalue=float(ks_pvalue),
        )
        return self._fit

    def var(self, confidence: float = 0.99) -> float:
        """
        Value at Risk at given confidence level.

        VaR(q) = u + (sigma/xi) * [(n/N_u * (1-q))^(-xi) - 1]
        """
        if self._fit is None:
            raise ValueError("Must call fit_tail() first")

        f = self._fit
        if abs(f.shape_xi) < 1e-10:
            # Exponential tail (shape ≈ 0)
            return f.threshold + f.scale_sigma * np.log(
                f.n_total / f.n_exceedances * (1 - confidence)
            ) * (-1)

        n_ratio = f.n_total / max(f.n_exceedances, 1)
        var_val = f.threshold + (f.scale_sigma / f.shape_xi) * (
            (n_ratio * (1 - confidence)) ** (-f.shape_xi) - 1
        )
        return float(var_val)

    def expected_shortfall(self, confidence: float = 0.99) -> float:
        """
        Expected Shortfall (CVaR) — expected loss given VaR breach.

        ES(q) = VaR(q)/(1-xi) + (sigma - xi*u)/(1-xi)
        """
        if self._fit is None:
            raise ValueError("Must call fit_tail() first")

        f = self._fit
        var_val = self.var(confidence)

        if f.shape_xi >= 1.0:
            # ES is infinite for shape >= 1 — cap at 2x VaR
            return var_val * 2.0

        es_val = var_val / (1 - f.shape_xi) + (
            f.scale_sigma - f.shape_xi * f.threshold
        ) / (1 - f.shape_xi)
        return float(max(es_val, var_val))

    def is_tail_event(self, return_value: float) -> bool:
        """Check if a return constitutes a tail event."""
        if self._fit is None:
            return False
        return -return_value > self._fit.threshold


# ------------------------------------------------------------------ #
# Stress Testing
# ------------------------------------------------------------------ #

class StressTestEngine:
    """
    Stress testing connected to regime.py scenarios.

    Runs predefined scenarios (all-resolve-against, worst-3, correlated)
    against current portfolio positions.
    """

    def run_scenario(self, positions: List[Dict],
                     scenario: Dict) -> StressScenario:
        """
        Run a single stress scenario.

        Args:
            positions: List of {market_id, side, entry_price, position_size}.
            scenario: {name, shocks: {market_id: shock_pct}}.
        """
        total_loss = 0.0
        worst = []

        for pos in positions:
            market_id = pos.get('market_id', '')
            shock = scenario.get('shocks', {}).get(market_id, 0)
            if shock == 0:
                continue
            position_size = pos.get('position_size', 0)
            loss = position_size * shock
            total_loss += loss
            worst.append(market_id)

        return StressScenario(
            scenario_name=scenario.get('name', 'Unknown'),
            portfolio_loss=total_loss,
            probability_estimate=scenario.get('probability', 0.01),
            worst_positions=worst[:3],
        )

    def reverse_stress(self, positions: List[Dict],
                       loss_threshold: float) -> List[StressScenario]:
        """
        Find smallest shocks that produce losses exceeding threshold.

        Enumerates: all resolve against, worst N, individual.
        """
        scenarios = []

        if not positions:
            return scenarios

        # Scenario 1: All positions resolve against
        all_against_loss = sum(p.get('position_size', 0) for p in positions)
        scenarios.append(StressScenario(
            scenario_name="All positions resolve against",
            portfolio_loss=all_against_loss,
            probability_estimate=0.5 ** max(len(positions), 1),
            worst_positions=[p.get('market_id', '') for p in positions[:3]],
        ))

        # Scenario 2: Top 3 largest positions resolve against
        sorted_pos = sorted(positions, key=lambda p: p.get('position_size', 0), reverse=True)
        top3_loss = sum(p.get('position_size', 0) for p in sorted_pos[:3])
        scenarios.append(StressScenario(
            scenario_name="Top 3 positions resolve against",
            portfolio_loss=top3_loss,
            probability_estimate=0.5 ** min(3, len(positions)),
            worst_positions=[p.get('market_id', '') for p in sorted_pos[:3]],
        ))

        # Scenario 3: Each position individually
        for pos in sorted_pos[:5]:
            loss = pos.get('position_size', 0)
            if loss >= loss_threshold:
                scenarios.append(StressScenario(
                    scenario_name=f"Single position: {pos.get('market_id', '')[:20]}",
                    portfolio_loss=loss,
                    probability_estimate=0.5,
                    worst_positions=[pos.get('market_id', '')],
                ))

        return scenarios

    def regime_stress(self, positions: List[Dict],
                      regime_outcomes: Dict) -> StressScenario:
        """Apply historical regime outcomes as a stress scenario."""
        total_loss = 0.0
        affected = []

        for pos in positions:
            market_title = pos.get('market_title', '')
            for asset, outcome in regime_outcomes.items():
                if asset.lower() in market_title.lower():
                    move_pct = outcome.get('median_move_pct', 0) / 100
                    side = pos.get('side', 'yes')
                    # If we're long YES and market goes down, we lose
                    if side == 'yes' and move_pct < 0:
                        total_loss += pos.get('position_size', 0) * abs(move_pct)
                        affected.append(pos.get('market_id', ''))
                    elif side == 'no' and move_pct > 0:
                        total_loss += pos.get('position_size', 0) * abs(move_pct)
                        affected.append(pos.get('market_id', ''))

        return StressScenario(
            scenario_name="Historical regime stress",
            portfolio_loss=total_loss,
            probability_estimate=0.1,
            worst_positions=affected[:3],
        )


# ------------------------------------------------------------------ #
# Position Sizer
# ------------------------------------------------------------------ #

class PositionSizer:
    """
    EVT-aware position sizing that replaces fixed Kelly.

    Adjusts Kelly fraction downward when EVT detects fat tails
    and accounts for existing portfolio exposure.
    """

    def __init__(self, evt_model: Optional[EVTRiskModel] = None):
        self.evt_model = evt_model

    def kelly_with_evt(self, edge: float, win_prob: float,
                       capital: float) -> float:
        """
        Kelly Criterion adjusted for fat tails.

        Standard Kelly: f* = edge / odds = p - q/b
        EVT adjustment: reduce by tail heaviness factor.
        """
        if edge <= 0 or win_prob <= 0:
            return 0.0

        # For binary prediction markets: f* = edge / (q + edge)
        # where q = 1 - win_prob. This simplifies Kelly for binary outcomes.
        q = 1.0 - win_prob
        kelly_frac = edge / max(q + edge, 0.01)
        kelly_frac = min(kelly_frac, 0.25) * 0.5  # Half Kelly, capped at 25%

        # EVT tail adjustment
        if self.evt_model and self.evt_model._fit:
            xi = self.evt_model._fit.shape_xi
            if xi > 0:
                # Fat tails: reduce position proportionally
                tail_discount = 1.0 / (1.0 + xi * 2)
                kelly_frac *= tail_discount

        return kelly_frac * capital

    def size_position(self, signal: Dict, capital: float,
                      existing_exposure: float,
                      max_var_pct: float = 0.05) -> float:
        """
        Full position sizing considering Kelly, EVT, and portfolio limits.

        Args:
            signal: Signal dict with expected_return, severity.
            capital: Available capital.
            existing_exposure: Current total exposure.
            max_var_pct: Maximum portfolio VaR as % of capital.

        Returns:
            Recommended position size in dollars.
        """
        edge = signal.get('expected_return', 0.02)
        severity = signal.get('severity', 'MEDIUM')

        # Win probability estimate from severity
        win_prob_map = {'CRITICAL': 0.70, 'HIGH': 0.60, 'MEDIUM': 0.55, 'LOW': 0.52}
        win_prob = win_prob_map.get(severity, 0.55)

        # Kelly sizing
        raw_size = self.kelly_with_evt(edge, win_prob, capital)

        # Exposure limit: don't exceed 80% of capital
        available = max(0, capital * 0.8 - existing_exposure)
        size = min(raw_size, available)

        # VaR constraint
        if self.evt_model and self.evt_model._fit:
            try:
                var_limit = capital * max_var_pct
                current_var = self.evt_model.var(0.95)
                if current_var > 0:
                    max_size = var_limit / current_var * capital * 0.1
                    size = min(size, max_size)
            except (ValueError, ZeroDivisionError):
                pass

        return max(0, size)


# ------------------------------------------------------------------ #
# Portfolio-level risk
# ------------------------------------------------------------------ #

def compute_portfolio_risk(positions: List[Dict],
                           returns_by_market: Dict[str, np.ndarray],
                           ) -> PortfolioRisk:
    """
    Compute portfolio-level VaR and Expected Shortfall.

    Uses individual EVT models and position-weighted aggregation.
    """
    if not positions:
        return PortfolioRisk(
            var_95=0, var_99=0,
            expected_shortfall_95=0, expected_shortfall_99=0,
        )

    individual_vars = {}
    total_exposure = sum(p.get('position_size', 0) for p in positions)

    for pos in positions:
        mid = pos.get('market_id', '')
        returns = returns_by_market.get(mid, np.array([]))
        if len(returns) < 10:
            # Use simple volatility estimate
            var_95 = pos.get('position_size', 0) * 0.05
        else:
            model = EVTRiskModel()
            model.fit_tail(returns)
            try:
                var_95 = model.var(0.95) * pos.get('position_size', 0)
            except (ValueError, ZeroDivisionError):
                var_95 = pos.get('position_size', 0) * 0.05
        individual_vars[mid] = var_95

    # Naive aggregation (conservative — assumes no diversification)
    port_var_95 = sum(individual_vars.values())
    port_var_99 = port_var_95 * 1.5  # Approximate scaling

    # Herfindahl concentration
    if total_exposure > 0:
        weights = [p.get('position_size', 0) / total_exposure for p in positions]
        concentration = sum(w**2 for w in weights)
    else:
        concentration = 0

    return PortfolioRisk(
        var_95=port_var_95,
        var_99=port_var_99,
        expected_shortfall_95=port_var_95 * 1.2,
        expected_shortfall_99=port_var_99 * 1.2,
        individual_vars=individual_vars,
        concentration_risk=concentration,
    )
