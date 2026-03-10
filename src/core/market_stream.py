"""
Market Stream Adapter — Unified interface for Polymarket data sources

Provides automatic failover between WebSocket (real-time) and HTTP (fallback).
Simplifies integration into Pythia Live pipeline.

Usage:
    stream = MarketStream(mode="websocket")  # or "http" or "auto"
    
    async def handle_price(data):
        print(f"Price update: {data}")
    
    await stream.start(on_price_update=handle_price)
"""

import asyncio
import logging
from typing import Callable, Optional, Dict, List
from datetime import datetime
import json

from .connectors.polymarket import PolymarketConnector
from .connectors.polymarket_ws import PolymarketWebSocketConnector

logger = logging.getLogger(__name__)


class MarketStream:
    """
    Unified market data stream with automatic HTTP/WebSocket failover.
    
    Modes:
    - "websocket": Real-time WebSocket only
    - "http": HTTP polling only (60s interval)
    - "auto": WebSocket primary, fallback to HTTP if fails
    """
    
    def __init__(
        self,
        mode: str = "auto",  # "websocket", "http", or "auto"
        poll_interval: int = 60,  # HTTP polling interval (seconds)
    ):
        self.mode = mode
        self.poll_interval = poll_interval
        self.is_running = False
        
        # Connectors
        self.http_connector = PolymarketConnector()
        self.ws_connector = None
        
        # Callbacks
        self.on_price_update: Optional[Callable[[Dict], None]] = None
        self.on_trade: Optional[Callable[[Dict], None]] = None
        self.on_orderbook: Optional[Callable[[Dict], None]] = None
        
        # Market tracking
        self.subscribed_markets: List[str] = []
        self._http_poll_task = None
    
    async def start(
        self,
        market_ids: Optional[List[str]] = None,
        on_price_update: Optional[Callable[[Dict], None]] = None,
        on_trade: Optional[Callable[[Dict], None]] = None,
        on_orderbook: Optional[Callable[[Dict], None]] = None,
    ):
        """
        Start market data stream.
        
        Args:
            market_ids: List of market condition IDs (or None for top N liquid markets)
            on_price_update: Callback for price updates
            on_trade: Callback for trade executions
            on_orderbook: Callback for orderbook snapshots
        """
        self.on_price_update = on_price_update
        self.on_trade = on_trade
        self.on_orderbook = on_orderbook
        self.is_running = True
        
        # Get markets to subscribe to
        if market_ids is None:
            market_ids = await self._get_top_liquid_markets(limit=10)
        
        self.subscribed_markets = market_ids
        
        logger.info(f"Starting market stream in '{self.mode}' mode")
        logger.info(f"Subscribed to {len(market_ids)} markets")
        
        # Start appropriate connector(s)
        if self.mode == "websocket":
            await self._start_websocket()
        elif self.mode == "http":
            await self._start_http()
        elif self.mode == "auto":
            # Try WebSocket first, fall back to HTTP if it fails
            try:
                await self._start_websocket()
            except Exception as e:
                logger.warning(f"WebSocket failed, falling back to HTTP: {e}")
                await self._start_http()
    
    async def _start_websocket(self):
        """Start WebSocket streaming."""
        # Convert market condition IDs to token IDs
        token_ids = await self._get_token_ids(self.subscribed_markets)
        
        if not token_ids:
            raise ValueError("No token IDs available for WebSocket subscription")
        
        self.ws_connector = PolymarketWebSocketConnector(
            on_price_update=self._handle_ws_price_update,
            on_trade=self._handle_ws_trade,
            on_orderbook=self._handle_ws_orderbook,
        )
        
        logger.info(f"Starting WebSocket with {len(token_ids)} tokens")
        await self.ws_connector.connect(token_ids)
    
    async def _start_http(self):
        """Start HTTP polling."""
        logger.info(f"Starting HTTP polling (interval: {self.poll_interval}s)")
        self._http_poll_task = asyncio.create_task(self._http_poll_loop())
    
    async def _http_poll_loop(self):
        """HTTP polling loop."""
        while self.is_running:
            try:
                # Fetch latest prices for subscribed markets
                markets = self.http_connector.get_active_markets(limit=100)
                
                for market in markets:
                    if market["id"] in self.subscribed_markets:
                        # Convert to unified format
                        price_data = {
                            "market_id": market["id"],
                            "price": market.get("yes_price", 0.5),
                            "timestamp": datetime.now().isoformat(),
                            "event_type": "price_change",
                            "source": "http",
                        }
                        
                        if self.on_price_update:
                            self.on_price_update(price_data)
                
                logger.debug(f"HTTP poll complete: {len(markets)} markets fetched")
                
            except Exception as e:
                logger.error(f"HTTP poll error: {e}")
            
            await asyncio.sleep(self.poll_interval)
    
    async def _get_top_liquid_markets(self, limit: int = 10) -> List[str]:
        """Get top N liquid markets by volume."""
        try:
            markets = self.http_connector.get_active_markets(limit=limit)
            market_ids = [m["id"] for m in markets if m.get("liquidity", 0) > 1000]
            logger.info(f"Auto-selected {len(market_ids)} liquid markets")
            return market_ids[:limit]
        except Exception as e:
            logger.error(f"Failed to fetch liquid markets: {e}")
            return []
    
    async def _get_token_ids(self, market_ids: List[str]) -> List[str]:
        """Convert market condition IDs to token IDs for WebSocket."""
        try:
            markets = self.http_connector.get_active_markets(limit=100)
            token_ids = []
            
            for market in markets:
                if market["id"] in market_ids:
                    # Get slug to fetch full market details
                    slug = market.get("slug")
                    if slug:
                        # Fetch token IDs from market details
                        # Note: This requires the market to have clobTokenIds
                        # In the HTTP connector, we'd need to add a method to fetch this
                        # For now, just log that we need token IDs
                        pass
            
            # Fallback: fetch from API directly
            import requests
            response = requests.get(
                "https://gamma-api.polymarket.com/markets",
                params={"active": "true", "closed": "false", "limit": 100}
            )
            api_markets = response.json()
            
            for api_market in api_markets:
                condition_id = api_market.get("conditionId")
                if condition_id in market_ids:
                    clob_token_ids_str = api_market.get("clobTokenIds", "[]")
                    clob_token_ids = json.loads(clob_token_ids_str)
                    if clob_token_ids:
                        # Add YES token (first element)
                        token_ids.append(clob_token_ids[0])
            
            logger.info(f"Converted {len(market_ids)} markets to {len(token_ids)} tokens")
            return token_ids
            
        except Exception as e:
            logger.error(f"Failed to get token IDs: {e}")
            return []
    
    def _handle_ws_price_update(self, data: Dict):
        """Handle WebSocket price update."""
        if self.on_price_update:
            # Add source tag
            data["source"] = "websocket"
            self.on_price_update(data)
    
    def _handle_ws_trade(self, data: Dict):
        """Handle WebSocket trade."""
        if self.on_trade:
            data["source"] = "websocket"
            self.on_trade(data)
    
    def _handle_ws_orderbook(self, data: Dict):
        """Handle WebSocket orderbook."""
        if self.on_orderbook:
            data["source"] = "websocket"
            self.on_orderbook(data)
    
    async def stop(self):
        """Stop market data stream."""
        self.is_running = False
        
        if self.ws_connector:
            await self.ws_connector.disconnect()
        
        if self._http_poll_task:
            self._http_poll_task.cancel()
        
        logger.info("Market stream stopped")


# Convenience functions for quick integration

async def stream_top_markets(
    count: int = 10,
    on_price_update: Callable[[Dict], None] = None,
    mode: str = "auto",
):
    """
    Quick start: stream top N liquid markets.
    
    Example:
        async def handle_price(data):
            print(f"Price: {data}")
        
        await stream_top_markets(count=5, on_price_update=handle_price)
    """
    stream = MarketStream(mode=mode)
    await stream.start(
        market_ids=None,  # Auto-select top markets
        on_price_update=on_price_update,
    )
