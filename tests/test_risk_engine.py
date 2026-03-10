import numpy as np
from scipy.stats import t

from pythia_live.risk_engine import EVTRiskModel, LiquidityRisk, PositionSizer, StressTestEngine


def test_gpd_fit_on_fat_tailed_series():
    rng = np.random.default_rng(1)
    returns = t.rvs(df=3, size=5000, random_state=rng) * 0.02
    model = EVTRiskModel()
    model.fit_tail(returns.tolist(), threshold_percentile=0.90)
    assert model.n_exceedances > 0
    assert np.isfinite(model.scale)


def test_var_es_ordering():
    rng = np.random.default_rng(2)
    returns = t.rvs(df=4, size=3000, random_state=rng) * 0.015
    model = EVTRiskModel()
    model.fit_tail(returns.tolist(), threshold_percentile=0.90)
    var99 = model.var(0.99)
    es99 = model.expected_shortfall(0.99)
    assert es99 >= var99 >= 0.0


def test_position_sizer_reduces_under_fat_tails():
    rng = np.random.default_rng(3)
    thin = EVTRiskModel()
    thin.fit_tail((rng.normal(0, 0.01, size=2000)).tolist())

    fat = EVTRiskModel()
    fat.fit_tail((t.rvs(df=2.5, size=2000, random_state=rng) * 0.02).tolist())

    thin_size = PositionSizer(thin).size_position({"expected_return": 0.05, "forecast_prob": 0.6}, 10000, 0)
    fat_size = PositionSizer(fat).size_position({"expected_return": 0.05, "forecast_prob": 0.6}, 10000, 0)
    assert fat_size <= thin_size


def test_stress_scenario_loss_direction():
    portfolio = [{"market_id": "a", "position_size": 1000}, {"market_id": "b", "position_size": 500}]
    scenario = {"a": -0.1, "b": -0.05}
    out = StressTestEngine().run_scenario(portfolio, scenario)
    assert out["total_pnl"] < 0


def test_reverse_stress_finds_breakpoint():
    portfolio = [{"market_id": "a", "position_size": 1000}]
    out = StressTestEngine().reverse_stress(portfolio, loss_threshold=200)
    assert out["breached"] is True
    assert out["total_pnl"] <= -200


def test_liquidity_risk_dataclass():
    lr = LiquidityRisk(estimated_slippage=0.02, time_to_exit_seconds=120.0, depth_at_best=5000)
    assert lr.estimated_slippage == 0.02
