"""
Polymarket Connector — Gamma API + Data API
Uses httpx with retry logic, offset-based pagination, market + trade fetching.
"""
import httpx
import time
import logging
from typing import List, Dict, Optional, Iterator
from datetime import datetime

logger = logging.getLogger(__name__)

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0  # seconds, doubles each retry
REQUEST_TIMEOUT = 15.0


def _request_with_retry(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Make an HTTP request with exponential backoff retry."""
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise  # Don't retry client errors
            wait = RETRY_BACKOFF * (2 ** attempt)
            logger.warning("Polymarket request failed (attempt %d/%d): %s — retrying in %.1fs",
                           attempt + 1, MAX_RETRIES, exc, wait)
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


class PolymarketConnector:
    """
    Polymarket connector using:
    - Gamma API (https://gamma-api.polymarket.com) for market metadata
    - Data API (https://data-api.polymarket.com) for trades
    """

    GAMMA_URL = "https://gamma-api.polymarket.com"
    DATA_URL = "https://data-api.polymarket.com"

    def __init__(self):
        self.client = httpx.Client(
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------

    def get_active_markets(self, limit: int = 100) -> List[Dict]:
        """
        Fetch active markets from Gamma API.
        Returns list of normalised market dicts compatible with PythiaDB.
        """
        try:
            params = {
                "active": "true",
                "closed": "false",
                "limit": min(limit, 100),
                "offset": 0,
            }
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.GAMMA_URL}/markets", params=params)
            raw_markets = resp.json()
            # Gamma returns a plain list
            if isinstance(raw_markets, dict):
                raw_markets = raw_markets.get("data", raw_markets.get("markets", []))

            markets = []
            for m in raw_markets[:limit]:
                markets.append(self._normalise_market(m))
            return markets

        except Exception as exc:
            logger.error("Polymarket get_active_markets failed: %s", exc)
            return []

    def iter_markets(self, *, page_size: int = 100, max_pages: int = 20) -> Iterator[Dict]:
        """
        Iterate over all active markets using offset-based pagination.
        Yields normalised market dicts.
        """
        offset = 0
        for _ in range(max_pages):
            try:
                params = {
                    "active": "true",
                    "closed": "false",
                    "limit": page_size,
                    "offset": offset,
                }
                resp = _request_with_retry(self.client, "GET",
                                           f"{self.GAMMA_URL}/markets", params=params)
                raw = resp.json()
                if isinstance(raw, dict):
                    raw = raw.get("data", raw.get("markets", []))

                if not raw:
                    break

                for m in raw:
                    yield self._normalise_market(m)

                if len(raw) < page_size:
                    break
                offset += page_size

            except Exception as exc:
                logger.error("Polymarket iter_markets page offset=%d failed: %s", offset, exc)
                break

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------

    def get_market_price(self, market_id: str, slug: str = "") -> Optional[Dict]:
        """
        Get current price for a specific market via Gamma API.
        Tries slug first (more reliable), falls back to condition_id query param.
        """
        try:
            data = None
            # Try slug-based lookup first
            if slug:
                try:
                    resp = _request_with_retry(self.client, "GET",
                                               f"{self.GAMMA_URL}/markets",
                                               params={"slug": slug, "limit": 1})
                    results = resp.json()
                    if isinstance(results, list) and results:
                        data = results[0]
                    elif isinstance(results, dict):
                        items = results.get("data", results.get("markets", []))
                        if items:
                            data = items[0]
                except Exception:
                    pass

            # Fallback: query by condition_id
            if not data:
                try:
                    resp = _request_with_retry(self.client, "GET",
                                               f"{self.GAMMA_URL}/markets",
                                               params={"condition_id": market_id, "limit": 1})
                    results = resp.json()
                    if isinstance(results, list) and results:
                        data = results[0]
                    elif isinstance(results, dict):
                        items = results.get("data", results.get("markets", []))
                        if items:
                            data = items[0]
                except Exception:
                    pass

            if not data:
                return None

            # Extract prices from outcome_prices
            outcome_prices = data.get("outcomePrices")
            if outcome_prices:
                if isinstance(outcome_prices, str):
                    import json
                    outcome_prices = json.loads(outcome_prices)
                yes_price = float(outcome_prices[0]) if outcome_prices else 0.5
                no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 1 - yes_price
            else:
                yes_price = 0.5
                no_price = 0.5

            spread = float(data.get("spread", 0) or 0)

            return {
                "market_id": market_id,
                "yes_price": yes_price,
                "no_price": no_price,
                "yes_bid": yes_price - spread / 2,
                "yes_ask": yes_price + spread / 2,
                "no_bid": no_price - spread / 2,
                "no_ask": no_price + spread / 2,
                "mid_price": yes_price,
                "spread": spread,
                "volume": float(data.get("volume", 0) or 0),
                "liquidity": float(data.get("liquidity", 0) or 0),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            logger.error("Polymarket price fetch error for %s: %s", market_id, exc)
            return None

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def get_recent_trades(self, limit: int = 200) -> List[Dict]:
        """
        Fetch recent trades across all markets from the Data API.
        """
        try:
            params = {"limit": min(limit, 500)}
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.DATA_URL}/trades", params=params)
            raw = resp.json()
            if isinstance(raw, dict):
                raw = raw.get("data", raw.get("trades", []))
            return [self._normalise_trade(t) for t in raw]
        except Exception as exc:
            logger.error("Polymarket get_recent_trades failed: %s", exc)
            return []

    def get_market_trades(self, market_id: str, limit: int = 200) -> List[Dict]:
        """
        Fetch recent trades for a specific market from the Data API.
        Uses condition_id (= market_id in our schema) for filtering.
        """
        try:
            params = {"market": market_id, "limit": min(limit, 500)}
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.DATA_URL}/trades", params=params)
            raw = resp.json()
            if isinstance(raw, dict):
                raw = raw.get("data", raw.get("trades", []))
            return [self._normalise_trade(t) for t in raw]
        except Exception as exc:
            logger.error("Polymarket get_market_trades(%s) failed: %s", market_id, exc)
            return []

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_market(m: dict) -> Dict:
        """Map Gamma API fields to Pythia's internal format."""
        # Extract outcome prices directly from listing (avoids per-market API call)
        outcome_prices = m.get("outcomePrices") or m.get("outcome_prices")
        yes_price, no_price = 0.5, 0.5
        if outcome_prices:
            if isinstance(outcome_prices, str):
                import json
                try:
                    outcome_prices = json.loads(outcome_prices)
                except (json.JSONDecodeError, TypeError):
                    outcome_prices = None
            if outcome_prices and len(outcome_prices) >= 2:
                yes_price = float(outcome_prices[0])
                no_price = float(outcome_prices[1])

        return {
            "id": m.get("conditionId") or m.get("condition_id") or m.get("id", ""),
            "slug": m.get("slug") or "",
            "source": "polymarket",
            "title": m.get("question") or m.get("title") or "Unknown",
            "category": m.get("category") or m.get("groupSlug") or "General",
            "liquidity": float(m.get("liquidity", 0) or 0),
            "volume_24h": float(m.get("volume24hr", 0) or m.get("volume_24h", 0) or 0),
            "yes_price": yes_price,
            "no_price": no_price,
            "description": m.get("description") or "",
            "end_date": m.get("endDate") or m.get("end_date"),
            "created_at": m.get("createdAt") or m.get("created_at") or datetime.now().isoformat(),
        }

    @staticmethod
    def _normalise_trade(t: dict) -> Dict:
        """Map Data API trade to Pythia's internal trade format."""
        # Determine taker side: if outcome == "Yes" that means taker bought YES
        outcome = (t.get("outcome") or t.get("side") or "").upper()
        taker_side = "yes" if "YES" in outcome else "no"

        return {
            "trade_id": t.get("id") or t.get("tradeId") or "",
            "market_id": t.get("conditionId") or t.get("market") or t.get("condition_id") or "",
            "source": "polymarket",
            "timestamp": t.get("timestamp") or t.get("createdAt") or datetime.now().isoformat(),
            "price": float(t.get("price", 0) or 0),
            "amount": float(t.get("size", 0) or t.get("amount", 0) or 0),
            "taker_side": taker_side,
            "maker_address": t.get("makerAddress") or t.get("maker", ""),
            "taker_address": t.get("takerAddress") or t.get("taker", ""),
        }
