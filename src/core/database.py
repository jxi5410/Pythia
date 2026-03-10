"""
Database layer for Pythia Live
SQLite with automatic migration for schema upgrades.
"""
import logging
import sqlite3
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from collections import defaultdict
import pandas as pd

logger = logging.getLogger(__name__)


class PythiaDB:
    def __init__(self, db_path: str = "data/pythia_live.db"):
        self.db_path = str(Path(db_path).expanduser().resolve())
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _ensure_parent_dir(self) -> None:
        """Create the database parent directory when using a filesystem path."""
        parent = Path(self.db_path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Open and configure a SQLite connection."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        """Return a reusable SQLite connection using the configured DB path."""
        self._ensure_parent_dir()
        db_path = Path(self.db_path)

        if self._conn is not None:
            try:
                self._conn.execute("SELECT 1")
                return self._conn
            except sqlite3.Error:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

        last_error = None
        for attempt in range(2):
            try:
                self._conn = self._connect()
                return self._conn
            except sqlite3.OperationalError as exc:
                last_error = exc
                try:
                    cwd = str(Path.cwd())
                except OSError:
                    cwd = "<cwd-unavailable>"
                logger.warning(
                    "SQLite open failed (attempt %d/2) path=%s exists=%s parent_exists=%s cwd=%s err=%s",
                    attempt + 1,
                    db_path,
                    db_path.exists(),
                    db_path.parent.exists(),
                    cwd,
                    exc,
                )
                time.sleep(0.25)
        raise last_error

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.close()
        finally:
            self._conn = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _init_db(self):
        """Initialize database tables and run migrations."""
        self._ensure_parent_dir()
        with self._get_conn() as conn:
            # --- Original tables (kept for backward compat) ---

            # Markets
            conn.execute("""
                CREATE TABLE IF NOT EXISTS markets (
                    id TEXT PRIMARY KEY,
                    source TEXT,  -- 'polymarket', 'kalshi'
                    title TEXT,
                    category TEXT,
                    liquidity REAL,
                    volume_24h REAL,
                    created_at TIMESTAMP,
                    last_updated TIMESTAMP
                )
            """)

            # Price history
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT,
                    timestamp TIMESTAMP,
                    yes_price REAL,
                    no_price REAL,
                    volume REAL,
                    FOREIGN KEY (market_id) REFERENCES markets(id)
                )
            """)

            # Signals
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT,
                    timestamp TIMESTAMP,
                    signal_type TEXT,
                    severity TEXT,
                    description TEXT,
                    old_price REAL,
                    new_price REAL,
                    expected_return REAL,
                    alert_sent BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (market_id) REFERENCES markets(id)
                )
            """)

            # Alerts sent
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER,
                    timestamp TIMESTAMP,
                    channel TEXT,
                    status TEXT,
                    error_msg TEXT,
                    FOREIGN KEY (signal_id) REFERENCES signals(id)
                )
            """)

            # --- New tables (v0.3) ---

            # Trades — maker/taker level data
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT,
                    market_id TEXT,
                    source TEXT,
                    timestamp TIMESTAMP,
                    price REAL,
                    amount REAL,
                    taker_side TEXT,          -- 'yes' or 'no'
                    maker_address TEXT,
                    taker_address TEXT,
                    FOREIGN KEY (market_id) REFERENCES markets(id)
                )
            """)

            # Market snapshots — periodic full state capture
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT,
                    timestamp TIMESTAMP,
                    source TEXT,
                    yes_price REAL,
                    no_price REAL,
                    spread REAL,
                    volume_24h REAL,
                    liquidity REAL,
                    open_interest REAL,
                    snapshot_data TEXT,        -- JSON blob for extra fields
                    FOREIGN KEY (market_id) REFERENCES markets(id)
                )
            """)

            # Indexes for new tables
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_market_id
                ON trades(market_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_timestamp
                ON trades(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_trade_id
                ON trades(trade_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshots_market_id
                ON market_snapshots(market_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
                ON market_snapshots(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_prices_market_id
                ON prices(market_id)
            """)

            # --- Spike events (v0.5) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS spike_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT,
                    market_title TEXT,
                    timestamp TIMESTAMP,
                    direction TEXT,
                    magnitude REAL,
                    price_before REAL,
                    price_after REAL,
                    volume_at_spike REAL,
                    asset_class TEXT,
                    attributed_events TEXT DEFAULT '[]',
                    manual_tag TEXT DEFAULT '',
                    asset_reaction TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (market_id) REFERENCES markets(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_spikes_market
                ON spike_events(market_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_spikes_asset
                ON spike_events(asset_class)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_spikes_time
                ON spike_events(timestamp)
            """)

            # --- Confluence events (v0.6) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS confluence_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_category TEXT,
                    direction TEXT,
                    confluence_score REAL,
                    layer_count INTEGER,
                    layers TEXT DEFAULT '[]',
                    confidence REAL,
                    timestamp TIMESTAMP,
                    historical_hit_rate REAL DEFAULT 0.0,
                    suggested_assets TEXT DEFAULT '[]',
                    alert_text TEXT DEFAULT '',
                    signals_json TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_confluence_time
                ON confluence_events(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_confluence_category
                ON confluence_events(event_category)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_confluence_score
                ON confluence_events(confluence_score)
            """)

            # --- Quant engines (v0.7) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS probability_models (
                    market_id TEXT PRIMARY KEY,
                    alpha REAL,
                    beta_param REAL,
                    mu REAL DEFAULT 0.0,
                    sigma REAL DEFAULT 0.0,
                    jump_intensity REAL DEFAULT 0.0,
                    jump_mean REAL DEFAULT 0.0,
                    jump_std REAL DEFAULT 0.0,
                    n_observations INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS forecasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT NOT NULL,
                    forecast_prob REAL NOT NULL,
                    signal_type TEXT NOT NULL,
                    actual_outcome INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP,
                    brier_score REAL,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_forecasts_market_created
                ON forecasts(market_id, created_at DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_forecasts_signal_created
                ON forecasts(signal_type, created_at DESC)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    portfolio_var_95 REAL,
                    portfolio_var_99 REAL,
                    expected_shortfall_95 REAL,
                    expected_shortfall_99 REAL,
                    gpd_shape REAL,
                    gpd_scale REAL,
                    n_positions INTEGER,
                    total_exposure REAL,
                    stress_test_results TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS correlation_pairs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id_a TEXT NOT NULL,
                    market_id_b TEXT NOT NULL,
                    spearman_rho REAL NOT NULL,
                    p_value REAL NOT NULL,
                    rolling_corr_7d REAL,
                    n_observations INTEGER DEFAULT 0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(market_id_a, market_id_b, timestamp)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_corr_pairs_a
                ON correlation_pairs(market_id_a, timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_corr_pairs_b
                ON correlation_pairs(market_id_b, timestamp DESC)
            """)

            self._ensure_column(conn, "signals", "metadata", "TEXT DEFAULT '{}'")
            self._ensure_column(conn, "signals", "probability_context", "TEXT DEFAULT '{}'")

            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {c[1] for c in cols}
        if column not in names:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # ------------------------------------------------------------------
    # Markets (unchanged interface)
    # ------------------------------------------------------------------

    def save_market(self, market: Dict):
        """Save or update market."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO markets
                (id, source, title, category, liquidity, volume_24h, created_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                market['id'], market['source'], market['title'],
                market.get('category', ''), market.get('liquidity', 0),
                market.get('volume_24h', 0),
                market.get('created_at', datetime.now()),
                datetime.now()
            ))
            conn.commit()
    
    def get_market(self, market_id: str) -> Optional[Dict]:
        """Get market by ID."""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT id, source, title, category, liquidity, volume_24h, 
                       created_at, last_updated
                FROM markets
                WHERE id = ?
            """, (market_id,))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None

    # ------------------------------------------------------------------
    # Prices (unchanged interface)
    # ------------------------------------------------------------------

    def save_price(self, market_id: str, yes_price: float, no_price: float, volume: float = 0):
        """Save price snapshot."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO prices (market_id, timestamp, yes_price, no_price, volume)
                VALUES (?, ?, ?, ?, ?)
            """, (market_id, datetime.now(), yes_price, no_price, volume))
            conn.commit()

    # ------------------------------------------------------------------
    # Signals (unchanged interface)
    # ------------------------------------------------------------------

    def save_signal(self, market_id: str, signal_type: str, severity: str,
                    description: str, old_price: Optional[float] = None,
                    new_price: Optional[float] = None, expected_return: Optional[float] = None,
                    metadata: Optional[Dict] = None, probability_context: Optional[Dict] = None) -> int:
        """Save signal and return ID."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO signals (market_id, timestamp, signal_type, severity,
                                   description, old_price, new_price, expected_return, metadata, probability_context)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (market_id, datetime.now(), signal_type, severity,
                  description, old_price, new_price, expected_return,
                  json.dumps(metadata or {}), json.dumps(probability_context or {})))
            conn.commit()
            return cursor.lastrowid

    def mark_alert_sent(self, signal_id: int, channel: str, status: str = "SUCCESS", error: str = ""):
        """Mark signal as alerted."""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE signals SET alert_sent = TRUE WHERE id = ?
            """, (signal_id,))
            conn.execute("""
                INSERT INTO alerts (signal_id, timestamp, channel, status, error_msg)
                VALUES (?, ?, ?, ?, ?)
            """, (signal_id, datetime.now(), channel, status, error))
            conn.commit()

    # ------------------------------------------------------------------
    # Trades (new)
    # ------------------------------------------------------------------

    def save_trade(self, trade: Dict):
        """Save a single trade."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO trades
                (trade_id, market_id, source, timestamp, price, amount,
                 taker_side, maker_address, taker_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get('trade_id', ''),
                trade.get('market_id', ''),
                trade.get('source', ''),
                trade.get('timestamp', datetime.now()),
                trade.get('price', 0),
                trade.get('amount', 0),
                trade.get('taker_side', ''),
                trade.get('maker_address', ''),
                trade.get('taker_address', ''),
            ))
            conn.commit()

    def save_trades_batch(self, trades: List[Dict]):
        """Save a batch of trades efficiently."""
        if not trades:
            return
        with self._get_conn() as conn:
            conn.executemany("""
                INSERT OR IGNORE INTO trades
                (trade_id, market_id, source, timestamp, price, amount,
                 taker_side, maker_address, taker_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    t.get('trade_id', ''),
                    t.get('market_id', ''),
                    t.get('source', ''),
                    t.get('timestamp', datetime.now()),
                    t.get('price', 0),
                    t.get('amount', 0),
                    t.get('taker_side', ''),
                    t.get('maker_address', ''),
                    t.get('taker_address', ''),
                )
                for t in trades
            ])
            conn.commit()

    def get_market_trades(self, market_id: str, hours: int = 24) -> pd.DataFrame:
        """Get trades for a market within the time window."""
        with self._get_conn() as conn:
            return pd.read_sql_query("""
                SELECT * FROM trades
                WHERE market_id = ?
                AND timestamp > datetime('now', ?)
                ORDER BY timestamp DESC
            """, conn, params=(market_id, f'-{hours} hours'))

    # ------------------------------------------------------------------
    # Snapshots (new)
    # ------------------------------------------------------------------

    def save_snapshot(self, market_id: str, source: str, price_data: Dict):
        """Save a full market snapshot."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO market_snapshots
                (market_id, timestamp, source, yes_price, no_price, spread,
                 volume_24h, liquidity, open_interest, snapshot_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                market_id,
                datetime.now(),
                source,
                price_data.get('yes_price', 0),
                price_data.get('no_price', 0),
                price_data.get('spread', 0),
                price_data.get('volume_24h', 0),
                price_data.get('liquidity', 0),
                price_data.get('open_interest', 0),
                json.dumps(price_data),
            ))
            conn.commit()

    # ------------------------------------------------------------------
    # Queries (unchanged interface)
    # ------------------------------------------------------------------

    def get_market_history(self, market_id: str, hours: int = 24) -> pd.DataFrame:
        """Get price history for market."""
        with self._get_conn() as conn:
            return pd.read_sql_query("""
                SELECT * FROM prices
                WHERE market_id = ?
                AND timestamp > datetime('now', ?)
                ORDER BY timestamp DESC
            """, conn, params=(market_id, f'-{hours} hours'))

    def get_recent_signals(self, hours: int = 1) -> pd.DataFrame:
        """Get recent signals."""
        with self._get_conn() as conn:
            return pd.read_sql_query("""
                SELECT s.*, m.title, m.source, m.category
                FROM signals s
                JOIN markets m ON s.market_id = m.id
                WHERE s.timestamp > datetime('now', ?)
                ORDER BY s.timestamp DESC
            """, conn, params=(f'-{hours} hours',))

    # ------------------------------------------------------------------
    # Probability models
    # ------------------------------------------------------------------

    def save_probability_model(
        self,
        market_id: str,
        alpha: float,
        beta_param: float,
        mu: float = 0.0,
        sigma: float = 0.0,
        jump_intensity: float = 0.0,
        jump_mean: float = 0.0,
        jump_std: float = 0.0,
        n_observations: int = 0,
    ) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO probability_models
                (market_id, alpha, beta_param, mu, sigma, jump_intensity, jump_mean, jump_std, n_observations, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market_id) DO UPDATE SET
                    alpha = excluded.alpha,
                    beta_param = excluded.beta_param,
                    mu = excluded.mu,
                    sigma = excluded.sigma,
                    jump_intensity = excluded.jump_intensity,
                    jump_mean = excluded.jump_mean,
                    jump_std = excluded.jump_std,
                    n_observations = excluded.n_observations,
                    updated_at = excluded.updated_at
            """, (
                market_id, alpha, beta_param, mu, sigma, jump_intensity,
                jump_mean, jump_std, n_observations, datetime.now()
            ))
            conn.commit()

    def get_probability_model(self, market_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM probability_models WHERE market_id = ?",
                (market_id,),
            ).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Calibration forecasts
    # ------------------------------------------------------------------

    def save_forecast(self, market_id: str, forecast_prob: float, signal_type: str, metadata: Optional[Dict] = None) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO forecasts
                (market_id, forecast_prob, signal_type, metadata)
                VALUES (?, ?, ?, ?)
            """, (market_id, forecast_prob, signal_type, json.dumps(metadata or {})))
            conn.commit()
            return cursor.lastrowid

    def resolve_forecast(self, forecast_id: int, actual_outcome: int) -> Optional[int]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT forecast_prob FROM forecasts WHERE id = ?",
                (forecast_id,),
            ).fetchone()
            if not row:
                return None
            forecast_prob = float(row[0])
            brier = (forecast_prob - float(1 if actual_outcome else 0)) ** 2
            conn.execute("""
                UPDATE forecasts
                SET actual_outcome = ?, resolved_at = ?, brier_score = ?
                WHERE id = ?
            """, (actual_outcome, datetime.now(), brier, forecast_id))
            conn.commit()
            return forecast_id

    def get_unresolved_forecasts(self, market_id: Optional[str] = None, signal_type: Optional[str] = None) -> List[Dict]:
        query = "SELECT * FROM forecasts WHERE actual_outcome IS NULL"
        params: List = []
        if market_id:
            query += " AND market_id = ?"
            params.append(market_id)
        if signal_type:
            query += " AND signal_type = ?"
            params.append(signal_type)
        query += " ORDER BY created_at DESC"

        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_signal_outcomes(self, days: int = 30, signal_type: Optional[str] = None) -> List[Dict]:
        query = """
            SELECT id, market_id, forecast_prob, signal_type, actual_outcome, created_at, resolved_at, brier_score
            FROM forecasts
            WHERE actual_outcome IS NOT NULL
            AND created_at > datetime('now', ?)
        """
        params: List = [f"-{days} days"]
        if signal_type:
            query += " AND signal_type = ?"
            params.append(signal_type)
        query += " ORDER BY created_at DESC"

        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_signal_outcomes_by_type(self, days: int = 30) -> Dict[str, List[Dict]]:
        rows = self.get_signal_outcomes(days=days, signal_type=None)
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for row in rows:
            grouped[row["signal_type"]].append(row)
        return dict(grouped)

    # ------------------------------------------------------------------
    # Returns and risk snapshots
    # ------------------------------------------------------------------

    def get_returns_series(self, market_id: str, days: int = 30) -> List[float]:
        hours = max(24, days * 24)
        hist = self.get_market_history(market_id, hours=hours)
        if hist.empty or "yes_price" not in hist.columns:
            return []
        if "timestamp" in hist.columns:
            hist = hist.sort_values("timestamp")
        series = hist["yes_price"].astype(float).values
        if len(series) < 2:
            return []
        returns = (series[1:] - series[:-1]) / series[:-1]
        returns = returns[~pd.isna(returns)]
        return [float(r) for r in returns if pd.notna(r)]

    def save_risk_snapshot(
        self,
        portfolio_var_95: float,
        portfolio_var_99: float,
        expected_shortfall_95: float,
        expected_shortfall_99: float,
        gpd_shape: float,
        gpd_scale: float,
        n_positions: int,
        total_exposure: float,
        stress_test_results: Dict,
    ) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO risk_snapshots
                (portfolio_var_95, portfolio_var_99, expected_shortfall_95, expected_shortfall_99,
                 gpd_shape, gpd_scale, n_positions, total_exposure, stress_test_results)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                portfolio_var_95, portfolio_var_99, expected_shortfall_95, expected_shortfall_99,
                gpd_shape, gpd_scale, n_positions, total_exposure, json.dumps(stress_test_results or {}),
            ))
            conn.commit()

    # ------------------------------------------------------------------
    # Correlations
    # ------------------------------------------------------------------

    def save_correlation(
        self,
        market_id_a: str,
        market_id_b: str,
        spearman_rho: float,
        p_value: float,
        rolling_corr_7d: Optional[float],
        n_observations: int,
    ) -> None:
        a, b = sorted([market_id_a, market_id_b])
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO correlation_pairs
                (market_id_a, market_id_b, spearman_rho, p_value, rolling_corr_7d, n_observations, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (a, b, spearman_rho, p_value, rolling_corr_7d, n_observations, datetime.now()))
            conn.commit()

    def get_correlations(self, market_id: Optional[str] = None, limit: int = 500) -> List[Dict]:
        query = """
            SELECT c.*
            FROM correlation_pairs c
            JOIN (
                SELECT market_id_a, market_id_b, MAX(timestamp) AS max_ts
                FROM correlation_pairs
                GROUP BY market_id_a, market_id_b
            ) latest
            ON c.market_id_a = latest.market_id_a
            AND c.market_id_b = latest.market_id_b
            AND c.timestamp = latest.max_ts
        """
        params: List = []
        if market_id:
            query += " WHERE c.market_id_a = ? OR c.market_id_b = ?"
            params.extend([market_id, market_id])
        query += " ORDER BY ABS(c.spearman_rho) DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Spike Events (v0.5)
    # ------------------------------------------------------------------

    def save_spike_event(self, spike_dict: Dict) -> int:
        """Save a spike event and return its ID."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO spike_events
                (market_id, market_title, timestamp, direction, magnitude,
                 price_before, price_after, volume_at_spike, asset_class,
                 attributed_events, manual_tag, asset_reaction)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                spike_dict['market_id'],
                spike_dict.get('market_title', ''),
                spike_dict.get('timestamp', datetime.now()),
                spike_dict.get('direction', ''),
                spike_dict.get('magnitude', 0),
                spike_dict.get('price_before', 0),
                spike_dict.get('price_after', 0),
                spike_dict.get('volume_at_spike', 0),
                spike_dict.get('asset_class', ''),
                json.dumps(spike_dict.get('attributed_events', [])),
                spike_dict.get('manual_tag', ''),
                json.dumps(spike_dict.get('asset_reaction', {})),
            ))
            conn.commit()
            return cursor.lastrowid

    def get_spike_events(self, market_id: str = None, asset_class: str = None,
                         min_magnitude: float = 0.03, limit: int = 50) -> pd.DataFrame:
        """Get spike events with optional filters."""
        query = "SELECT * FROM spike_events WHERE magnitude >= ?"
        params: list = [min_magnitude]

        if market_id:
            query += " AND market_id = ?"
            params.append(market_id)
        if asset_class:
            query += " AND asset_class = ?"
            params.append(asset_class)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def update_spike_tag(self, spike_id: int, tag: str):
        """Update manual tag for a spike event."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE spike_events SET manual_tag = ? WHERE id = ?",
                (tag, spike_id)
            )
            conn.commit()

    def update_spike_reaction(self, spike_id: int, reaction: Dict):
        """Update asset reaction data for a spike event."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE spike_events SET asset_reaction = ? WHERE id = ?",
                (json.dumps(reaction), spike_id)
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Queries (unchanged interface)
    # ------------------------------------------------------------------

    def get_liquid_markets(self, min_liquidity: float = 10000) -> pd.DataFrame:
        """Get liquid markets."""
        with self._get_conn() as conn:
            return pd.read_sql_query("""
                SELECT * FROM markets
                WHERE liquidity >= ?
                ORDER BY liquidity DESC
            """, conn, params=(min_liquidity,))
