import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

from pythia_live.database import PythiaDB
from pythia_live.paper_trading import PaperTrading
from pythia_live.track_record import get_track_record


def test_track_record_includes_realized_risk_metrics():
    with tempfile.TemporaryDirectory() as td:
        db_path = f"{td}/track.db"
        db = PythiaDB(db_path)
        PaperTrading(db_path)

        now = datetime.now(timezone.utc)
        with sqlite3.connect(db.db_path) as conn:
            conn.execute(
                """
                INSERT INTO confluence_events
                (event_category, direction, confluence_score, layer_count, layers, confidence, timestamp, alert_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "fed_rate",
                    "bullish",
                    0.82,
                    3,
                    '["equities", "twitter", "fixed_income"]',
                    0.82,
                    now.isoformat(),
                    "Fed signal fired",
                ),
            )
            conn.execute(
                """
                INSERT INTO spike_events
                (market_id, market_title, timestamp, direction, magnitude, price_before, price_after, volume_at_spike, asset_class)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "m1",
                    "Fed market",
                    (now + timedelta(hours=2)).isoformat(),
                    "up",
                    0.03,
                    0.50,
                    0.53,
                    10000,
                    "rates",
                ),
            )
            conn.executemany(
                """
                INSERT INTO paper_trades
                (signal_id, market_id, market_title, trade_type, side, entry_price, exit_price,
                 position_size, expected_return, actual_return, status, opened_at, closed_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1, "m1", "Fed market", "taker", "yes", 0.55, 0.70, 1000, 0.10, 0.20, "closed", now.isoformat(), now.isoformat(), "{}"),
                    (1, "m2", "Tariff market", "taker", "no", 0.45, 0.30, 1000, 0.08, -0.10, "closed", now.isoformat(), now.isoformat(), "{}"),
                    (1, "m3", "Crypto market", "taker", "yes", 0.40, 0.55, 1000, 0.06, 0.15, "closed", now.isoformat(), now.isoformat(), "{}"),
                ],
            )
            conn.commit()

        record = get_track_record(days=30, db=db)

        assert record.total_events == 1
        assert record.total_hits == 1
        assert record.realized_trade_count == 3
        assert record.avg_realized_return > 0
        assert record.sharpe_ratio != 0
        assert record.max_drawdown > 0
        assert record.win_loss_ratio > 1
