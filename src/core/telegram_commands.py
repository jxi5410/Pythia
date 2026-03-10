"""
Telegram Bot Commands — Extended command set for Pythia.

Builds on telegram_query.py with new commands:
  /confluence - Active confluence events
  /regime     - Current regime heatmap
  /proof      - Track record stats
  /detail <c> - Contract detail view
  /watchlist  - List / manage watchlists

Each command handler returns a formatted Telegram message string.
"""

import logging
import re
from datetime import datetime
from typing import List, Optional

from .confluence import get_confluence_history
from .contract_detail import get_contract_detail
from .database import PythiaDB
from .regime import get_regime_state, format_regime_heatmap
from .telegram_query import TelegramQueryHandler, _fmt_ts
from .track_record import get_track_record, format_track_record
from .watchlists import WatchlistManager

logger = logging.getLogger(__name__)


class ExtendedTelegramHandler(TelegramQueryHandler):
    """
    Extended Telegram command handler.

    Inherits all original commands from TelegramQueryHandler and adds
    new commands for confluence, regime, proof, detail, and watchlist.
    """

    def __init__(self, db_path: str = "data/pythia_live.db"):
        super().__init__(db_path)
        self._watchlist_mgr = WatchlistManager()

    def handle_command(self, command: str, args: str) -> str:
        """
        Process a Telegram command and return response text.

        Extended commands:
          /confluence             - Active confluence events
          /regime                 - Current regime heatmap
          /proof [days]           - Track record stats
          /detail <slug>          - Contract detail view
          /watchlist              - List watchlists
          /watchlist add <n> <c>  - Add watchlist

        Falls back to the original handler for unrecognised commands.
        """
        cmd = command.lower().lstrip("/")

        if cmd == "confluence":
            return self._cmd_confluence(args)
        elif cmd == "regime":
            return self._cmd_regime(args)
        elif cmd == "proof":
            return self._cmd_proof(args)
        elif cmd == "detail":
            return self._cmd_detail(args)
        elif cmd == "watchlist":
            return self._cmd_watchlist(args)
        else:
            # Fall back to parent handler
            return super().handle_command(command, args)

    # ------------------------------------------------------------------ #
    # /confluence
    # ------------------------------------------------------------------ #

    def _cmd_confluence(self, args: str) -> str:
        """
        Show active confluence events.

        Usage:
          /confluence          — all events (last 24h, score ≥ 0.3)
          /confluence 0.5      — only score ≥ 0.5
          /confluence 48h      — last 48 hours
        """
        min_score = 0.3
        hours = 24

        if args:
            # Parse min_score
            score_match = re.search(r"0\.\d+", args)
            if score_match:
                min_score = float(score_match.group())

            # Parse hours
            hours_match = re.search(r"(\d+)\s*h", args)
            if hours_match:
                hours = int(hours_match.group(1))

        events = get_confluence_history(self.db, hours=hours, min_score=min_score)

        if not events:
            return (
                f"⚡ No confluence events (score ≥{min_score:.0%}) "
                f"in the last {hours}h.\n"
                "Signals need ≥3 layers agreeing to trigger confluence."
            )

        lines = [
            f"⚡ CONFLUENCE EVENTS (last {hours}h, ≥{min_score:.0%})",
            f"Found {len(events)} event(s)",
            "",
        ]

        for evt in events[:8]:
            score = evt.get("confluence_score", 0)
            direction = evt.get("direction", "?")
            category = evt.get("event_category", "?")
            layer_count = evt.get("layer_count", 0)
            ts = evt.get("timestamp", "")

            # Severity emoji
            if score >= 0.7:
                emoji = "🔴"
            elif score >= 0.4:
                emoji = "🟡"
            else:
                emoji = "🟢"

            # Direction emoji
            dir_emoji = "📈" if direction == "bullish" else "📉" if direction == "bearish" else "➡️"

            ts_str = _fmt_ts(ts, "%m/%d %H:%M") if ts else "?"

            lines.append(
                f"{emoji} {category.upper().replace('_', ' ')} "
                f"{dir_emoji} {direction}"
            )
            lines.append(
                f"   Score: {score:.0%} | Layers: {layer_count}/8 | {ts_str}"
            )

            # Show alert text snippet
            alert = evt.get("alert_text", "")
            if alert:
                # Get the layer list line
                for line in alert.split("\n"):
                    if "agreeing" in line.lower() or "•" in line:
                        lines.append(f"   {line.strip()[:80]}")
                        break

            lines.append("")

        if len(events) > 8:
            lines.append(f"...and {len(events) - 8} more events")

        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # /regime
    # ------------------------------------------------------------------ #

    def _cmd_regime(self, _args: str) -> str:
        """
        Show current market regime as a text heatmap.

        Uses emoji blocks to visualise activity per category:
          ████████░░ = 0.8 activity (high)
          ██░░░░░░░░ = 0.2 activity (low)
        """
        state = get_regime_state(db=self.db)
        return format_regime_heatmap(state)

    # ------------------------------------------------------------------ #
    # /proof
    # ------------------------------------------------------------------ #

    def _cmd_proof(self, args: str) -> str:
        """
        Show track record summary.

        Usage:
          /proof        — last 30 days
          /proof 7      — last 7 days
          /proof 90     — last 90 days
        """
        days = 30
        if args:
            try:
                days = int(args.strip())
                days = max(1, min(365, days))
            except ValueError:
                pass

        record = get_track_record(days=days, db=self.db)
        return format_track_record(record)

    # ------------------------------------------------------------------ #
    # /detail
    # ------------------------------------------------------------------ #

    def _cmd_detail(self, args: str) -> str:
        """
        Show full contract detail.

        Usage:
          /detail fed-rate-cut-june
          /detail Bitcoin above 100K
        """
        if not args:
            return "Usage: /detail <contract slug or title>\nExample: /detail fed-rate-cut"

        slug = args.strip()
        detail = get_contract_detail(slug, db=self.db)

        if detail.platform == "unknown" and detail.current_price == 0.0:
            return f"❌ Contract not found: {slug}\nTry a market title or ID."

        lines = [
            f"📋 {detail.title}",
            f"Platform: {detail.platform} | Category: {detail.category}",
            "",
        ]

        # Price info
        price_str = f"Price: {detail.current_price:.2f}"
        if detail.delta_24h is not None:
            sign = "+" if detail.delta_24h >= 0 else ""
            price_str += f" ({sign}{detail.delta_24h:.2f} 24h)"
        lines.append(price_str)

        if detail.volume_24h > 0:
            lines.append(f"Volume: ${detail.volume_24h:,.0f}")

        # Cross-platform prices
        if detail.cross_platform_prices:
            lines.append("")
            lines.append("Cross-Platform:")
            for platform_key, price in detail.cross_platform_prices.items():
                lines.append(f"  • {platform_key}: {price:.4f}")

        # Confluence status
        lines.append("")
        active_layers = [l for l in detail.confluence_layers if l.active]
        if active_layers:
            lines.append(
                f"⚡ Confluence: {detail.confluence_score:.0%} "
                f"({detail.active_layer_count}/8 layers)"
            )
            for ls in active_layers:
                dir_emoji = "📈" if ls.direction == "bullish" else "📉" if ls.direction == "bearish" else "➡️"
                lines.append(
                    f"  {dir_emoji} {ls.layer}: {ls.confidence:.0%} "
                    f"— {ls.description[:50]}"
                )
        else:
            lines.append("⚡ Confluence: No active layers")

        # Causal attribution
        if detail.causal_attribution:
            ca = detail.causal_attribution
            lines.append("")
            lines.append(f"🔍 Cause: {ca.most_likely_cause[:80]}")
            lines.append(f"   Confidence: {ca.confidence}")
            if ca.trading_implication:
                lines.append(f"   ⚡ {ca.trading_implication[:80]}")

        # Historical patterns
        if detail.historical_patterns:
            lines.append("")
            lines.append("📊 Historical Patterns:")
            for pm in detail.historical_patterns[:3]:
                lines.append(
                    f"  • {pm.direction} ({pm.spike_count}x): "
                    f"avg {pm.avg_magnitude:.1%} move, "
                    f"{pm.hit_rate:.0%} hit rate"
                )
                if pm.time_to_resolution_hours > 0:
                    lines.append(
                        f"    Resolves in ~{pm.time_to_resolution_hours:.0f}h"
                    )

        # Suggested assets
        if detail.suggested_assets:
            lines.append("")
            lines.append(
                f"💰 Trade: {', '.join(detail.suggested_assets[:5])}"
            )
            if detail.asset_rationale:
                lines.append(f"   Why: {detail.asset_rationale[:80]}")

        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # /watchlist
    # ------------------------------------------------------------------ #

    def _cmd_watchlist(self, args: str) -> str:
        """
        Manage watchlists.

        Usage:
          /watchlist                        — list all watchlists
          /watchlist add <name> <contracts> — create or add to watchlist
          /watchlist remove <name>          — delete watchlist
        """
        if not args:
            return self._watchlist_list()

        parts = args.strip().split(maxsplit=1)
        sub_cmd = parts[0].lower()
        sub_args = parts[1] if len(parts) > 1 else ""

        if sub_cmd == "add":
            return self._watchlist_add(sub_args)
        elif sub_cmd in ("remove", "delete", "rm"):
            return self._watchlist_remove(sub_args)
        else:
            # Treat as a watchlist name to view
            return self._watchlist_view(args.strip())

    def _watchlist_list(self) -> str:
        """List all watchlists."""
        watchlists = self._watchlist_mgr.list_watchlists()

        if not watchlists:
            return (
                "📋 No watchlists yet.\n"
                "Create one: /watchlist add <name> <contract1> <contract2> ..."
            )

        lines = ["📋 WATCHLISTS", ""]
        for wl in watchlists:
            count = len(wl.contracts)
            updated = (
                _fmt_ts(wl.updated_at, "%m/%d") if wl.updated_at else "?"
            )
            lines.append(f"• {wl.name} ({count} contracts, updated {updated})")

        lines.append("")
        lines.append("View: /watchlist <name>")
        lines.append("Add: /watchlist add <name> <contracts...>")
        return "\n".join(lines)

    def _watchlist_add(self, args: str) -> str:
        """Add or create a watchlist."""
        if not args:
            return "Usage: /watchlist add <name> <contract1> <contract2> ..."

        parts = args.split()
        name = parts[0]
        contracts = parts[1:] if len(parts) > 1 else []

        existing = self._watchlist_mgr.get(name)
        if existing:
            if contracts:
                self._watchlist_mgr.add_contracts(name, contracts)
                total = len(existing.contracts) + len(contracts)
                return f"✅ Added {len(contracts)} contract(s) to '{name}' (total: {total})"
            else:
                return f"Watchlist '{name}' already exists with {len(existing.contracts)} contracts."
        else:
            self._watchlist_mgr.create(name, contracts)
            return f"✅ Created watchlist '{name}' with {len(contracts)} contract(s)"

    def _watchlist_remove(self, args: str) -> str:
        """Remove a watchlist."""
        name = args.strip()
        if not name:
            return "Usage: /watchlist remove <name>"

        if self._watchlist_mgr.delete(name):
            return f"🗑 Deleted watchlist '{name}'"
        else:
            return f"Watchlist '{name}' not found."

    def _watchlist_view(self, name: str) -> str:
        """View contracts in a watchlist."""
        wl = self._watchlist_mgr.get(name)
        if not wl:
            return f"Watchlist '{name}' not found.\nList all: /watchlist"

        if not wl.contracts:
            return (
                f"📋 {wl.name} — empty\n"
                f"Add contracts: /watchlist add {wl.name} <contract1> ..."
            )

        lines = [f"📋 {wl.name} ({len(wl.contracts)} contracts)", ""]
        for slug in wl.contracts:
            lines.append(f"  • {slug}")

        return "\n".join(lines)


# ------------------------------------------------------------------ #
# Convenience function (drop-in replacement for telegram_query)
# ------------------------------------------------------------------ #

def handle_extended_command(
    message_text: str,
    db_path: str = "data/pythia_live.db",
) -> str:
    """
    Convenience function for Telegram bot integration.

    Handles all original + extended commands.

    Usage in your Telegram bot::

        from pythia_live.telegram_commands import handle_extended_command

        if message.startswith('/'):
            response = handle_extended_command(message)
            bot.send_message(chat_id, response)
    """
    parts = message_text.split(maxsplit=1)
    command = parts[0] if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    handler = ExtendedTelegramHandler(db_path)
    return handler.handle_command(command, args)
