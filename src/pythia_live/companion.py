"""
Pythia Conversational Companion — The brain of the Telegram bot.

NOT a command parser. A conversational agent. Rule-based NLU with
template responses and dynamic data injection. No external LLM needed.

Personality: Sharp, concise, trader-fluent. No corporate speak.
Confident but precise. States confidence levels. Uses market shorthand.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .confluence import ConfluenceScorer, get_confluence_history
from .contract_detail import get_contract_detail
from .database import PythiaDB
from .regime import get_regime_state, format_regime_heatmap, RegimeState
from .track_record import get_track_record, TrackRecord
from .user_context import UserContextManager
from .watchlists import WatchlistManager

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Intent detection
# ------------------------------------------------------------------ #

_INTENT_PATTERNS: List[Tuple[str, List[str]]] = [
    ("status", [
        r"what.?s\s+moving", r"anything\s+(happening|interesting|going\s+on)",
        r"status", r"update", r"what.?s\s+up", r"what.?s\s+new",
        r"sitrep", r"brief\s*me",
    ]),
    ("fed", [
        r"\bfed\b", r"\bfomc\b", r"\brates?\b", r"interest\s+rate",
        r"powell", r"monetary\s+policy", r"rate\s+cut", r"rate\s+hike",
    ]),
    ("china", [
        r"\bchina\b", r"\btariff", r"\bpboc\b", r"\byuan\b",
        r"\bcny\b", r"trade\s+war", r"beijing",
    ]),
    ("crypto", [
        r"\bcrypto\b", r"\bbitcoin\b", r"\bbtc\b", r"\bethereum\b",
        r"\beth\b", r"\bdefi\b",
    ]),
    ("causal", [
        r"why\s+did", r"what\s+caused", r"what\s+happened",
        r"explain\s+the\s+move", r"what\s+drove",
    ]),
    ("watch", [
        r"watch\s+(\S+)", r"alert\s+me\s+on\s+(\S+)", r"track\s+(\S+)",
        r"follow\s+(\S+)",
    ]),
    ("unwatch", [
        r"unwatch\s+(\S+)", r"stop\s+watching\s+(\S+)",
        r"remove\s+watch\s+(\S+)", r"drop\s+(\S+)",
    ]),
    ("regime", [
        r"regime", r"\bmacro\b", r"what.?s\s+the\s+vibe",
        r"environment", r"market\s+state", r"big\s+picture",
    ]),
    ("proof", [
        r"proof", r"track\s+record", r"how\s+accurate",
        r"hit\s+rate", r"performance", r"how\s+good",
    ]),
    ("detail", [
        r"detail\s+(.+)", r"tell\s+me\s+about\s+(.+)",
        r"show\s+me\s+(.+)", r"info\s+on\s+(.+)", r"drill\s+into\s+(.+)",
    ]),
    ("briefing", [
        r"morning", r"briefing", r"daily", r"digest",
    ]),
    ("watchlist", [
        r"my\s+watch", r"watchlist", r"what\s+am\s+i\s+watching",
    ]),
]


def _detect_intent(text: str) -> Tuple[str, Optional[str]]:
    """
    Parse natural language into an intent + optional entity.

    Returns:
        (intent_name, extracted_entity_or_None)
    """
    text_lower = text.lower().strip()

    for intent, patterns in _INTENT_PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                entity = match.group(1) if match.lastindex and match.lastindex >= 1 else None
                return intent, entity

    # Fallback: try to match a known ticker/asset
    words = text_lower.split()
    if len(words) <= 3:
        # Short message — treat as a market query
        return "detail", text.strip()

    return "unknown", None


# ------------------------------------------------------------------ #
# Response formatting helpers
# ------------------------------------------------------------------ #

def _urgency_emoji(score: float) -> str:
    """Return urgency emoji based on score."""
    if score >= 0.7:
        return "\U0001f534"  # red circle
    elif score >= 0.4:
        return "\U0001f7e1"  # yellow circle
    else:
        return "\U0001f7e2"  # green circle


def _direction_emoji(direction: str) -> str:
    """Return direction emoji."""
    if direction == "bullish":
        return "\U0001f4c8"  # chart increasing
    elif direction == "bearish":
        return "\U0001f4c9"  # chart decreasing
    return "\u27a1\ufe0f"


def _fmt_confluence_event(evt: Dict) -> str:
    """Format a single confluence event into a compact line."""
    score = evt.get("confluence_score", 0)
    direction = evt.get("direction", "?")
    category = evt.get("event_category", "?")
    layers = evt.get("layer_count", 0)
    emoji = _urgency_emoji(score)
    dir_e = _direction_emoji(direction)
    cat_display = category.upper().replace("_", " ")
    return f"{emoji} **{cat_display}** {dir_e} {direction} — score {score:.0%}, {layers}/8 layers"


# ------------------------------------------------------------------ #
# PythiaCompanion
# ------------------------------------------------------------------ #

class PythiaCompanion:
    """
    Conversational AI engine for the Pythia Telegram bot.

    Takes natural language input, returns conversational response.
    Maintains per-user context. Rule-based NLU with template responses
    and dynamic data. No external LLM calls.

    Args:
        db_path: Path to the Pythia SQLite database.
    """

    def __init__(self, db_path: str = "data/pythia_live.db"):
        self.db_path = db_path
        self.db = PythiaDB(db_path)
        self.user_ctx = UserContextManager()
        self.watchlist_mgr = WatchlistManager()

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    async def respond(self, user_id: str, message: str) -> str:
        """
        Process a natural language message and return a conversational response.

        Args:
            user_id: Telegram user ID string.
            message: The user's message text.

        Returns:
            Markdown-formatted response string.
        """
        try:
            intent, entity = _detect_intent(message)

            handlers = {
                "status": self._handle_status,
                "fed": lambda uid, e: self._handle_category_filter(uid, "fed_rate"),
                "china": lambda uid, e: self._handle_category_filter(uid, "china_macro"),
                "crypto": lambda uid, e: self._handle_category_filter(uid, "crypto_regulation"),
                "causal": self._handle_causal,
                "watch": self._handle_watch,
                "unwatch": self._handle_unwatch,
                "regime": self._handle_regime,
                "proof": self._handle_proof,
                "detail": self._handle_detail,
                "briefing": self._handle_briefing,
                "watchlist": self._handle_watchlist,
                "unknown": self._handle_fallback,
            }

            handler = handlers.get(intent, self._handle_fallback)
            response = await handler(user_id, entity)

            # Store context for continuity
            self.user_ctx.update_context(user_id, message, response)
            return response

        except Exception as e:
            logger.exception("Error handling message from user %s: %s", user_id, e)
            return "Something broke on my end. Try again in a sec."

    # ------------------------------------------------------------------ #
    # Intent handlers
    # ------------------------------------------------------------------ #

    async def _handle_status(self, user_id: str, _entity: Optional[str]) -> str:
        """Active confluence events + top movers."""
        events = get_confluence_history(self.db, hours=24, min_score=0.3)

        if not events:
            return (
                "\U0001f7e2 Quiet across the board. No confluence events "
                "above 30% in the last 24h.\n\n"
                "I'll ping you when something lights up."
            )

        lines = [f"\u26a1 **{len(events)} active signal(s)** in the last 24h:\n"]
        for evt in events[:5]:
            lines.append(_fmt_confluence_event(evt))

        if len(events) > 5:
            lines.append(f"\n...and {len(events) - 5} more.")

        top = events[0]
        cat = top.get("event_category", "").upper().replace("_", " ")
        lines.append(f"\nHottest signal: **{cat}**. Want details?")
        return "\n".join(lines)

    async def _handle_category_filter(
        self, user_id: str, category: str
    ) -> str:
        """Filter confluence events for a specific category."""
        events = get_confluence_history(self.db, hours=48, min_score=0.0)
        filtered = [
            e for e in events if e.get("event_category") == category
        ]

        cat_display = category.upper().replace("_", " ")

        if not filtered:
            return (
                f"\U0001f7e2 No active signals on **{cat_display}** "
                f"in the last 48h. Quiet for now."
            )

        lines = [f"\u26a1 **{cat_display}** — {len(filtered)} event(s):\n"]
        for evt in filtered[:5]:
            lines.append(_fmt_confluence_event(evt))

        best = filtered[0]
        score = best.get("confluence_score", 0)
        if score >= 0.6:
            lines.append(
                f"\nThis is a strong signal. Historical patterns suggest "
                f"watching related assets closely."
            )

        return "\n".join(lines)

    async def _handle_causal(self, user_id: str, entity: Optional[str]) -> str:
        """Causal attribution — why did something move."""
        if not entity:
            # Check recent context for a subject
            ctx = self.user_ctx.get_context(user_id)
            if ctx.recent_messages:
                last = list(ctx.recent_messages)[-1]
                return (
                    "What move are you asking about? Give me a contract "
                    "name or ticker and I'll dig into the causal chain."
                )

        query = entity or ""
        detail = get_contract_detail(query, db=self.db)

        if detail.platform == "unknown" and detail.current_price == 0.0:
            return f"Can't find **{query}**. Try a contract title or ticker."

        lines = [f"\U0001f50d **{detail.title[:60]}**\n"]

        if detail.causal_attribution:
            ca = detail.causal_attribution
            lines.append(f"**Cause:** {ca.most_likely_cause}")
            if ca.causal_chain:
                lines.append(f"**Chain:** {ca.causal_chain[:120]}")
            lines.append(f"**Confidence:** {ca.confidence}")
            if ca.trading_implication:
                lines.append(f"\n\u26a1 {ca.trading_implication[:120]}")
        else:
            lines.append("No causal attribution data yet for this contract.")

        return "\n".join(lines)

    async def _handle_watch(self, user_id: str, entity: Optional[str]) -> str:
        """Add an asset to the user's watch list."""
        if not entity:
            return "Watch what? Give me a ticker or contract name."

        asset = entity.upper().strip()
        self.user_ctx.add_watch(user_id, asset, threshold_pct=1.0)
        return (
            f"Done. Watching **{asset}**. "
            f"I'll ping you if it moves >1% or if related signals develop."
        )

    async def _handle_unwatch(self, user_id: str, entity: Optional[str]) -> str:
        """Remove an asset watch."""
        if not entity:
            return "Unwatch what? Give me the ticker."

        asset = entity.upper().strip()
        removed = self.user_ctx.remove_watch(user_id, asset)
        if removed:
            return f"Stopped watching **{asset}**."
        return f"**{asset}** wasn't on your watch list."

    async def _handle_regime(self, user_id: str, _entity: Optional[str]) -> str:
        """Current regime state."""
        state = get_regime_state(db=self.db)
        regime_display = state.current_regime.upper().replace("_", " ")

        # Custom conversational format instead of raw heatmap
        emoji = _urgency_emoji(0.7 if state.current_regime != "calm" else 0.1)

        lines = [f"{emoji} **{regime_display}** regime."]
        lines.append(f"{state.regime_description}")

        # Top active categories
        active = sorted(
            state.category_activity.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        top_active = [(c, v) for c, v in active if v > 0.15][:4]
        if top_active:
            cats = ", ".join(
                f"{c.replace('_', ' ')} ({v:.0%})" for c, v in top_active
            )
            lines.append(f"\nActive clusters: {cats}")

        # Historical precedent
        if state.historical_comparisons:
            comp = state.historical_comparisons[0]
            moves = []
            for asset, outcome in list(comp.outcomes.items())[:3]:
                sign = "+" if outcome["median_move_pct"] > 0 else ""
                moves.append(
                    f"{asset} {sign}{outcome['median_move_pct']:.1f}%"
                )
            if moves:
                lines.append(
                    f"\nLast similar pattern: {', '.join(moves)} in 48h."
                )

        return "\n".join(lines)

    async def _handle_proof(self, user_id: str, _entity: Optional[str]) -> str:
        """Track record stats."""
        record = get_track_record(days=30, db=self.db)

        if record.total_events == 0:
            return (
                "\U0001f4ca No confluence events in the last 30 days to score. "
                "Need more data before I can show a track record."
            )

        lines = [
            f"\U0001f4ca Last {record.days} days: "
            f"**{record.total_events}** confluence alerts. "
            f"**{record.total_hits}** correct "
            f"(**{record.overall_hit_rate:.0%}**).",
        ]

        # Best and worst categories
        if record.category_stats:
            best = record.category_stats[0]
            worst = record.category_stats[-1] if len(record.category_stats) > 1 else None
            lines.append(
                f"Best: {best.category} ({best.hit_rate:.0%})."
            )
            if worst and worst.category != best.category:
                lines.append(
                    f"Worst: {worst.category} ({worst.hit_rate:.0%})."
                )

        if record.avg_lead_time_hours > 0:
            lines.append(
                f"Avg lead time: **{record.avg_lead_time_hours:.1f}hrs**."
            )

        return " ".join(lines)

    async def _handle_detail(self, user_id: str, entity: Optional[str]) -> str:
        """Contract detail view."""
        if not entity:
            return "Detail on what? Give me a contract name or ticker."

        detail = get_contract_detail(entity.strip(), db=self.db)

        if detail.platform == "unknown" and detail.current_price == 0.0:
            return f"Can't find **{entity}**. Try a market title or slug."

        lines = [f"\U0001f4cb **{detail.title[:60]}**"]
        lines.append(f"Platform: {detail.platform} | Category: {detail.category}")

        # Price
        price_str = f"Price: **{detail.current_price:.2f}**"
        if detail.delta_24h is not None:
            sign = "+" if detail.delta_24h >= 0 else ""
            price_str += f" ({sign}{detail.delta_24h:.2f} 24h)"
        lines.append(price_str)

        # Confluence
        if detail.active_layer_count > 0:
            lines.append(
                f"\n\u26a1 Confluence: **{detail.confluence_score:.0%}** "
                f"({detail.active_layer_count}/8 layers active)"
            )

        # Suggested assets
        if detail.suggested_assets:
            lines.append(
                f"\n\U0001f4b0 Trade: {', '.join(detail.suggested_assets[:5])}"
            )
            if detail.asset_rationale:
                lines.append(f"Why: {detail.asset_rationale[:80]}")

        return "\n".join(lines)

    async def _handle_briefing(self, user_id: str, _entity: Optional[str]) -> str:
        """Morning briefing."""
        return await self.morning_briefing(user_id)

    async def _handle_watchlist(self, user_id: str, _entity: Optional[str]) -> str:
        """Show user's active watches."""
        watches = self.user_ctx.get_watches(user_id)
        if not watches:
            return (
                "You're not watching anything yet. "
                "Say \"watch RTX\" or \"watch BTC\" to start."
            )

        lines = [f"\U0001f4cb **Your watches** ({len(watches)}):\n"]
        for w in watches:
            lines.append(f"  \u2022 **{w.asset}** (alert on >{w.threshold_pct:.0f}% move)")
        lines.append("\nSay \"unwatch X\" to remove one.")
        return "\n".join(lines)

    async def _handle_fallback(self, user_id: str, entity: Optional[str]) -> str:
        """Fallback for unrecognised input."""
        return (
            "Not sure what you're after. Try:\n"
            "\u2022 \"what's moving\" — active signals\n"
            "\u2022 \"fed\" / \"china\" / \"crypto\" — category filter\n"
            "\u2022 \"regime\" — macro state\n"
            "\u2022 \"watch RTX\" — track an asset\n"
            "\u2022 \"proof\" — my track record\n"
            "\u2022 \"detail fed-rate\" — contract deep dive\n"
            "\u2022 \"morning\" — daily briefing"
        )

    # ------------------------------------------------------------------ #
    # Proactive outputs
    # ------------------------------------------------------------------ #

    async def generate_proactive_alert(
        self, confluence_event: Dict
    ) -> Optional[str]:
        """
        Generate a proactive alert message from a confluence event.

        Args:
            confluence_event: Dict from get_confluence_history or ConfluenceEvent.

        Returns:
            Formatted alert string, or None if not worth alerting.
        """
        score = confluence_event.get("confluence_score", 0)
        if score < 0.4:
            return None

        category = confluence_event.get("event_category", "?")
        direction = confluence_event.get("direction", "?")
        layers = confluence_event.get("layer_count", 0)
        cat_display = category.upper().replace("_", " ")

        emoji = "\u26a1" if score >= 0.7 else _urgency_emoji(score)
        dir_e = _direction_emoji(direction)

        lines = [
            f"{emoji} **{cat_display}** {dir_e} {direction} "
            f"— {score:.0%} confluence, {layers}/8 layers agreeing.",
        ]

        # Add alert text snippet if available
        alert_text = confluence_event.get("alert_text", "")
        if alert_text:
            for line in alert_text.split("\n"):
                if "\u2022" in line or "agreeing" in line.lower():
                    lines.append(line.strip()[:100])
                    break

        lines.append("\nYou're seeing this before it hits the wire.")
        return "\n".join(lines)

    async def morning_briefing(self, user_id: str) -> str:
        """
        Generate a morning briefing for the user.

        Covers: regime state, top confluence events, user's watches.

        Args:
            user_id: Telegram user ID.

        Returns:
            Markdown-formatted briefing string.
        """
        lines = ["\u2615 **Morning Briefing**\n"]

        # Regime
        state = get_regime_state(db=self.db)
        regime_display = state.current_regime.upper().replace("_", " ")
        emoji = _urgency_emoji(0.7 if state.current_regime != "calm" else 0.1)
        lines.append(f"{emoji} Regime: **{regime_display}**")
        lines.append(f"{state.regime_description}\n")

        # Top events
        events = get_confluence_history(self.db, hours=24, min_score=0.3)
        if events:
            lines.append(f"\u26a1 **{len(events)} signal(s)** overnight:\n")
            for evt in events[:3]:
                lines.append(_fmt_confluence_event(evt))
        else:
            lines.append("\U0001f7e2 No major signals overnight.")

        # User watches
        watches = self.user_ctx.get_watches(user_id)
        if watches:
            assets = ", ".join(w.asset for w in watches[:5])
            lines.append(f"\n\U0001f440 Watching: {assets}")

        lines.append("\nWhat do you want to dig into?")
        return "\n".join(lines)

    async def weekly_digest(self, user_id: str) -> str:
        """
        Generate a weekly digest summary.

        Covers: track record, best calls, regime trajectory.

        Args:
            user_id: Telegram user ID.

        Returns:
            Markdown-formatted digest string.
        """
        lines = ["\U0001f4ca **Weekly Digest**\n"]

        # Track record
        record = get_track_record(days=7, db=self.db)
        if record.total_events > 0:
            lines.append(
                f"This week: **{record.total_events}** alerts, "
                f"**{record.total_hits}** correct "
                f"(**{record.overall_hit_rate:.0%}** hit rate)."
            )
            if record.avg_lead_time_hours > 0:
                lines.append(
                    f"Avg lead time: **{record.avg_lead_time_hours:.1f}hrs**."
                )
        else:
            lines.append("No confluence events this week.")

        # Best category
        if record.category_stats:
            best = record.category_stats[0]
            lines.append(
                f"\nBest category: **{best.category}** "
                f"({best.hit_rate:.0%} hit rate, {best.event_count} events)."
            )

        # Regime
        state = get_regime_state(db=self.db)
        regime_display = state.current_regime.upper().replace("_", " ")
        lines.append(f"\nCurrent regime: **{regime_display}**.")

        return "\n".join(lines)
