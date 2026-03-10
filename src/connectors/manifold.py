"""
Manifold Markets Connector — v0 API
Free, open-source prediction markets with play-money and real-money pools.
https://docs.manifold.markets/api

No auth required for public endpoints.
"""
import httpx
import time
import logging
from typing import List, Dict, Optional
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
            logger.warning("Manifold request failed (attempt %d/%d): %s — retrying in %.1fs",
                           attempt + 1, MAX_RETRIES, exc, wait)
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


class ManifoldConnector:
    """
    Manifold Markets v0 API connector.
    Base URL: https://api.manifold.markets/v0
    Public endpoints only (no auth needed).
    
    Note: Manifold has play-money AND real-money (MANA/Sweepstakes) markets.
    """

    BASE_URL = "https://api.manifold.markets/v0"

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
        Fetch active markets from Manifold.
        Filters for real-money (prizeMarket or Sweepstakes) markets only.
        Returns normalised market dicts compatible with PythiaDB.
        """
        try:
            # Manifold API - simple params only
            params = {
                "limit": min(limit, 1000),
                # Note: Manifold doesn't support 'sort' or 'filter' params in v0 API
                # Returns all markets, we'll filter client-side
            }
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.BASE_URL}/markets", params=params)
            raw_markets = resp.json()

            # Filter for open BINARY markets only (skip resolved, non-binary)
            open_markets = [
                m for m in raw_markets 
                if not m.get('isResolved', False) and m.get('outcomeType') == 'BINARY'
            ]
            
            return [self._normalise_market(m) for m in open_markets[:limit]]

        except Exception as exc:
            logger.error("Manifold get_active_markets failed: %s", exc)
            return []

    def get_market(self, market_id: str) -> Optional[Dict]:
        """Get a single market by ID or slug."""
        try:
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.BASE_URL}/market/{market_id}")
            market = resp.json()
            return self._normalise_market(market)
        except Exception as exc:
            logger.error("Manifold get_market(%s) failed: %s", market_id, exc)
            return None

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------

    def get_market_price(self, market_id: str) -> Optional[Dict]:
        """
        Get current price for a specific market.
        Manifold uses probability (0-1) directly.
        """
        try:
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.BASE_URL}/market/{market_id}")
            market = resp.json()

            # Manifold binary markets have a 'probability' field
            prob = market.get('probability', 0.5)
            
            return {
                "market_id": market_id,
                "yes_price": prob,
                "no_price": 1 - prob,
                "yes_bid": prob,  # Manifold doesn't expose bid/ask explicitly
                "yes_ask": prob,
                "spread": 0.0,  # AMM pools have implicit spread in price impact
                "volume": float(market.get('volume', 0) or 0),
                "liquidity": float(market.get('totalLiquidity', 0) or market.get('liquidity', 0) or 0),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            logger.error("Manifold price fetch error for %s: %s", market_id, exc)
            return None

    # ------------------------------------------------------------------
    # Bets (Trades)
    # ------------------------------------------------------------------

    def get_market_bets(self, market_id: str, limit: int = 100) -> List[Dict]:
        """
        Fetch recent bets (trades) for a specific market.
        """
        try:
            params = {"limit": min(limit, 1000)}
            resp = _request_with_retry(self.client, "GET",
                                       f"{self.BASE_URL}/bets", params={"contractId": market_id, **params})
            raw_bets = resp.json()
            return [self._normalise_bet(b) for b in raw_bets[:limit]]

        except Exception as exc:
            logger.error("Manifold get_market_bets(%s) failed: %s", market_id, exc)
            return []

    def get_recent_trades(self, limit: int = 100) -> List[Dict]:
        """
        Fetch recent bets across all markets.
        Note: Manifold v0 API doesn't have a global trades endpoint,
        so this returns empty list. Use get_market_bets for specific markets.
        """
        logger.warning("Manifold doesn't support global trades endpoint - use get_market_bets instead")
        return []

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_market(m: dict) -> Dict:
        """Map Manifold API fields to Pythia's internal format."""
        # Manifold has multiple market types: BINARY, MULTIPLE_CHOICE, NUMERIC, etc.
        # We focus on BINARY for now
        outcome_type = m.get('outcomeType', 'BINARY')
        if outcome_type != 'BINARY':
            # Skip non-binary markets for now (could add support later)
            return {}
        
        volume = float(m.get('volume', 0) or 0)
        liquidity = float(m.get('totalLiquidity', 0) or m.get('liquidity', 0) or 0)
        
        return {
            "id": m.get('id', ''),
            "source": "manifold",
            "title": m.get('question', 'Unknown'),
            "category": m.get('groupSlugs', ['General'])[0] if m.get('groupSlugs') else 'General',
            "liquidity": liquidity,
            "volume_24h": float(m.get('volume24Hours', 0) or volume),
            "description": m.get('description', ''),
            "close_date": m.get('closeTime'),  # Unix timestamp in ms
            "created_at": m.get('createdTime') or datetime.now().isoformat(),
            "is_real_money": m.get('isRealMoney', False) or m.get('token') == 'MANA',
        }

    @staticmethod
    def _normalise_bet(b: dict) -> Dict:
        """Map Manifold bet to Pythia's internal trade format."""
        # Manifold bets have outcome ('YES' or 'NO') and probBefore/probAfter
        outcome = (b.get('outcome') or 'YES').upper()
        prob_after = float(b.get('probAfter', 0) or 0)
        amount_usd = float(b.get('amount', 0) or 0)  # In MANA or USD depending on market type
        
        return {
            "trade_id": b.get('id', ''),
            "market_id": b.get('contractId', ''),
            "source": "manifold",
            "timestamp": b.get('createdTime') or datetime.now().isoformat(),
            "price": prob_after,
            "amount": amount_usd,
            "taker_side": outcome.lower(),
            "maker_address": "",  # Manifold uses userIds, not wallet addresses
            "taker_address": b.get('userId', ''),
        }
