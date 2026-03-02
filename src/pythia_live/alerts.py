"""
Telegram Alert System — Intelligence Briefing Format
Real-time notifications for trading signals + Query commands
"""
import logging
import requests
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

from .database import PythiaDB
from .detector import Signal
from .telegram_query import TelegramQueryHandler


class TelegramAlerter:
    """
    Sends real-time intelligence briefings via Telegram.

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

    SEVERITY_LABEL = {
        "CRITICAL": "CRITICAL",
        "HIGH": "HIGH",
        "MEDIUM": "MEDIUM",
        "LOW": "LOW",
    }

    SIGNAL_LABEL = {
        "PROBABILITY_SPIKE": "Probability Spike",
        "VOLUME_ANOMALY": "Volume Spike",
        "MAKER_EDGE": "Maker Edge",
        "MOMENTUM_BREAKOUT": "Upward Momentum",
        "MOMENTUM_BREAKDOWN": "Downward Momentum",
        "ARBITRAGE": "Arbitrage",
        "CORRELATION_DEV": "Correlation Deviation",
        "OPTIMISM_TAX": "Optimism Tax",
    }

    def __init__(self, bot_token: str, chat_id: str, db: PythiaDB):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.db = db
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.enabled = bool(bot_token)
        self.query_handler = TelegramQueryHandler(db.db_path) if db else None

    def handle_command(self, command: str, args: str = "") -> bool:
        """Handle query commands from Telegram."""
        if not self.enabled or not self.query_handler:
            return False

        response = self.query_handler.handle_command(command, args)
        return self._send_message(response, parse_mode=None)

    def send_signal(self, signal: Signal, market_title: str, market_url: str = "") -> bool:
        """Send a signal alert as an intelligence briefing."""
        if not self.enabled:
            logger.warning("Telegram not configured. Signal: %s", signal.description)
            return False

        if signal.severity in ("CRITICAL", "HIGH"):
            message = self._format_full_briefing(signal, market_title, market_url)
        else:
            message = self._format_short_briefing(signal, market_title, market_url)

        # Telegram limit: 4096 chars
        if len(message) > 4096:
            message = message[:4090] + "\n..."

        return self._send_message(message)

    def _format_full_briefing(self, signal: Signal, market_title: str, market_url: str) -> str:
        """Full intelligence briefing for CRITICAL/HIGH signals."""
        severity_emoji = self.SEVERITY_EMOJI.get(signal.severity, "⚪")
        signal_label = self.SIGNAL_LABEL.get(signal.signal_type, signal.signal_type)

        parts = []

        # Header
        parts.append(
            f"{severity_emoji} <b>{signal.severity} — {signal_label}</b>"
        )

        # Market title + price move
        title_display = (market_title or signal.market_title or "Unknown")[:100]
        parts.append(f'\n📊 "<b>{_escape_html(title_display)}</b>"')

        if signal.old_price is not None and signal.new_price is not None:
            old_pct = signal.old_price * 100
            new_pct = signal.new_price * 100
            change_pp = (signal.new_price - signal.old_price) * 100
            sign = "+" if change_pp >= 0 else ""
            timeframe = signal.metadata.get("timeframe", "")
            tf_str = f" in {timeframe}" if timeframe else ""
            parts.append(
                f"   {old_pct:.0f}% → {new_pct:.0f}% ({sign}{change_pp:.0f}pp){tf_str}"
            )

        # Asset class
        asset_class = signal.asset_class or "general"
        instruments = signal.instruments or ""
        why = signal.why_it_matters or ""
        parts.append(f"\n💼 <b>ASSET CLASS:</b> {asset_class.upper()}")
        if instruments:
            parts.append(f"   Instruments: {instruments}")
        if why:
            parts.append(f"   Why it matters: {why}")

        # Correlated markets
        if signal.correlated_markets:
            parts.append("\n🔗 <b>CORRELATED MARKETS:</b>")
            for cm in signal.correlated_markets[:3]:
                cm_title = _escape_html(cm.get("title", "")[:60])
                cm_price = cm.get("yes_price", 0)
                cm_change = cm.get("price_change_1h")
                if cm_change is not None:
                    arrow = "↑" if cm_change >= 0 else "↓"
                    parts.append(
                        f'   • "{cm_title}" — {cm_price:.0%} ({arrow}{abs(cm_change):.0%} today)'
                    )
                else:
                    parts.append(f'   • "{cm_title}" — {cm_price:.0%}')

        # News context
        if signal.news_context:
            parts.append("\n📰 <b>RECENT NEWS:</b>")
            for news in signal.news_context[:2]:
                news_title = _escape_html(news.get("title", "")[:80])
                parts.append(f"   • {news_title}")

        # Signal metadata
        parts.append(
            f"\n📈 Signal: {signal.signal_type} | Expected edge: {signal.expected_return:.1%}"
        )

        if market_url:
            parts.append(f'🔗 <a href="{market_url}">View on Platform</a>')

        return "\n".join(parts)

    def _format_short_briefing(self, signal: Signal, market_title: str, market_url: str) -> str:
        """Short format for MEDIUM/LOW signals."""
        severity_emoji = self.SEVERITY_EMOJI.get(signal.severity, "⚪")
        signal_label = self.SIGNAL_LABEL.get(signal.signal_type, signal.signal_type)

        title_display = _escape_html((market_title or signal.market_title or "Unknown")[:80])

        parts = [
            f"{severity_emoji} <b>{signal.severity} — {signal_label}</b>",
            f'\n📊 "<b>{title_display}</b>"',
        ]

        # Brief description
        if signal.signal_type == "VOLUME_ANOMALY":
            ratio = signal.metadata.get("volume_ratio", 0)
            vol = signal.metadata.get("current_volume", 0)
            parts.append(f"   Volume {ratio:.1f}x normal (${vol:,.0f} traded)")
        elif signal.old_price is not None and signal.new_price is not None:
            old_pct = signal.old_price * 100
            new_pct = signal.new_price * 100
            parts.append(f"   {old_pct:.0f}% → {new_pct:.0f}%")

        # Asset class one-liner
        asset_class = signal.asset_class or "general"
        instruments = signal.instruments or ""
        if instruments:
            parts.append(f"💼 {asset_class.upper()} → {instruments}")

        # Correlated count
        if signal.correlated_markets:
            n = len(signal.correlated_markets)
            parts.append(f"🔗 {n} correlated market{'s' if n != 1 else ''} also moving")

        if market_url:
            parts.append(f'🔗 <a href="{market_url}">View</a>')

        return "\n".join(parts)

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
            label = self.SIGNAL_LABEL.get(typ, typ)
            message += f"  {label}: {count}\n"

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

    def _send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send message via Telegram API."""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "disable_web_page_preview": True
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()

            return True

        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            return False


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
