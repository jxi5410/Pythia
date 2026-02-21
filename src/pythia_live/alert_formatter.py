"""
Alert Formatter — Formats causal attribution results into Telegram messages.
"""
from typing import Dict, Optional
from .equities import format_correlation_alert


def format_alert(alert: Dict, pattern_insight: Optional[str] = None) -> str:
    """Format a pipeline alert dict into a clean Telegram message."""
    severity_emoji = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🟢",
    }
    emoji = severity_emoji.get(alert.get("severity", ""), "⚪")

    title = alert.get("market_title", "Unknown Market")
    direction = alert.get("direction", "?")
    magnitude = alert.get("magnitude", 0)
    price_before = alert.get("price_before", 0)
    price_after = alert.get("price_after", 0)
    volume = alert.get("volume", 0)

    sign = "+" if direction == "up" else "-"
    vol_str = f"${volume:,.0f}" if volume else "N/A"

    attr = alert.get("attribution", {})
    cause = attr.get("most_likely_cause", "Unknown")
    chain = attr.get("causal_chain", "")
    confidence = attr.get("confidence", "N/A")
    duration = attr.get("expected_duration", "N/A")
    trading = attr.get("trading_implication", "")

    lines = [
        f"{emoji} SPIKE ALERT — {title}",
        "",
        f"📊 {sign}{magnitude:.0%} in 1h | ${price_before:.2f} → ${price_after:.2f} | Vol: {vol_str}",
        "",
        f"🧠 CAUSE: {cause}",
    ]

    if chain:
        lines.append(f"⛓️ CHAIN: {chain}")

    lines.append(f"📊 CONFIDENCE: {confidence}")
    lines.append(f"⏱️ DURATION: {duration}")

    if trading:
        lines.append(f"💰 TRADING: {trading}")

    if pattern_insight:
        lines.append("")
        lines.append(f"📈 PATTERN: {pattern_insight}")

    # Cross-asset correlation section
    correlation = alert.get("correlation")
    if correlation:
        corr_text = format_correlation_alert(correlation)
        if corr_text:
            lines.append("")
            lines.append(corr_text)

    return "\n".join(lines)
