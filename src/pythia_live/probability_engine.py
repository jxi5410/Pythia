"""Probability and scenario engines for market signal detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
from scipy.stats import beta as beta_dist
from scipy.stats import norm

from .database import PythiaDB


_EPS = 1e-6


@dataclass
class ProbabilityModel:
    """Per-market beta model for bounded prices in [0, 1]."""

    alpha: float = 2.0
    beta_param: float = 2.0
    n_observations: int = 0

    def fit(self, price_history: List[float]) -> None:
        prices = np.asarray(price_history, dtype=float)
        if prices.size < 3:
            return
        prices = np.clip(prices, _EPS, 1.0 - _EPS)

        try:
            # bounded fit only; loc=0 and scale=1 keeps model stable
            a, b, _, _ = beta_dist.fit(prices, floc=0.0, fscale=1.0)
            if np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0:
                self.alpha = float(a)
                self.beta_param = float(b)
                self.n_observations = int(prices.size)
                return
        except Exception:
            pass

        # fallback: method of moments
        m = float(np.mean(prices))
        v = float(np.var(prices, ddof=1))
        max_v = max(_EPS, m * (1.0 - m) - _EPS)
        v = min(max(v, _EPS), max_v)
        common = m * (1.0 - m) / v - 1.0
        self.alpha = max(_EPS, m * common)
        self.beta_param = max(_EPS, (1.0 - m) * common)
        self.n_observations = int(prices.size)

    def anomaly_score(self, current_price: float) -> float:
        """Return high score when in either tail (near 0 or 1 under fitted model)."""
        x = float(np.clip(current_price, _EPS, 1.0 - _EPS))
        cdf = float(beta_dist.cdf(x, self.alpha, self.beta_param))
        return float(max(cdf, 1.0 - cdf))

    def credible_interval(self, alpha: float = 0.05) -> tuple[float, float]:
        lo, hi = beta_dist.interval(1.0 - alpha, self.alpha, self.beta_param)
        return float(lo), float(hi)

    def update(self, new_price: float) -> None:
        # Fractional pseudo-count update for bounded observations.
        x = float(np.clip(new_price, _EPS, 1.0 - _EPS))
        self.alpha += x
        self.beta_param += 1.0 - x
        self.n_observations += 1

    @property
    def mean(self) -> float:
        denom = self.alpha + self.beta_param
        return float(self.alpha / denom) if denom > 0 else 0.5


@dataclass
class JumpDiffusionSimulator:
    """Merton-style jump diffusion path simulator in probability space."""

    mu: float = 0.0
    sigma: float = 0.05
    jump_intensity: float = 0.1
    jump_mean: float = 0.0
    jump_std: float = 0.05

    def calibrate(self, price_history: List[float]) -> None:
        prices = np.asarray(price_history, dtype=float)
        prices = np.clip(prices, _EPS, 1.0 - _EPS)
        if prices.size < 5:
            return
        rets = np.diff(np.log(prices))
        if rets.size < 3:
            return

        self.mu = float(np.mean(rets))
        self.sigma = float(max(np.std(rets, ddof=1), 1e-4))

        cutoff = 2.0 * self.sigma
        jump_rets = rets[np.abs(rets - self.mu) > cutoff]
        if jump_rets.size > 0:
            self.jump_intensity = float(jump_rets.size / rets.size)
            self.jump_mean = float(np.mean(jump_rets))
            self.jump_std = float(max(np.std(jump_rets, ddof=1), 1e-4)) if jump_rets.size > 1 else 1e-4

    def simulate_paths(
        self,
        current_price: float,
        dt: float,
        n_steps: int,
        n_paths: int = 1000,
        seed: Optional[int] = 42,
    ) -> np.ndarray:
        rng = np.random.default_rng(seed)
        s0 = float(np.clip(current_price, _EPS, 1.0 - _EPS))
        paths = np.zeros((n_paths, n_steps + 1), dtype=float)
        paths[:, 0] = s0

        for step in range(1, n_steps + 1):
            prev = np.clip(paths[:, step - 1], _EPS, 1.0 - _EPS)
            d_w = rng.normal(0.0, np.sqrt(dt), size=n_paths)
            jump_counts = rng.poisson(self.jump_intensity * dt, size=n_paths)
            jump_sizes = np.where(
                jump_counts > 0,
                rng.lognormal(mean=self.jump_mean, sigma=max(self.jump_std, 1e-6), size=n_paths) - 1.0,
                0.0,
            )
            drift = (self.mu - 0.5 * self.sigma * self.sigma) * dt
            diff = self.sigma * d_w
            next_prices = prev * np.exp(drift + diff) * (1.0 + jump_sizes)
            paths[:, step] = np.clip(next_prices, 0.0, 1.0)

        return paths


@dataclass
class EnsembleWeighter:
    estimates: List[Dict] = field(default_factory=list)

    def add_estimate(self, source: str, probability: float, confidence: float) -> None:
        p = float(np.clip(probability, 0.0, 1.0))
        c = float(np.clip(confidence, 1e-6, 1.0))
        variance = max((1.0 - c) ** 2, 1e-6)
        self.estimates.append(
            {
                "source": source,
                "probability": p,
                "confidence": c,
                "variance": variance,
            }
        )

    def weighted_probability(self) -> float:
        if not self.estimates:
            return 0.5
        weights = np.array([1.0 / e["variance"] for e in self.estimates], dtype=float)
        probs = np.array([e["probability"] for e in self.estimates], dtype=float)
        return float(np.sum(weights * probs) / np.sum(weights))

    def disagreement_score(self) -> float:
        if len(self.estimates) < 2:
            return 0.0
        probs = np.array([e["probability"] for e in self.estimates], dtype=float)
        return float(np.std(probs, ddof=1))


class ProbabilityEngineManager:
    """Top-level manager that caches and evaluates per-market probability models."""

    def __init__(self, db: PythiaDB):
        self.db = db
        self.models: Dict[str, ProbabilityModel] = {}
        self.simulators: Dict[str, JumpDiffusionSimulator] = {}

    def get_or_create_model(self, market_id: str) -> ProbabilityModel:
        model = self.models.get(market_id)
        if model is not None:
            return model

        stored = self.db.get_probability_model(market_id)
        if stored:
            model = ProbabilityModel(
                alpha=stored.get("alpha", 2.0),
                beta_param=stored.get("beta_param", 2.0),
                n_observations=stored.get("n_observations", 0),
            )
        else:
            model = ProbabilityModel()

        self.models[market_id] = model
        if market_id not in self.simulators:
            self.simulators[market_id] = JumpDiffusionSimulator()
        return model

    def evaluate_signal(self, market_data: Dict, price_history) -> Dict:
        market_id = market_data["id"]
        model = self.get_or_create_model(market_id)
        current_price = float(market_data.get("yes_price", 0.5))

        if price_history is not None and len(price_history) >= 10 and "yes_price" in price_history:
            model.fit(price_history["yes_price"].astype(float).tolist())
        model.update(current_price)

        anomaly_score = model.anomaly_score(current_price)
        ci = model.credible_interval(alpha=0.05)

        p_tail = max(1e-6, 2.0 * (1.0 - anomaly_score))
        z_equiv = float(norm.isf(p_tail / 2.0))

        self.db.save_probability_model(
            market_id=market_id,
            alpha=model.alpha,
            beta_param=model.beta_param,
            n_observations=model.n_observations,
        )

        return {
            "anomaly_score": anomaly_score,
            "fitted_mean": model.mean,
            "credible_interval": ci,
            "z_score_equivalent": z_equiv,
            "is_anomalous": anomaly_score >= 0.90,
        }

    def simulate_scenarios(
        self,
        market_id: str,
        current_price: float,
        price_history,
        hours_ahead: int = 24,
    ) -> Dict:
        sim = self.simulators.setdefault(market_id, JumpDiffusionSimulator())
        if price_history is not None and len(price_history) >= 10 and "yes_price" in price_history:
            sim.calibrate(price_history["yes_price"].astype(float).tolist())

        n_steps = max(1, int(hours_ahead))
        paths = sim.simulate_paths(current_price, dt=1.0 / 24.0, n_steps=n_steps, n_paths=1000)
        terminal = paths[:, -1]

        return {
            "median_path": np.median(paths, axis=0).tolist(),
            "p5_path": np.quantile(paths, 0.05, axis=0).tolist(),
            "p95_path": np.quantile(paths, 0.95, axis=0).tolist(),
            "threshold_crossing": {
                "above_0_7": float(np.mean(terminal > 0.7)),
                "below_0_3": float(np.mean(terminal < 0.3)),
            },
        }
