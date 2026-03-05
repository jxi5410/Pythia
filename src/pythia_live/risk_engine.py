"""Risk engines for EVT tail modeling and position sizing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
from scipy.stats import genpareto

from .regime import HISTORICAL_REGIME_OUTCOMES


@dataclass
class EVTRiskModel:
    """Peaks-over-threshold EVT risk model over loss tail."""

    threshold_percentile: float = 0.90
    threshold: float = 0.0
    shape: float = 0.0
    scale: float = 1e-6
    n_total: int = 0
    n_exceedances: int = 0

    def fit_tail(self, returns: List[float], threshold_percentile: float = 0.90) -> None:
        arr = np.asarray(returns, dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size < 20:
            return

        losses = -arr
        self.threshold_percentile = threshold_percentile
        self.threshold = float(np.quantile(losses, threshold_percentile))

        exceedances = losses[losses > self.threshold] - self.threshold
        self.n_total = int(losses.size)
        self.n_exceedances = int(exceedances.size)
        if exceedances.size < 10:
            self.shape = 0.0
            self.scale = float(max(np.std(exceedances), 1e-6))
            return

        c, _, scale = genpareto.fit(exceedances, floc=0.0)
        self.shape = float(c)
        self.scale = float(max(scale, 1e-6))

    def var(self, confidence: float = 0.99) -> float:
        if self.n_total == 0 or self.n_exceedances == 0:
            return 0.0

        q = float(confidence)
        n = float(self.n_total)
        nu = float(self.n_exceedances)
        p_exceed = max(1e-9, n / nu * (1.0 - q))

        xi = self.shape
        beta = self.scale
        u = self.threshold

        if abs(xi) < 1e-8:
            return float(u + beta * np.log(1.0 / p_exceed))
        return float(u + (beta / xi) * ((p_exceed ** (-xi)) - 1.0))

    def expected_shortfall(self, confidence: float = 0.99) -> float:
        xi = self.shape
        if xi >= 1.0:
            return float("inf")

        var_q = self.var(confidence)
        if var_q <= 0:
            return 0.0

        beta = self.scale
        u = self.threshold
        return float((var_q + beta - xi * u) / max(1e-8, 1.0 - xi))

    def is_tail_event(self, return_value: float) -> bool:
        return float(-return_value) > self.threshold


class StressTestEngine:
    """Scenario and reverse stress testing."""

    def run_scenario(self, portfolio: List[Dict], scenario: Dict[str, float]) -> Dict:
        pnl = {}
        total = 0.0
        for pos in portfolio:
            mid = pos.get("market_id")
            shock = float(scenario.get(mid, scenario.get("default", 0.0)))
            pos_pnl = float(pos.get("position_size", 0.0)) * shock
            pnl[mid] = pos_pnl
            total += pos_pnl
        return {"position_pnl": pnl, "total_pnl": total}

    def reverse_stress(self, portfolio: List[Dict], loss_threshold: float) -> Dict:
        if not portfolio:
            return {"shock": 0.0, "total_pnl": 0.0, "breached": False}

        shock = -0.01
        while shock >= -1.0:
            total = sum(float(p.get("position_size", 0.0)) * shock for p in portfolio)
            if total <= -abs(loss_threshold):
                return {"shock": shock, "total_pnl": total, "breached": True}
            shock -= 0.01
        return {"shock": -1.0, "total_pnl": total, "breached": False}

    def regime_stress(self, portfolio: List[Dict], regime_state: str) -> Dict:
        scenario = HISTORICAL_REGIME_OUTCOMES.get(regime_state, {})
        if not scenario:
            return {"position_pnl": {}, "total_pnl": 0.0}

        default = float(scenario.get("avg_market_move", -0.03))
        mapped = {p.get("market_id"): default for p in portfolio}
        mapped["default"] = default
        return self.run_scenario(portfolio, mapped)


@dataclass
class LiquidityRisk:
    estimated_slippage: float
    time_to_exit_seconds: float
    depth_at_best: float


class PositionSizer:
    """Kelly-based sizing adjusted for tail risk and exposure."""

    def __init__(self, evt_model: Optional[EVTRiskModel] = None, max_position_pct: float = 0.25):
        self.evt_model = evt_model or EVTRiskModel()
        self.max_position_pct = max_position_pct

    def kelly_with_evt(self, edge: float, win_prob: float, capital: float) -> float:
        p = float(np.clip(win_prob, 1e-4, 1.0 - 1e-4))
        q = 1.0 - p
        b = max(edge, 1e-4)
        raw = max(0.0, (b * p - q) / b)

        es99 = self.evt_model.expected_shortfall(0.99)
        if not np.isfinite(es99):
            tail_mult = 0.1
        else:
            tail_mult = float(np.clip(1.0 - es99, 0.1, 1.0))

        frac = min(self.max_position_pct, raw * 0.5 * tail_mult)
        return float(max(0.0, frac * capital))

    def size_position(self, signal: Dict, capital: float, existing_exposure: float) -> float:
        edge = float(max(signal.get("expected_return", 0.0), 0.0))
        win_prob = float(signal.get("forecast_prob", 0.55))
        gross_size = self.kelly_with_evt(edge=edge, win_prob=win_prob, capital=capital)

        remaining = max(0.0, capital * 0.8 - existing_exposure)
        return float(min(gross_size, remaining))
