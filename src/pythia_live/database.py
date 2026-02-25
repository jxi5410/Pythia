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

    def get_liquid_markets(self, min_liquidity: float = 10000) -> pd.DataFrame:
        """Get liquid markets."""
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("""
                SELECT * FROM markets
                WHERE liquidity >= ?
                ORDER BY liquidity DESC
            """, conn, params=(min_liquidity,))
