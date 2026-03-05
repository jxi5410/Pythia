"""
Paper Trading Module for Pythia Live
Simulates execution and tracks P&L without real money
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class TradeStatus(Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass
class PaperTrade:
    """A paper trade record."""
    id: int
    signal_id: int
    market_id: str
    market_title: str
    trade_type: str  # 'maker' or 'taker'
    side: str  # 'yes' or 'no'
    entry_price: float
    exit_price: Optional[float]
    position_size: float  # Dollar amount
    expected_return: float
    actual_return: Optional[float]
    status: TradeStatus
    opened_at: datetime
    closed_at: Optional[datetime]
    metadata: Dict


class PaperTrading:
    """
    Paper trading system for Pythia Live.

    Automatically creates trades from HIGH/CRITICAL signals
    and tracks P&L without real execution.
    """

    def __init__(self, db_path: str, initial_capital: float = 10000.0,
                 position_sizer=None, calibration_tracker=None):
        self.db_path = db_path
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.position_sizer = position_sizer
        self.calibration_tracker = calibration_tracker
        self._init_db()
    
    def _init_db(self):
        """Initialize paper trading tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER,
                    market_id TEXT,
                    market_title TEXT,
                    trade_type TEXT,
                    side TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    position_size REAL,
                    expected_return REAL,
                    actual_return REAL,
                    status TEXT,
                    opened_at TIMESTAMP,
                    closed_at TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (signal_id) REFERENCES signals(id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY,
                    timestamp TIMESTAMP,
                    capital REAL,
                    exposure REAL,
                    open_positions INTEGER,
                    daily_pnl REAL
                )
            """)
            
            conn.commit()
    
    def create_trade_from_signal(self, signal: Dict) -> Optional[int]:
        """
        Create a paper trade from a signal.
        
        Args:
            signal: Signal dictionary with market info
            
        Returns:
            Trade ID or None if not created
        """
        # Risk checks
        if not self._can_open_position(signal['expected_return']):
            return None
        
        # Calculate position size — use EVT-aware sizer if available
        if self.position_sizer:
            exposure = self._get_current_exposure()
            position_size = self.position_sizer.size_position(
                signal, self.current_capital, exposure,
            )
        else:
            edge = signal.get('expected_return', 0.02)
            kelly_fraction = min(edge * 0.5, 0.25)  # Half Kelly, max 25%
            position_size = self.current_capital * kelly_fraction
        
        # Determine side from signal
        side = 'yes'  # Default
        if 'metadata' in signal:
            meta = json.loads(signal['metadata']) if isinstance(signal['metadata'], str) else signal['metadata']
            if meta.get('direction') == 'down':
                side = 'no'
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO paper_trades 
                (signal_id, market_id, market_title, trade_type, side,
                 entry_price, exit_price, position_size, expected_return,
                 actual_return, status, opened_at, closed_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal['id'],
                signal['market_id'],
                signal.get('title', 'Unknown'),
                'maker' if signal['signal_type'] == 'MAKER_EDGE' else 'taker',
                side,
                signal.get('new_price', 0.5),
                None,
                position_size,
                signal['expected_return'],
                None,
                TradeStatus.EXECUTED.value,
                datetime.now(),
                None,
                json.dumps(signal.get('metadata', {}))
            ))
            conn.commit()
            return cursor.lastrowid
    
    def _can_open_position(self, expected_return: float) -> bool:
        """Risk check before opening position."""
        # Check capital
        if self.current_capital < self.initial_capital * 0.5:  # 50% drawdown stop
            return False
        
        # Check daily loss limit
        daily_pnl = self._get_daily_pnl()
        if daily_pnl < -self.initial_capital * 0.10:  # 10% daily loss limit
            return False
        
        # Check exposure
        exposure = self._get_current_exposure()
        if exposure > self.current_capital * 0.8:  # Max 80% exposed
            return False
        
        return True
    
    def _get_daily_pnl(self) -> float:
        """Get today's P&L."""
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("""
                SELECT COALESCE(SUM(actual_return * position_size), 0)
                FROM paper_trades
                WHERE date(closed_at) = date('now')
            """).fetchone()
            return result[0] if result else 0
    
    def _get_current_exposure(self) -> float:
        """Get current total exposure."""
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("""
                SELECT COALESCE(SUM(position_size), 0)
                FROM paper_trades
                WHERE status = ?
            """, (TradeStatus.EXECUTED.value,)).fetchone()
            return result[0] if result else 0
    
    def close_position(self, trade_id: int, exit_price: float, 
                       actual_outcome: int) -> float:
        """
        Close a paper trade and calculate P&L.
        
        Args:
            trade_id: Trade to close
            exit_price: Current market price
            actual_outcome: 1 for YES, 0 for NO
            
        Returns:
            Actual P&L
        """
        with sqlite3.connect(self.db_path) as conn:
            # Get trade details
            trade = conn.execute(
                "SELECT * FROM paper_trades WHERE id = ?",
                (trade_id,)
            ).fetchone()
            
            if not trade:
                return 0
            
            # Calculate P&L
            entry_price = trade[6]  # entry_price column
            position_size = trade[8]  # position_size column
            side = trade[5]  # side column
            
            if side == 'yes':
                if actual_outcome == 1:
                    pnl_pct = (1 / entry_price - 1)
                else:
                    pnl_pct = -1
            else:  # side == 'no'
                if actual_outcome == 0:
                    pnl_pct = (1 / (1 - entry_price) - 1)
                else:
                    pnl_pct = -1
            
            actual_pnl = position_size * pnl_pct
            
            # Update trade
            conn.execute("""
                UPDATE paper_trades
                SET exit_price = ?, actual_return = ?, status = ?, closed_at = ?
                WHERE id = ?
            """, (exit_price, pnl_pct, TradeStatus.CLOSED.value, datetime.now(), trade_id))
            
            conn.commit()
            
            # Update capital
            self.current_capital += actual_pnl

            # Record outcome for calibration
            if self.calibration_tracker:
                market_id = trade[2]  # market_id column
                self.calibration_tracker.record_outcome(
                    market_id, float(actual_outcome)
                )

            return actual_pnl
    
    def get_portfolio_summary(self) -> Dict:
        """Get current portfolio summary."""
        with sqlite3.connect(self.db_path) as conn:
            # Total stats
            stats = conn.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN actual_return > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN status = ? THEN position_size ELSE 0 END) as open_exposure,
                    AVG(actual_return) as avg_return,
                    SUM(actual_return * position_size) as total_pnl
                FROM paper_trades
                WHERE status = ?
            """, (TradeStatus.EXECUTED.value, TradeStatus.CLOSED.value)).fetchone()
            
            total_trades = stats[0] or 0
            winning_trades = stats[1] or 0
            open_exposure = stats[2] or 0
            avg_return = stats[3] or 0
            total_pnl = stats[4] or 0
            
            return {
                'initial_capital': self.initial_capital,
                'current_capital': self.current_capital,
                'total_pnl': total_pnl,
                'total_return': (self.current_capital - self.initial_capital) / self.initial_capital,
                'total_trades': total_trades,
                'win_rate': winning_trades / total_trades if total_trades > 0 else 0,
                'avg_return': avg_return,
                'open_exposure': open_exposure,
                'available_capital': self.current_capital - open_exposure
            }
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open positions."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM paper_trades
                WHERE status = ?
                ORDER BY opened_at DESC
            """, (TradeStatus.EXECUTED.value,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def record_portfolio_snapshot(self):
        """Record daily portfolio snapshot."""
        summary = self.get_portfolio_summary()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO portfolio (timestamp, capital, exposure, open_positions, daily_pnl)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.now(),
                summary['current_capital'],
                summary['open_exposure'],
                len(self.get_open_positions()),
                summary['total_pnl']
            ))
            conn.commit()
