"""
Database layer for Pythia Live
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
        """Initialize database tables."""
        with sqlite3.connect(self.db_path) as conn:
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
                    signal_type TEXT,  -- 'PROBABILITY_SPIKE', 'ARBITRAGE', 'VOLUME_ANOMALY'
                    severity TEXT,  -- 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
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
            
            conn.commit()
    
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
    
    def save_price(self, market_id: str, yes_price: float, no_price: float, volume: float = 0):
        """Save price snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO prices (market_id, timestamp, yes_price, no_price, volume)
                VALUES (?, ?, ?, ?, ?)
            """, (market_id, datetime.now(), yes_price, no_price, volume))
            conn.commit()
    
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
    
    def get_liquid_markets(self, min_liquidity: float = 10000) -> pd.DataFrame:
        """Get liquid markets."""
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("""
                SELECT * FROM markets 
                WHERE liquidity >= ?
                ORDER BY liquidity DESC
            """, conn, params=(min_liquidity,))
