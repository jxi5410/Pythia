"""
Pythia Alert System — Signal Formatting & Dispatch

Stub module for future alert integrations (webhook, email, push).
Telegram bot removed — will be re-added when needed.
"""
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "MEDIUM": "🟡",
    "LOW": "🟢",
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


def format_signal(signal, market_title: str = "", market_url: str = "") -> str:
    """Format a signal as a human-readable string."""
    emoji = SEVERITY_EMOJI.get(signal.severity, "⚪")
    label = SIGNAL_LABEL.get(signal.signal_type, signal.signal_type)
    title = market_title or getattr(signal, "market_title", "Unknown")

    parts = [f"{emoji} {signal.severity} — {label}", f"  {title}"]

    if signal.old_price is not None and signal.new_price is not None:
        old_pct = signal.old_price * 100
        new_pct = signal.new_price * 100
        change = (signal.new_price - signal.old_price) * 100
        sign = "+" if change >= 0 else ""
        parts.append(f"  {old_pct:.0f}% → {new_pct:.0f}% ({sign}{change:.0f}pp)")

    if signal.expected_return:
        parts.append(f"  Expected edge: {signal.expected_return:.1%}")

    return "\n".join(parts)
