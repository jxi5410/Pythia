"""
Automation Controller for Pythia Live
Manages autonomous operation of the trading system
"""

import logging
import sqlite3
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import threading

from .database import PythiaDB
from .detector import SignalDetector, Signal
from .alerts import TelegramAlerter
from .paper_trading import PaperTrading

logger = logging.getLogger(__name__)


class AutomationController:
    """
    Manages autonomous operation of Pythia Live.
    
    Features:
    - Auto-trade from HIGH/CRITICAL signals
    - Daily portfolio snapshots
    - Risk limit enforcement
    - End-of-day reporting
    """
    
    def __init__(self, db_path: str, config: Dict):
        self.db = PythiaDB(db_path)
        self.config = config
        self.paper_trading = PaperTrading(db_path, config.get('initial_capital', 10000))
        self.alerter = TelegramAlerter(
            config.get('telegram_bot_token', ''),
            config.get('telegram_chat_id', ''),
            self.db
        )
        
        self.running = False
        self.trades_today = 0
        self.daily_pnl = 0
        self.last_snapshot = None
        
    def start_automation(self):
        """Start the automation loop."""
        logger.info("Starting Pythia Automation Controller...")
        logger.info("  Initial Capital: $%,.2f", self.config.get('initial_capital', 10000))
        logger.info("  Max Daily Trades: %d", self.config.get('max_daily_trades', 10))
        logger.info("  Daily Loss Limit: %.1f%%", self.config.get('daily_loss_limit', 0.10) * 100)
        
        self.running = True
        self._send_startup_message()
        
        try:
            while self.running:
                cycle_start = time.time()
                
                # Check if new day (reset counters)
                self._check_new_day()
                
                # Process new HIGH/CRITICAL signals for auto-trading
                self._process_auto_trades()
                
                # Check risk limits
                if self._check_risk_limits():
                    logger.warning("Risk limit hit - pausing auto-trading")
                    time.sleep(300)  # 5 min cooldown
                    continue
                
                # Portfolio snapshot (hourly)
                self._maybe_take_snapshot()
                
                # End of day report
                self._maybe_send_eod_report()
                
                # Sleep
                elapsed = time.time() - cycle_start
                sleep_time = max(0, 60 - elapsed)  # 1 min cycle
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.info("Stopping automation...")
            self._send_shutdown_message()
            self.running = False
    
    def _check_new_day(self):
        """Reset daily counters if new day."""
        now = datetime.now()
        if now.hour == 0 and now.minute < 5:  # First 5 min of day
            if self.trades_today > 0:
                logger.info("New day - resetting counters (yesterday: %d trades)", self.trades_today)
                self.trades_today = 0
                self.daily_pnl = 0
    
    def _process_auto_trades(self):
        """Auto-create paper trades from recent HIGH/CRITICAL signals."""
        # Get recent unprocessed HIGH/CRITICAL signals
        recent_signals = self.db.get_recent_signals(hours=1)
        
        if recent_signals.empty:
            return
        
        # Filter to HIGH/CRITICAL only
        auto_signals = recent_signals[
            recent_signals['severity'].isin(['HIGH', 'CRITICAL'])
        ]
        
        for _, signal in auto_signals.iterrows():
            # Check if already traded
            if self._is_signal_traded(signal['id']):
                continue
            
            # Check daily trade limit
            if self.trades_today >= self.config.get('max_daily_trades', 10):
                logger.warning("Daily trade limit reached (%d)", self.trades_today)
                break
            
            # Create paper trade
            trade_id = self.paper_trading.create_trade_from_signal(signal.to_dict())
            
            if trade_id:
                self.trades_today += 1
                logger.info("Auto-trade created: %s | %s... | Trade #%s",
                           signal['signal_type'], signal['title'][:50], trade_id)
                
                # Send confirmation
                self.alerter._send_message(
                    f"🤖 <b>AUTO-TRADE EXECUTED</b>\n\n"
                    f"Signal: {signal['signal_type']}\n"
                    f"Market: {signal['title'][:60]}...\n"
                    f"Expected Return: {signal['expected_return']:.2%}\n"
                    f"Trade #{trade_id}\n"
                    f"Daily Trades: {self.trades_today}/{self.config.get('max_daily_trades', 10)}"
                )
    
    def _is_signal_traded(self, signal_id: int) -> bool:
        """Check if signal already has a trade."""
        with sqlite3.connect(self.db.db_path) as conn:
            result = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE signal_id = ?",
                (signal_id,)
            ).fetchone()
            return result[0] > 0
    
    def _check_risk_limits(self) -> bool:
        """Check if any risk limits are breached."""
        portfolio = self.paper_trading.get_portfolio_summary()
        
        # Daily loss limit
        daily_loss_limit = self.config.get('daily_loss_limit', 0.10)
        if self.daily_pnl < -self.config.get('initial_capital', 10000) * daily_loss_limit:
            if not hasattr(self, '_risk_alert_sent'):
                self.alerter._send_message(
                    f"🛑 <b>RISK LIMIT BREACHED</b>\n\n"
                    f"Daily loss limit hit: {self.daily_pnl:.2%}\n"
                    f"Auto-trading paused for 5 minutes."
                )
                self._risk_alert_sent = True
            return True
        
        # Max drawdown
        max_drawdown = self.config.get('max_drawdown', 0.20)
        if portfolio['total_return'] < -max_drawdown:
            if not hasattr(self, '_drawdown_alert_sent'):
                self.alerter._send_message(
                    f"🛑 <b>MAX DRAWDOWN BREACHED</b>\n\n"
                    f"Current drawdown: {portfolio['total_return']:.2%}\n"
                    f"Auto-trading stopped. Manual review required."
                )
                self._drawdown_alert_sent = True
            self.running = False
            return True
        
        return False
    
    def _maybe_take_snapshot(self):
        """Take portfolio snapshot every hour."""
        now = datetime.now()
        if self.last_snapshot is None or (now - self.last_snapshot).hours >= 1:
            self.paper_trading.record_portfolio_snapshot()
            self.last_snapshot = now
            logger.info("Portfolio snapshot taken")
    
    def _maybe_send_eod_report(self):
        """Send end-of-day report."""
        now = datetime.now()
        if now.hour == 21 and now.minute < 5:  # 9:00 PM
            if not hasattr(self, '_eod_sent_today'):
                self._send_eod_report()
                self._eod_sent_today = True
        elif now.hour == 0:
            self._eod_sent_today = False  # Reset for next day
    
    def _send_eod_report(self):
        """Generate and send end-of-day report."""
        portfolio = self.paper_trading.get_portfolio_summary()
        
        message = f"""
📊 <b>END OF DAY REPORT</b>

<b>Portfolio Summary:</b>
  Capital: ${portfolio['current_capital']:,.2f}
  P&L: ${portfolio['total_pnl']:,.2f} ({portfolio['total_return']:.2%})
  Win Rate: {portfolio['win_rate']:.1%}
  Avg Return: {portfolio['avg_return']:.2%}

<b>Today's Activity:</b>
  Trades: {self.trades_today}
  Open Exposure: ${portfolio['open_exposure']:,.2f}

<b>Available Capital:</b> ${portfolio['available_capital']:,.2f}
        """
        
        self.alerter._send_message(message)
        logger.info("EOD report sent")
    
    def _send_startup_message(self):
        """Send automation startup message."""
        self.alerter._send_message(
            f"🤖 <b>PYTHIA AUTOMATION STARTED</b>\n\n"
            f"Mode: Paper Trading\n"
            f"Initial Capital: ${self.config.get('initial_capital', 10000):,.2f}\n"
            f"Max Daily Trades: {self.config.get('max_daily_trades', 10)}\n"
            f"Auto-trading from HIGH/CRITICAL signals enabled."
        )
    
    def _send_shutdown_message(self):
        """Send automation shutdown message."""
        portfolio = self.paper_trading.get_portfolio_summary()
        self.alerter._send_message(
            f"🛑 <b>PYTHIA AUTOMATION STOPPED</b>\n\n"
            f"Final Capital: ${portfolio['current_capital']:,.2f}\n"
            f"Total Return: {portfolio['total_return']:.2%}\n"
            f"Total Trades: {portfolio['total_trades']}"
        )
