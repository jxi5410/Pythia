import tempfile
import sqlite3
from datetime import datetime, timedelta

import numpy as np

from pythia_live.correlations import find_correlated_markets
from pythia_live.cross_correlation import CrossCorrelationEngine
from pythia_live.database import PythiaDB


def _seed_market(db: PythiaDB, market_id: str, title: str, prices):
    db.save_market(
        {
            "id": market_id,
            "source": "test",
            "title": title,
            "category": "test",
            "liquidity": 100000,
            "volume_24h": 10000,
        }
    )
    start = datetime.now() - timedelta(hours=len(prices))
    with sqlite3.connect(db.db_path) as conn:
        for idx, p in enumerate(prices):
            ts = start + timedelta(hours=idx)
            conn.execute(
                """
                INSERT INTO prices (market_id, timestamp, yes_price, no_price, volume)
                VALUES (?, ?, ?, ?, ?)
                """,
                (market_id, ts.isoformat(), float(p), float(1 - p), 100),
            )
        conn.commit()


def test_spearman_one_for_perfectly_correlated_series():
    with tempfile.TemporaryDirectory() as td:
        db = PythiaDB(f"{td}/corr.db")
        x = np.linspace(0.1, 0.9, 120)
        _seed_market(db, "a", "Fed rates market A", x)
        _seed_market(db, "b", "Fed rates market B", x)
        engine = CrossCorrelationEngine(db)
        engine.compute_correlation_matrix(["a", "b"], hours=168)
        rows = engine.find_statistically_correlated("a")
        assert rows
        assert rows[0]["rho"] > 0.99


def test_uncorrelated_series_high_p_value():
    with tempfile.TemporaryDirectory() as td:
        db = PythiaDB(f"{td}/corr2.db")
        rng = np.random.default_rng(7)
        _seed_market(db, "a", "AAA", rng.uniform(0.1, 0.9, 200))
        _seed_market(db, "b", "BBB", rng.uniform(0.1, 0.9, 200))
        engine = CrossCorrelationEngine(db)
        engine.compute_correlation_matrix(["a", "b"], hours=168)
        pairs = db.get_correlations("a")
        assert pairs
        assert pairs[0]["p_value"] > 0.01


def test_correlation_break_detection_fires_on_regime_change():
    with tempfile.TemporaryDirectory() as td:
        db = PythiaDB(f"{td}/corr3.db")
        base = np.linspace(0.2, 0.8, 220)
        mixed = np.concatenate([base[:110], base[110:][::-1]])
        _seed_market(db, "a", "Market A", base)
        _seed_market(db, "b", "Market B", mixed)
        engine = CrossCorrelationEngine(db)
        engine.compute_correlation_matrix(["a", "b"], hours=168)
        breaks = engine.detect_correlation_breaks("a", ["b"])
        assert breaks
        assert breaks[0]["signal_type"] == "CORRELATION_DEVIATION"


def test_tail_dependence_estimate():
    rng = np.random.default_rng(8)
    x = rng.normal(0, 1, size=2000)
    y = x + rng.normal(0, 0.2, size=2000)
    est = CrossCorrelationEngine(db=PythiaDB(":memory:")).tail_dependence_estimate(x.tolist(), y.tolist(), quantile=0.05)
    assert est > 0.2


def test_factor_model_recovers_structure():
    with tempfile.TemporaryDirectory() as td:
        db = PythiaDB(f"{td}/corr4.db")
        rng = np.random.default_rng(9)
        factor = rng.normal(0, 0.02, size=200)
        for i in range(5):
            prices = np.clip(0.5 + np.cumsum(factor + rng.normal(0, 0.005, size=200)), 0.05, 0.95)
            _seed_market(db, f"m{i}", f"Market {i}", prices)
        out = CrossCorrelationEngine(db).compute_factor_exposures([f"m{i}" for i in range(5)])
        assert len(out["factors"]) >= 1


def test_keyword_fallback_with_insufficient_history():
    with tempfile.TemporaryDirectory() as td:
        db = PythiaDB(f"{td}/corr5.db")
        db.save_market({"id": "a", "source": "t", "title": "Fed cut rates by June", "category": "macro", "liquidity": 1000, "volume_24h": 100})
        db.save_market({"id": "b", "source": "t", "title": "Will Fed rates fall this summer", "category": "macro", "liquidity": 900, "volume_24h": 90})
        out = find_correlated_markets(db, "a", "Fed cut rates by June", use_statistical=True)
        assert out
