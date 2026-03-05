import tempfile
from datetime import datetime

import numpy as np
import pandas as pd

from pythia_live.calibration import CalibrationTracker
from pythia_live.confluence import ConfluenceScorer, Signal as ConfluenceSignal
from pythia_live.database import PythiaDB
from pythia_live.detector import Signal, SignalDetector
from pythia_live.paper_trading import PaperTrading
from pythia_live.risk_engine import EVTRiskModel, PositionSizer


def test_end_to_end_signal_to_calibration():
    with tempfile.TemporaryDirectory() as td:
        db = PythiaDB(f"{td}/int.db")
        detector = SignalDetector(db, {"SIGNAL_COOLDOWN": 0})
        tracker = CalibrationTracker(db)

        prices = pd.DataFrame(
            {
                "timestamp": pd.date_range(end=datetime.now(), periods=80, freq="h").astype(str),
                "yes_price": np.clip(np.linspace(0.25, 0.75, 80), 0, 1),
                "volume": np.full(80, 1000.0),
            }
        )

        market_data = {"id": "m1", "title": "Fed market", "yes_price": 0.95, "volume_24h": 3000}
        sig = detector._detect_probability_spike(market_data, prices)
        assert sig is not None
        assert "anomaly_score" in sig.probability_context

        forecast_id = tracker.record_forecast("m1", sig.probability_context["fitted_mean"], sig.signal_type)
        tracker.record_outcome("m1", actual_outcome=1, forecast_id=forecast_id)
        report = tracker.get_calibration_report(days=30)
        assert report["count"] == 1


def test_signal_dataclass_backward_compatibility():
    sig = Signal(
        market_id="m1",
        market_title="t",
        timestamp=datetime.now(),
        signal_type="PROBABILITY_SPIKE",
        severity="HIGH",
        description="d",
        old_price=0.4,
        new_price=0.5,
        expected_return=0.01,
        metadata={},
    )
    assert sig.probability_context == {}


def test_paper_trading_smaller_under_fat_tail():
    thin = EVTRiskModel()
    thin.fit_tail(np.random.normal(0, 0.01, size=1000).tolist())

    fat = EVTRiskModel()
    fat.fit_tail((np.random.standard_t(df=2.5, size=1000) * 0.02).tolist())

    s = {"expected_return": 0.05, "forecast_prob": 0.6}
    thin_sz = PositionSizer(thin).size_position(s, capital=10000, existing_exposure=0)
    fat_sz = PositionSizer(fat).size_position(s, capital=10000, existing_exposure=0)
    assert fat_sz <= thin_sz


def test_correlation_adjusted_confluence_score_lower_than_naive():
    scorer = ConfluenceScorer(min_layers=2)
    now = datetime.now()
    signals = [
        ConfluenceSignal("equities", "bullish", "fed_rate", 0.8, now, "s1"),
        ConfluenceSignal("fixed_income", "bullish", "fed_rate", 0.8, now, "s2"),
        ConfluenceSignal("twitter", "bullish", "fed_rate", 0.8, now, "s3"),
    ]
    naive = scorer.score(signals)
    adjusted = scorer.score(signals, correlation_clusters=[["equities", "fixed_income"], ["twitter"]])
    assert adjusted.confluence_score < naive.confluence_score
