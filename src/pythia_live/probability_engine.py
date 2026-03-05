"""
Probability Engine — Distribution-aware signal detection.

Replaces fixed thresholds with Beta distribution anomaly detection,
jump-diffusion simulation, and ensemble probability weighting.
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
class AnomalyResult:
    """Result of anomaly detection for a single price observation."""
    anomaly_score: float       # 0-1, how far into tails (0.5 = median)
    fitted_mean: float
    credible_interval: Tuple[float, float]  # (lower, upper)
    z_score_equivalent: float  # Normal-equivalent z-score
    is_anomalous: bool         # True if score > 0.95 or < 0.05


@dataclass
class SimulationResult:
    """Result of jump-diffusion forward simulation."""
    median_path: float         # median terminal price
    percentile_5: float
    percentile_95: float
    prob_above_threshold: float  # P(price > current + threshold)
    prob_below_threshold: float  # P(price < current - threshold)
    n_paths: int


# ------------------------------------------------------------------ #
# Beta distribution model per market
# ------------------------------------------------------------------ #

class ProbabilityModel:
    """
    Per-market Beta distribution fitted from price history.

    Prediction market prices are [0,1] bounded, making Beta the
    natural conjugate prior.
    """

    def __init__(self, alpha: float = 2.0, beta_param: float = 2.0):
        self.alpha = alpha
        self.beta_param = beta_param
        self._n_observations = 0

    def fit(self, price_history: np.ndarray) -> Dict:
        """
        Fit Beta distribution to historical prices.

        Clips prices to (0.001, 0.999) to avoid Beta edge singularities.
        """
        prices = np.clip(price_history, 0.001, 0.999)
        if len(prices) < 3:
            return {'alpha': self.alpha, 'beta_param': self.beta_param}

        # Method of moments fit (more stable than MLE for small samples)
        mean = np.mean(prices)
        var = np.var(prices)
        if var == 0 or var >= mean * (1 - mean):
            # Degenerate case — use weak prior
            self.alpha = 2.0
            self.beta_param = 2.0
        else:
            common = mean * (1 - mean) / var - 1
            self.alpha = max(0.5, mean * common)
            self.beta_param = max(0.5, (1 - mean) * common)

        self._n_observations = len(prices)
        return {'alpha': self.alpha, 'beta_param': self.beta_param}

    def anomaly_score(self, current_price: float) -> float:
        """
        CDF percentile of current price under fitted Beta.

        Near 0 or 1 = anomalous. Near 0.5 = typical.
        """
        price = np.clip(current_price, 0.001, 0.999)
        return float(sp_stats.beta.cdf(price, self.alpha, self.beta_param))

    def credible_interval(self, alpha_level: float = 0.05) -> Tuple[float, float]:
        """Bayesian credible interval at the given significance level."""
        lower = float(sp_stats.beta.ppf(alpha_level / 2, self.alpha, self.beta_param))
        upper = float(sp_stats.beta.ppf(1 - alpha_level / 2, self.alpha, self.beta_param))
        return (lower, upper)

    def update(self, new_price: float):
        """
        Online conjugate update.

        Treats price as a Bernoulli-like observation:
        prices > 0.5 increment alpha, prices < 0.5 increment beta.
        Scaled by distance from 0.5 for smoother updates.
        """
        price = np.clip(new_price, 0.001, 0.999)
        self.alpha += price
        self.beta_param += (1 - price)
        self._n_observations += 1

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta_param)

    @property
    def n_observations(self) -> int:
        return self._n_observations

    def to_dict(self) -> Dict:
        return {
            'alpha': self.alpha,
            'beta_param': self.beta_param,
            'n_observations': self._n_observations,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'ProbabilityModel':
        model = cls(alpha=d.get('alpha', 2.0), beta_param=d.get('beta_param', 2.0))
        model._n_observations = d.get('n_observations', 0)
        return model


# ------------------------------------------------------------------ #
# Jump-diffusion simulator
# ------------------------------------------------------------------ #

class JumpDiffusionSimulator:
    """
    Merton jump-diffusion model for forward price paths.

    dS = mu*S*dt + sigma*S*dW + J*S*dN
    where N is Poisson(lambda*dt), J ~ LogNormal(jump_mean, jump_std).
    """

    def __init__(self, mu: float = 0.0, sigma: float = 0.02,
                 jump_intensity: float = 0.1,
                 jump_mean: float = 0.0, jump_std: float = 0.05):
        self.mu = mu
        self.sigma = sigma
        self.jump_intensity = jump_intensity
        self.jump_mean = jump_mean
        self.jump_std = jump_std

    def calibrate(self, price_history: np.ndarray):
        """Calibrate parameters from historical price series."""
        if len(price_history) < 5:
            return

        prices = np.clip(price_history, 0.001, 0.999)
        log_returns = np.diff(np.log(prices))

        if len(log_returns) < 3:
            return

        self.mu = float(np.mean(log_returns))
        self.sigma = max(0.001, float(np.std(log_returns)))

        # Identify jumps: returns exceeding 2-sigma
        threshold = 2 * self.sigma
        jumps = log_returns[np.abs(log_returns) > threshold]

        if len(jumps) > 0:
            self.jump_intensity = max(0.01, len(jumps) / len(log_returns))
            self.jump_mean = float(np.mean(jumps))
            self.jump_std = max(0.001, float(np.std(jumps))) if len(jumps) > 1 else self.sigma
        else:
            self.jump_intensity = 0.01
            self.jump_mean = 0.0
            self.jump_std = self.sigma

    def simulate_paths(self, current_price: float, dt: float = 1/24,
                       n_steps: int = 24, n_paths: int = 1000) -> np.ndarray:
        """
        Simulate forward price paths.

        Args:
            current_price: Starting price.
            dt: Time step (in days). Default 1 hour.
            n_steps: Number of steps. Default 24 (1 day).
            n_paths: Number of Monte Carlo paths.

        Returns:
            Array of shape (n_paths, n_steps+1) with price paths.
        """
        rng = np.random.default_rng()
        paths = np.zeros((n_paths, n_steps + 1))
        paths[:, 0] = current_price

        for t in range(n_steps):
            # Diffusion
            dW = rng.normal(0, np.sqrt(dt), n_paths)
            diffusion = (self.mu - 0.5 * self.sigma**2) * dt + self.sigma * dW

            # Jumps (Poisson arrivals)
            n_jumps = rng.poisson(self.jump_intensity * dt, n_paths)
            jump_sizes = np.zeros(n_paths)
            has_jump = n_jumps > 0
            if has_jump.any():
                jump_sizes[has_jump] = rng.normal(
                    self.jump_mean, self.jump_std, has_jump.sum()
                )

            # Log price evolution
            log_price = np.log(np.clip(paths[:, t], 1e-10, None))
            log_price += diffusion + jump_sizes
            paths[:, t + 1] = np.exp(log_price)

            # Reflect into [0, 1] for prediction markets
            paths[:, t + 1] = np.clip(paths[:, t + 1], 0.001, 0.999)

        return paths

    def to_dict(self) -> Dict:
        return {
            'mu': self.mu,
            'sigma': self.sigma,
            'jump_intensity': self.jump_intensity,
            'jump_mean': self.jump_mean,
            'jump_std': self.jump_std,
        }


# ------------------------------------------------------------------ #
# Ensemble weighter
# ------------------------------------------------------------------ #

class EnsembleWeighter:
    """Combines probability estimates via inverse-variance weighting."""

    def __init__(self):
        self._estimates: List[Tuple[str, float, float]] = []  # (source, prob, confidence)

    def add_estimate(self, source: str, probability: float, confidence: float):
        """Add a probability estimate from a named source."""
        self._estimates.append((source, probability, max(confidence, 0.01)))

    def weighted_probability(self) -> float:
        """Inverse-variance weighted combination."""
        if not self._estimates:
            return 0.5

        # Variance proxy: (1 - confidence)^2
        weights = []
        probs = []
        for _, prob, conf in self._estimates:
            variance = (1 - conf) ** 2
            weight = 1.0 / max(variance, 1e-6)
            weights.append(weight)
            probs.append(prob)

        total_weight = sum(weights)
        if total_weight == 0:
            return float(np.mean(probs))

        return float(sum(w * p for w, p in zip(weights, probs)) / total_weight)

    def disagreement_score(self) -> float:
        """Spread across estimates — higher = more uncertainty."""
        if len(self._estimates) < 2:
            return 0.0
        probs = [e[1] for e in self._estimates]
        return float(np.std(probs))

    def clear(self):
        self._estimates.clear()


# ------------------------------------------------------------------ #
# Manager — top-level API
# ------------------------------------------------------------------ #

class ProbabilityEngineManager:
    """
    Maintains per-market probability models and provides
    the main evaluate_signal and simulate_scenarios APIs.
    """

    def __init__(self, db: Optional[PythiaDB] = None):
        self.db = db
        self._models: Dict[str, ProbabilityModel] = {}
        self._simulators: Dict[str, JumpDiffusionSimulator] = {}

    def get_or_create_model(self, market_id: str) -> ProbabilityModel:
        """Lazy initialization with DB caching."""
        if market_id in self._models:
            return self._models[market_id]

        # Try loading from DB
        if self.db:
            saved = self.db.get_probability_model(market_id)
            if saved:
                model = ProbabilityModel(
                    alpha=saved.get('alpha', 2.0),
                    beta_param=saved.get('beta_param', 2.0),
                )
                model._n_observations = saved.get('n_observations', 0)
                self._models[market_id] = model
                return model

        # Create new
        model = ProbabilityModel()
        self._models[market_id] = model
        return model

    def evaluate_signal(self, market_data: Dict,
                        price_history: np.ndarray) -> Optional[AnomalyResult]:
        """
        Evaluate whether current price is anomalous.

        Returns AnomalyResult with anomaly score, credible interval, etc.
        """
        market_id = market_data.get('id', '')
        current_price = market_data.get('yes_price', 0.5)

        if len(price_history) < 5:
            return None

        model = self.get_or_create_model(market_id)
        model.fit(price_history)

        score = model.anomaly_score(current_price)
        ci = model.credible_interval()
        fitted_mean = model.mean

        # Convert CDF score to z-score equivalent
        # score near 0 or 1 = extreme, convert to absolute z
        tail_prob = min(score, 1 - score)
        z_equiv = float(sp_stats.norm.ppf(1 - tail_prob)) if tail_prob > 1e-10 else 5.0

        is_anomalous = score > 0.95 or score < 0.05

        # Persist model
        if self.db:
            self.db.save_probability_model(market_id, {
                **model.to_dict(),
                **self._get_or_create_simulator(market_id).to_dict(),
            })

        return AnomalyResult(
            anomaly_score=score,
            fitted_mean=fitted_mean,
            credible_interval=ci,
            z_score_equivalent=z_equiv,
            is_anomalous=is_anomalous,
        )

    def simulate_scenarios(self, market_id: str, current_price: float,
                           price_history: np.ndarray,
                           hours_ahead: int = 24) -> Optional[SimulationResult]:
        """Run jump-diffusion simulation for forward scenarios."""
        if len(price_history) < 5:
            return None

        sim = self._get_or_create_simulator(market_id)
        sim.calibrate(price_history)

        paths = sim.simulate_paths(
            current_price=current_price,
            dt=1/24,
            n_steps=hours_ahead,
            n_paths=1000,
        )

        terminal = paths[:, -1]
        threshold = 0.05  # 5% move threshold

        return SimulationResult(
            median_path=float(np.median(terminal)),
            percentile_5=float(np.percentile(terminal, 5)),
            percentile_95=float(np.percentile(terminal, 95)),
            prob_above_threshold=float(np.mean(terminal > current_price + threshold)),
            prob_below_threshold=float(np.mean(terminal < current_price - threshold)),
            n_paths=1000,
        )

    def _get_or_create_simulator(self, market_id: str) -> JumpDiffusionSimulator:
        if market_id not in self._simulators:
            # Try loading from DB
            if self.db:
                saved = self.db.get_probability_model(market_id)
                if saved:
                    self._simulators[market_id] = JumpDiffusionSimulator(
                        mu=saved.get('mu', 0.0),
                        sigma=saved.get('sigma', 0.02),
                        jump_intensity=saved.get('jump_intensity', 0.1),
                        jump_mean=saved.get('jump_mean', 0.0),
                        jump_std=saved.get('jump_std', 0.05),
                    )
                    return self._simulators[market_id]
            self._simulators[market_id] = JumpDiffusionSimulator()
        return self._simulators[market_id]
