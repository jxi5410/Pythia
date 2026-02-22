"""
Watchlist Manager — Stub for Phase 1 to flesh out.

Provides basic watchlist CRUD backed by a JSON file on disk.
Phase 1 (terminal.py) will extend this with interactive features.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_WATCHLISTS_FILE = os.path.join("data", "watchlists.json")


@dataclass
class Watchlist:
    """A named watchlist of prediction market contracts."""
    name: str
    contracts: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WatchlistManager:
    """
    Manages named watchlists backed by a JSON file.

    Each watchlist is a named list of contract slugs / market IDs.
    """

    def __init__(self, file_path: str = DEFAULT_WATCHLISTS_FILE):
        self.file_path = file_path
        self._watchlists: Dict[str, Watchlist] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        """Load watchlists from disk."""
        if not os.path.exists(self.file_path):
            self._watchlists = {}
            return

        try:
            with open(self.file_path, "r") as f:
                data = json.load(f)

            for name, info in data.items():
                self._watchlists[name] = Watchlist(
                    name=name,
                    contracts=info.get("contracts", []),
                    created_at=_parse_iso(info.get("created_at")),
                    updated_at=_parse_iso(info.get("updated_at")),
                )
        except Exception as e:
            logger.warning("Failed to load watchlists: %s", e)
            self._watchlists = {}

    def _save(self) -> None:
        """Persist watchlists to disk."""
        os.makedirs(os.path.dirname(self.file_path) or ".", exist_ok=True)
        data = {}
        for name, wl in self._watchlists.items():
            data[name] = {
                "contracts": wl.contracts,
                "created_at": wl.created_at.isoformat() if wl.created_at else None,
                "updated_at": wl.updated_at.isoformat() if wl.updated_at else None,
            }
        try:
            with open(self.file_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save watchlists: %s", e)

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    def list_watchlists(self) -> List[Watchlist]:
        """Return all watchlists."""
        return list(self._watchlists.values())

    def get(self, name: str) -> Optional[Watchlist]:
        """Get a watchlist by name."""
        return self._watchlists.get(name)

    def create(self, name: str, contracts: Optional[List[str]] = None) -> Watchlist:
        """
        Create a new watchlist or overwrite an existing one.

        Args:
            name: Watchlist name.
            contracts: Initial list of contract slugs.

        Returns:
            The created/updated Watchlist.
        """
        now = datetime.now(timezone.utc)
        wl = Watchlist(
            name=name,
            contracts=contracts or [],
            created_at=now,
            updated_at=now,
        )
        self._watchlists[name] = wl
        self._save()
        return wl

    def add_contracts(self, name: str, contracts: List[str]) -> Optional[Watchlist]:
        """
        Add contracts to an existing watchlist.

        Returns the updated watchlist, or None if not found.
        """
        wl = self._watchlists.get(name)
        if wl is None:
            return None

        for slug in contracts:
            if slug not in wl.contracts:
                wl.contracts.append(slug)

        wl.updated_at = datetime.now(timezone.utc)
        self._save()
        return wl

    def remove_contracts(self, name: str, contracts: List[str]) -> Optional[Watchlist]:
        """
        Remove contracts from an existing watchlist.

        Returns the updated watchlist, or None if not found.
        """
        wl = self._watchlists.get(name)
        if wl is None:
            return None

        wl.contracts = [c for c in wl.contracts if c not in contracts]
        wl.updated_at = datetime.now(timezone.utc)
        self._save()
        return wl

    def delete(self, name: str) -> bool:
        """Delete a watchlist by name. Returns True if deleted."""
        if name in self._watchlists:
            del self._watchlists[name]
            self._save()
            return True
        return False


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO datetime string, returning None on failure."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
