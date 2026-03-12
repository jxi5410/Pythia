import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.database import PythiaDB
from core.evaluation.attribution_compare import persist_attribution_run, persist_shadow_comparison


def test_persist_shadow_and_runs(tmp_path):
    db_file = tmp_path / "test.db"
    db = PythiaDB(str(db_file))

    pce = {
        "spike_id": 9,
        "engine": "pce_v2",
        "engine_version": "2",
        "attribution": {"confidence": "MEDIUM", "most_likely_cause": "Fed"},
    }
    rce = {
        "spike_id": 9,
        "engine": "rce_v1",
        "engine_version": "1",
        "attribution": {"confidence": "LOW", "most_likely_cause": "Noisy"},
    }

    persist_attribution_run(db, mode="fast", result=pce)
    persist_shadow_comparison(db, spike_id=9, primary=pce, shadow=rce)

    with sqlite3.connect(db.db_path) as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM attribution_runs").fetchone()[0]
        cmp_count = conn.execute("SELECT COUNT(*) FROM attribution_comparisons").fetchone()[0]

    assert run_count == 1
    assert cmp_count == 1
