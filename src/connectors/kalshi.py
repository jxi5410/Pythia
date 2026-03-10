"""
Kalshi Connector — v2 API
Uses httpx with retry logic, cursor-based pagination, market + trade fetching.
No auth required for public endpoints.
"""
import httpx
import time
import logging
from typing import List, Dict, Optional, Iterator
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = 1.0
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
                raise
            wait = RETRY_BACKOFF * (2 ** attempt)
            logger.warning("Kalshi request failed (attempt %d/%d): %s — retrying in %.1fs",
                           attempt + 1, MAX_RETRIES, exc, wait)
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


class KalshiConnector:
    """
    Kalshi v2 API connector.
    Base URL: https://api.elections.kalshi.com/trade-api/v2
    Public endpoints only (no auth needed).
    """

    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

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
        Fetch active markets from Kalshi v2 API.
        Returns normalised market dicts compatible with PythiaDB.
        """
        try:
            params = {
                "status": "open",
                "limit": min(limit, 200),
            }
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.BASE_URL}/markets", params=params)
            data = resp.json()
            raw_markets = data.get("markets", [])

            return [self._normalise_market(m) for m in raw_markets[:limit]]

        except Exception as exc:
            logger.error("Kalshi get_active_markets failed: %s", exc)
            return []

    def iter_markets(self, *, page_size: int = 200, max_pages: int = 20) -> Iterator[Dict]:
        """
        Iterate over all active markets using cursor-based pagination.
        Yields normalised market dicts.
        """
        cursor = None
        for _ in range(max_pages):
            try:
                params: Dict = {
                    "status": "open",
                    "limit": page_size,
                }
                if cursor:
                    params["cursor"] = cursor

                resp = _request_with_retry(self.client, "GET",
                                           f"{self.BASE_URL}/markets", params=params)
                data = resp.json()
                raw_markets = data.get("markets", [])

                if not raw_markets:
                    break

                for m in raw_markets:
                    yield self._normalise_market(m)

                cursor = data.get("cursor")
                if not cursor:
                    break

            except Exception as exc:
                logger.error("Kalshi iter_markets failed: %s", exc)
                break

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------

    def get_market_price(self, ticker: str) -> Optional[Dict]:
        """
        Get current price for a specific market.
        Kalshi prices are in cents (0-100), we normalise to 0-1.
        """
        try:
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.BASE_URL}/markets/{ticker}")
            data = resp.json()
            market = data.get("market", data)

            yes_price = float(market.get("last_price", 50)) / 100
            yes_bid = float(market.get("yes_bid", market.get("last_price", 50))) / 100
            yes_ask = float(market.get("yes_ask", market.get("last_price", 50))) / 100

            return {
                "market_id": ticker,
                "yes_price": yes_price,
                "no_price": 1 - yes_price,
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "spread": yes_ask - yes_bid,
                "volume": float(market.get("volume", 0) or 0),
                "open_interest": float(market.get("open_interest", 0) or 0),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            logger.error("Kalshi price fetch error for %s: %s", ticker, exc)
            return None

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def get_market_trades(self, ticker: str, limit: int = 200) -> List[Dict]:
        """
        Fetch recent trades for a specific market using cursor pagination.
        """
        try:
            params: Dict = {"ticker": ticker, "limit": min(limit, 500)}
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.BASE_URL}/markets/trades", params=params)
            data = resp.json()
            raw_trades = data.get("trades", [])
            return [self._normalise_trade(t) for t in raw_trades]

        except Exception as exc:
            logger.error("Kalshi get_market_trades(%s) failed: %s", ticker, exc)
            return []

    def get_recent_trades(self, limit: int = 200) -> List[Dict]:
        """
        Fetch recent trades across all markets.
        Uses cursor-based pagination, returns up to `limit` trades.
        """
        trades: List[Dict] = []
        cursor = None
        page_size = min(limit, 500)

        while len(trades) < limit:
            try:
                params: Dict = {"limit": page_size}
                if cursor:
                    params["cursor"] = cursor

                resp = _request_with_retry(self.client, "GET",
                                           f"{self.BASE_URL}/markets/trades", params=params)
                data = resp.json()
                raw_trades = data.get("trades", [])

                if not raw_trades:
                    break

                trades.extend(self._normalise_trade(t) for t in raw_trades)

                cursor = data.get("cursor")
                if not cursor:
                    break

            except Exception as exc:
                logger.error("Kalshi get_recent_trades failed: %s", exc)
                break

        return trades[:limit]

    def get_series_markets(self, series_ticker: str) -> List[Dict]:
        """Get all markets in a series (e.g. all markets under an event)."""
        try:
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.BASE_URL}/events/{series_ticker}")
            data = resp.json()
            raw_markets = data.get("markets", [])
            return [self._normalise_market(m) for m in raw_markets]
        except Exception as exc:
            logger.error("Kalshi series fetch error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_market(m: dict) -> Dict:
        """Map Kalshi v2 API fields to Pythia's internal format."""
        volume = float(m.get("volume", 0) or 0)
        return {
            "id": m.get("ticker") or m.get("id", ""),
            "source": "kalshi",
            "title": m.get("title") or m.get("subtitle") or "Unknown",
            "category": m.get("category") or m.get("series_ticker") or "General",
            "liquidity": volume * 0.1,  # Rough proxy — Kalshi doesn't expose liquidity directly
            "volume_24h": float(m.get("volume_24h", 0) or m.get("dollar_volume", 0) or volume),
            "description": m.get("rules_primary") or m.get("description") or "",
            "close_date": m.get("close_time") or m.get("expiration_time"),
            "created_at": m.get("open_time") or m.get("created_time") or datetime.now().isoformat(),
        }

    @staticmethod
    def _normalise_trade(t: dict) -> Dict:
        """Map Kalshi v2 trade to Pythia's internal trade format."""
        # Kalshi trades: taker_side is "yes" or "no"
        taker_side = (t.get("taker_side") or t.get("side") or "yes").lower()
        # Kalshi prices are in cents
        price_raw = float(t.get("yes_price", 0) or t.get("price", 0) or 0)
        price = price_raw / 100 if price_raw > 1 else price_raw

        return {
            "trade_id": t.get("id") or t.get("trade_id") or "",
            "market_id": t.get("ticker") or t.get("market_ticker") or "",
            "source": "kalshi",
            "timestamp": t.get("created_time") or t.get("ts") or datetime.now().isoformat(),
            "price": price,
            "amount": float(t.get("count", 0) or t.get("contracts", 0) or 0),
            "taker_side": taker_side,
            "maker_address": "",  # Kalshi doesn't expose wallet addresses
            "taker_address": "",
        }
