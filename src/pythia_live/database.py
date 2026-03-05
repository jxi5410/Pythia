"""
Database layer for Pythia Live
SQLite with automatic migration for schema upgrades.
"""
import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict
import pandas as pd


class PythiaDB:
    def __init__(self, db_path: str = "data/pythia_live.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database tables and run migrations."""
        with sqlite3.connect(self.db_path) as conn:
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

            # --- Probability models (v0.8 - Quant layer) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS probability_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT UNIQUE,
                    alpha REAL,
                    beta_param REAL,
                    mu REAL,
                    sigma REAL,
                    jump_intensity REAL,
                    jump_mean REAL,
                    jump_std REAL,
                    n_observations INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # --- Forecasts (v0.8 - Calibration layer) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS forecasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT,
                    forecast_prob REAL,
                    signal_type TEXT,
                    actual_outcome REAL,
                    brier_score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_forecasts_market
                ON forecasts(market_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_forecasts_resolved
                ON forecasts(resolved_at)
            """)

            # --- Risk snapshots (v0.8 - EVT layer) ---
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
                    stress_test_results TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_risk_time
                ON risk_snapshots(timestamp)
            """)

            # --- Correlation pairs (v0.8 - Statistical correlation layer) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS correlation_pairs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id_a TEXT,
                    market_id_b TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    spearman_rho REAL,
                    p_value REAL,
                    rolling_corr_7d REAL,
                    n_observations INTEGER,
                    UNIQUE(market_id_a, market_id_b, timestamp)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_corr_pair
                ON correlation_pairs(market_id_a, market_id_b)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_corr_time
                ON correlation_pairs(timestamp)
            """)

            conn.commit()

    # ------------------------------------------------------------------
    # Markets (unchanged interface)
    # ------------------------------------------------------------------

    def save_market(self, market: Dict):
        """Save or update market."""
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
                    new_price: Optional[float] = None, expected_return: Optional[float] = None) -> int:
        """Save signal and return ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO signals (market_id, timestamp, signal_type, severity,
                                   description, old_price, new_price, expected_return)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (market_id, datetime.now(), signal_type, severity,
                  description, old_price, new_price, expected_return))
            conn.commit()
            return cursor.lastrowid

    def mark_alert_sent(self, signal_id: int, channel: str, status: str = "SUCCESS", error: str = ""):
        """Mark signal as alerted."""
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("""
                SELECT * FROM prices
                WHERE market_id = ?
                AND timestamp > datetime('now', ?)
                ORDER BY timestamp DESC
            """, conn, params=(market_id, f'-{hours} hours'))

    def get_recent_signals(self, hours: int = 1) -> pd.DataFrame:
        """Get recent signals."""
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("""
                SELECT s.*, m.title, m.source
                FROM signals s
                JOIN markets m ON s.market_id = m.id
                WHERE s.timestamp > datetime('now', ?)
                ORDER BY s.timestamp DESC
            """, conn, params=(f'-{hours} hours',))

    # ------------------------------------------------------------------
    # Spike Events (v0.5)
    # ------------------------------------------------------------------

    def save_spike_event(self, spike_dict: Dict) -> int:
        """Save a spike event and return its ID."""
        with sqlite3.connect(self.db_path) as conn:
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

        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(query, conn, params=params)

    def update_spike_tag(self, spike_id: int, tag: str):
        """Update manual tag for a spike event."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE spike_events SET manual_tag = ? WHERE id = ?",
                (tag, spike_id)
            )
            conn.commit()

    def update_spike_reaction(self, spike_id: int, reaction: Dict):
        """Update asset reaction data for a spike event."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE spike_events SET asset_reaction = ? WHERE id = ?",
                (json.dumps(reaction), spike_id)
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Queries (unchanged interface)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Probability Models (v0.8)
    # ------------------------------------------------------------------

    def save_probability_model(self, market_id: str, params: Dict):
        """Save or update probability model parameters for a market."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO probability_models
                (market_id, alpha, beta_param, mu, sigma,
                 jump_intensity, jump_mean, jump_std, n_observations, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                market_id,
                params.get('alpha', 1.0),
                params.get('beta_param', 1.0),
                params.get('mu', 0.0),
                params.get('sigma', 0.01),
                params.get('jump_intensity', 0.1),
                params.get('jump_mean', 0.0),
                params.get('jump_std', 0.05),
                params.get('n_observations', 0),
                datetime.now(),
            ))
            conn.commit()

    def get_probability_model(self, market_id: str) -> Optional[Dict]:
        """Get probability model parameters for a market."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM probability_models WHERE market_id = ?",
                (market_id,)
            ).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Forecasts (v0.8 - Calibration)
    # ------------------------------------------------------------------

    def save_forecast(self, market_id: str, forecast_prob: float,
                      signal_type: str) -> int:
        """Save a forecast for later calibration scoring. Returns row ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO forecasts (market_id, forecast_prob, signal_type)
                VALUES (?, ?, ?)
            """, (market_id, forecast_prob, signal_type))
            conn.commit()
            return cursor.lastrowid

    def resolve_forecast(self, forecast_id: int, actual_outcome: float):
        """Resolve a forecast with actual outcome and compute Brier score."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT forecast_prob FROM forecasts WHERE id = ?",
                (forecast_id,)
            ).fetchone()
            if row:
                brier = (row[0] - actual_outcome) ** 2
                conn.execute("""
                    UPDATE forecasts
                    SET actual_outcome = ?, brier_score = ?, resolved_at = ?
                    WHERE id = ?
                """, (actual_outcome, brier, datetime.now(), forecast_id))
                conn.commit()

    def get_unresolved_forecasts(self, market_id: Optional[str] = None) -> List[Dict]:
        """Get all unresolved forecasts, optionally filtered by market."""
        query = "SELECT * FROM forecasts WHERE resolved_at IS NULL"
        params = []
        if market_id:
            query += " AND market_id = ?"
            params.append(market_id)
        query += " ORDER BY created_at DESC"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_resolved_forecasts(self, days: int = 30,
                                signal_type: Optional[str] = None) -> List[Dict]:
        """Get resolved forecasts for calibration analysis."""
        query = """
            SELECT * FROM forecasts
            WHERE resolved_at IS NOT NULL
            AND created_at > datetime('now', ?)
        """
        params: list = [f'-{days} days']
        if signal_type:
            query += " AND signal_type = ?"
            params.append(signal_type)
        query += " ORDER BY created_at DESC"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Risk Snapshots (v0.8)
    # ------------------------------------------------------------------

    def save_risk_snapshot(self, snapshot: Dict):
        """Save a portfolio risk snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO risk_snapshots
                (timestamp, portfolio_var_95, portfolio_var_99,
                 expected_shortfall_95, expected_shortfall_99,
                 gpd_shape, gpd_scale, n_positions, total_exposure,
                 stress_test_results)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(),
                snapshot.get('portfolio_var_95', 0),
                snapshot.get('portfolio_var_99', 0),
                snapshot.get('expected_shortfall_95', 0),
                snapshot.get('expected_shortfall_99', 0),
                snapshot.get('gpd_shape', 0),
                snapshot.get('gpd_scale', 0),
                snapshot.get('n_positions', 0),
                snapshot.get('total_exposure', 0),
                json.dumps(snapshot.get('stress_test_results', {})),
            ))
            conn.commit()

    # ------------------------------------------------------------------
    # Correlation Pairs (v0.8)
    # ------------------------------------------------------------------

    def save_correlation(self, pair: Dict):
        """Save a correlation pair result."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO correlation_pairs
                (market_id_a, market_id_b, timestamp, spearman_rho,
                 p_value, rolling_corr_7d, n_observations)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                pair['market_id_a'],
                pair['market_id_b'],
                datetime.now(),
                pair.get('spearman_rho', 0),
                pair.get('p_value', 1.0),
                pair.get('rolling_corr_7d', 0),
                pair.get('n_observations', 0),
            ))
            conn.commit()

    def get_correlations(self, market_id: str,
                         min_abs_corr: float = 0.3) -> List[Dict]:
        """Get statistically significant correlations for a market."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM correlation_pairs
                WHERE (market_id_a = ? OR market_id_b = ?)
                AND ABS(spearman_rho) >= ?
                ORDER BY ABS(spearman_rho) DESC
            """, (market_id, market_id, min_abs_corr)).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Returns Series (v0.8 - for EVT and Correlation)
    # ------------------------------------------------------------------

    def get_returns_series(self, market_id: str, hours: int = 720) -> pd.DataFrame:
        """Get price returns series for a market."""
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query("""
                SELECT timestamp, yes_price FROM prices
                WHERE market_id = ?
                AND timestamp > datetime('now', ?)
                ORDER BY timestamp ASC
            """, conn, params=(market_id, f'-{hours} hours'))
            if len(df) > 1:
                df['returns'] = df['yes_price'].pct_change()
                df = df.dropna(subset=['returns'])
            return df

    def get_signal_outcomes(self, days: int = 30) -> List[Dict]:
        """Get signals paired with their outcomes for calibration."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT s.id, s.market_id, s.signal_type, s.severity,
                       s.expected_return, s.new_price, s.timestamp,
                       se.direction, se.magnitude
                FROM signals s
                LEFT JOIN spike_events se ON s.market_id = se.market_id
                    AND se.timestamp > s.timestamp
                    AND se.timestamp <= datetime(s.timestamp, '+24 hours')
                WHERE s.timestamp > datetime('now', ?)
                ORDER BY s.timestamp DESC
            """, (f'-{days} days',)).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Queries (unchanged interface)
    # ------------------------------------------------------------------

    def get_liquid_markets(self, min_liquidity: float = 10000) -> pd.DataFrame:
        """Get liquid markets."""
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("""
                SELECT * FROM markets
                WHERE liquidity >= ?
                ORDER BY liquidity DESC
            """, conn, params=(min_liquidity,))
