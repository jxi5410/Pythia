import tempfile

import numpy as np
import pandas as pd
from scipy.stats import beta as beta_dist

from pythia_live.database import PythiaDB
from pythia_live.probability_engine import (
    EnsembleWeighter,
    JumpDiffusionSimulator,
    ProbabilityEngineManager,
    ProbabilityModel,
)


def test_beta_fit_recovers_shape():
    rng = np.random.default_rng(123)
    samples = beta_dist.rvs(2.5, 6.0, size=2000, random_state=rng)
    model = ProbabilityModel()
    model.fit(samples.tolist())
    assert abs(model.alpha - 2.5) < 0.6
    assert abs(model.beta_param - 6.0) < 1.0


def test_anomaly_score_extremes():
    model = ProbabilityModel(alpha=5.0, beta_param=5.0)
    assert model.anomaly_score(0.01) > 0.99
    assert model.anomaly_score(0.99) > 0.99


def test_low_variance_history_uses_stable_fallback():
    model = ProbabilityModel()
    model.fit([0.51] * 40)
    assert model.n_observations == 40
    assert model.alpha > 0.0
    assert model.beta_param > 0.0
    assert abs(model.mean - 0.51) < 0.02


def test_conjugate_style_update_increments():
    model = ProbabilityModel(alpha=2.0, beta_param=3.0, n_observations=10)
    model.update(0.7)
    assert abs(model.alpha - 2.7) < 1e-9
    assert abs(model.beta_param - 3.3) < 1e-9
    assert model.n_observations == 11


def test_jump_diffusion_paths_bounded():
    sim = JumpDiffusionSimulator(mu=0.0, sigma=0.2, jump_intensity=0.2, jump_mean=0.0, jump_std=0.1)
    paths = sim.simulate_paths(current_price=0.5, dt=1 / 24, n_steps=48, n_paths=200)
    assert np.all(paths >= 0.0)
    assert np.all(paths <= 1.0)


def test_ensemble_inverse_variance_weighting():
    ew = EnsembleWeighter()
    ew.add_estimate("beta_model", 0.60, 0.9)
    ew.add_estimate("momentum", 0.40, 0.7)
    ew.add_estimate("orderbook", 0.70, 0.8)
    p = ew.weighted_probability()
    assert 0.55 < p < 0.65
    assert ew.disagreement_score() > 0.0


def test_probability_engine_manager_caches_models():
    with tempfile.TemporaryDirectory() as td:
        db = PythiaDB(f"{td}/test.db")
        mgr = ProbabilityEngineManager(db)
        m1 = mgr.get_or_create_model("m1")
        m2 = mgr.get_or_create_model("m1")
        assert m1 is m2

        history = pd.DataFrame({"yes_price": np.clip(np.linspace(0.2, 0.8, 40), 0, 1)})
        result = mgr.evaluate_signal({"id": "m1", "yes_price": 0.79}, history)
        assert "anomaly_score" in result
        assert "credible_interval" in result
