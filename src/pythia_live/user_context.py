"""
Per-User Context Manager — Maintains conversational state for each Telegram user.

Stores preferences, watchlists, recent messages, and active watches in
per-user JSON files under data/users/{user_id}.json.
"""

import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

USERS_DIR = os.path.join("data", "users")


@dataclass
class Watch:
    """An active asset watch with threshold."""
    asset: str
    threshold_pct: float = 1.0
    created_at: Optional[str] = None


@dataclass
class UserContext:
    """Per-user conversational state."""
    user_id: str
    preferences: Dict[str, Any] = field(default_factory=dict)
    watchlist: List[str] = field(default_factory=list)
    recent_messages: Deque[Dict[str, str]] = field(default_factory=lambda: deque(maxlen=10))
    active_watches: List[Watch] = field(default_factory=list)


class UserContextManager:
    """
    Manages per-user context backed by JSON files.

    Each user gets a file at data/users/{user_id}.json containing their
    preferences, watchlist, last 10 messages, and active watches.
    """

    def __init__(self, users_dir: str = USERS_DIR):
        self.users_dir = users_dir
        self._cache: Dict[str, UserContext] = {}

    def _path(self, user_id: str) -> str:
        """Return the file path for a user's context."""
        return os.path.join(self.users_dir, f"{user_id}.json")

    def get_context(self, user_id: str) -> UserContext:
        """
        Load or create per-user context.

        Returns:
            UserContext with preferences, watchlist, last 10 messages,
            and active watches.
        """
        if user_id in self._cache:
            return self._cache[user_id]

        ctx = UserContext(user_id=user_id)
        path = self._path(user_id)

        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                ctx.preferences = data.get("preferences", {})
                ctx.watchlist = data.get("watchlist", [])
                msgs = data.get("recent_messages", [])
                ctx.recent_messages = deque(msgs[-10:], maxlen=10)
                watches = data.get("active_watches", [])
                ctx.active_watches = [
                    Watch(
                        asset=w["asset"],
                        threshold_pct=w.get("threshold_pct", 1.0),
                        created_at=w.get("created_at"),
                    )
                    for w in watches
                ]
            except Exception as e:
                logger.warning("Failed to load context for user %s: %s", user_id, e)

        self._cache[user_id] = ctx
        return ctx

    def update_context(self, user_id: str, message: str, response: str) -> None:
        """
        Store a message+response pair for conversational continuity.

        Args:
            user_id: Telegram user ID.
            message: The user's message.
            response: Pythia's response.
        """
        ctx = self.get_context(user_id)
        ctx.recent_messages.append({
            "user": message,
            "pythia": response,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        self._save(ctx)

    def add_watch(self, user_id: str, asset: str, threshold_pct: float = 1.0) -> None:
        """
        Add an asset watch with a move threshold.

        Args:
            user_id: Telegram user ID.
            asset: Asset ticker or name to watch.
            threshold_pct: Percentage move threshold to trigger alert.
        """
        ctx = self.get_context(user_id)
        # Avoid duplicates
        for w in ctx.active_watches:
            if w.asset.lower() == asset.lower():
                w.threshold_pct = threshold_pct
                self._save(ctx)
                return
        ctx.active_watches.append(Watch(
            asset=asset,
            threshold_pct=threshold_pct,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))
        if asset.upper() not in [a.upper() for a in ctx.watchlist]:
            ctx.watchlist.append(asset.upper())
        self._save(ctx)

    def remove_watch(self, user_id: str, asset: str) -> bool:
        """
        Remove an asset watch.

        Returns:
            True if the watch was found and removed.
        """
        ctx = self.get_context(user_id)
        before = len(ctx.active_watches)
        ctx.active_watches = [
            w for w in ctx.active_watches
            if w.asset.lower() != asset.lower()
        ]
        if len(ctx.active_watches) < before:
            self._save(ctx)
            return True
        return False

    def get_watches(self, user_id: str) -> List[Watch]:
        """Return active watches for a user."""
        ctx = self.get_context(user_id)
        return list(ctx.active_watches)

    def _save(self, ctx: UserContext) -> None:
        """Persist user context to disk."""
        os.makedirs(self.users_dir, exist_ok=True)
        data = {
            "user_id": ctx.user_id,
            "preferences": ctx.preferences,
            "watchlist": ctx.watchlist,
            "recent_messages": list(ctx.recent_messages),
            "active_watches": [
                {
                    "asset": w.asset,
                    "threshold_pct": w.threshold_pct,
                    "created_at": w.created_at,
                }
                for w in ctx.active_watches
            ],
        }
        try:
            with open(self._path(ctx.user_id), "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save context for user %s: %s", ctx.user_id, e)
