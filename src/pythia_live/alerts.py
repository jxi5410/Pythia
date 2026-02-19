"""
Telegram Alert System
Real-time notifications for trading signals
"""
import requests
import json
from typing import Optional, List
from datetime import datetime

from .database import PythiaDB
from .detector import Signal


class TelegramAlerter:
    """
    Sends real-time alerts via Telegram.
    
    Emoji legend:
    🔴 CRITICAL - Major opportunity, act now
    🟠 HIGH - Significant signal, worth monitoring
    🟡 MEDIUM - Notable activity
    🟢 LOW - Informational
    """
    
    SEVERITY_EMOJI = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🟢"
    }
    
    SIGNAL_EMOJI = {
        "PROBABILITY_SPIKE": "📊",
        "VOLUME_ANOMALY": "🔥",
        "MAKER_EDGE": "💰",
        "MOMENTUM_BREAKOUT": "🚀",
        "MOMENTUM_BREAKDOWN": "🔻",
        "ARBITRAGE": "⚡",
        "CORRELATION_DEV": "🔗"
    }
    
    def __init__(self, bot_token: str, chat_id: str, db: PythiaDB):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.db = db
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.enabled = bool(bot_token)
    
    def send_signal(self, signal: Signal, market_title: str, market_url: str = "") -> bool:
        """
        Send a signal alert to Telegram.
        
        Returns True if sent successfully.
        """
        if not self.enabled:
            print(f"[ALERT] Telegram not configured. Signal: {signal.description}")
            return False
        
        # Build message
        severity_emoji = self.SEVERITY_EMOJI.get(signal.severity, "⚪")
        signal_emoji = self.SIGNAL_EMOJI.get(signal.signal_type, "📈")
        
        message = f"""
{severity_emoji} <b>{signal.severity} ALERT</b> {signal_emoji}

<b>{market_title[:100]}</b>

{signal.description}

<b>Signal Type:</b> {signal.signal_type}
<b>Expected Return:</b> {signal.expected_return:.2%}
"""
        
        if signal.old_price and signal.new_price:
            change = ((signal.new_price - signal.old_price) / signal.old_price) if signal.old_price else 0
            message += f"""
<b>Price:</b> {signal.old_price:.2%} → {signal.new_price:.2%} ({change:+.1%})
"""
        
        if market_url:
            message += f"""
<a href="{market_url}">🔗 View on Platform</a>
"""
        
        message += f"""
<code>ID: {signal.market_id[:20]}...</code>
<code>Time: {signal.timestamp.strftime('%H:%M:%S')}</code>
"""
        
        return self._send_message(message)
    
    def send_summary(self, signals: List[Signal], timeframe_minutes: int = 60) -> bool:
        """Send a summary of multiple signals."""
        if not signals or not self.enabled:
            return False
        
        message = f"""
📊 <b>PYTHIA SUMMARY</b> (Last {timeframe_minutes}m)

<b>Total Signals:</b> {len(signals)}
"""
        
        # Count by severity
        by_severity = {}
        by_type = {}
        for s in signals:
            by_severity[s.severity] = by_severity.get(s.severity, 0) + 1
            by_type[s.signal_type] = by_type.get(s.signal_type, 0) + 1
        
        message += "\n<b>By Severity:</b>\n"
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if sev in by_severity:
                emoji = self.SEVERITY_EMOJI.get(sev, "")
                message += f"  {emoji} {sev}: {by_severity[sev]}\n"
        
        message += "\n<b>By Type:</b>\n"
        for typ, count in sorted(by_type.items(), key=lambda x: -x[1])[:5]:
            emoji = self.SIGNAL_EMOJI.get(typ, "📈")
            message += f"  {emoji} {typ}: {count}\n"
        
        return self._send_message(message)
    
    def send_startup_message(self, market_count: int) -> bool:
        """Send startup confirmation."""
        message = f"""
🎯 <b>PYTHIA LIVE - ACTIVE</b>

Monitoring {market_count} liquid markets
Scanning: Polymarket, Kalshi

<b>Signal Thresholds:</b>
  📊 Probability spikes: ≥5%
  🔥 Volume anomalies: ≥3x normal
  💰 Maker edge: ≥1% spread
  🚀 Momentum breakouts

<b>Cooldown:</b> 5 minutes between alerts

Ready to detect alpha.
"""
        return self._send_message(message)
    
    def _send_message(self, message: str) -> bool:
        """Send message via Telegram API."""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            return True
            
        except Exception as e:
            print(f"Telegram send failed: {e}")
            return False
