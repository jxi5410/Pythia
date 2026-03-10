"""
Polymarket WebSocket Connector — Real-time market data streaming

Connects to Polymarket's CLOB WebSocket API for sub-second price updates.
Replaces HTTP polling (60s) with real-time push-based updates.

WebSocket endpoint: wss://ws-subscriptions-clob.polymarket.com/ws/market
Documentation: https://docs.polymarket.com/market-data/websocket/overview
"""

import asyncio
import json
import logging
import ssl
from typing import Callable, Optional, Dict, List
from datetime import datetime
import websockets

logger = logging.getLogger(__name__)

class PolymarketWebSocketConnector:
    """
    Real-time Polymarket data via WebSocket CLOB API.
    
    Provides:
    - Sub-second price updates
    - Trade executions
    - Best bid/ask changes
    - Orderbook snapshots
    
    Usage:
        connector = PolymarketWebSocketConnector(
            on_price_update=lambda data: print(data),
            on_trade=lambda data: print(data)
        )
        await connector.connect(asset_ids=["token_id_1", "token_id_2"])
    """
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    HEARTBEAT_INTERVAL = 10  # Send PING every 10 seconds
    
    def __init__(
        self,
        on_price_update: Optional[Callable[[Dict], None]] = None,
        on_trade: Optional[Callable[[Dict], None]] = None,
        on_orderbook: Optional[Callable[[Dict], None]] = None,
    ):
        """
        Initialize WebSocket connector.
        
        Args:
            on_price_update: Callback for price changes (spike detection)
            on_trade: Callback for trade executions (volume analysis)
            on_orderbook: Callback for full orderbook snapshots (liquidity analysis)
        """
        self.on_price_update = on_price_update or (lambda x: None)
        self.on_trade = on_trade or (lambda x: None)
        self.on_orderbook = on_orderbook or (lambda x: None)
        
        self.ws = None
        self.asset_ids: List[str] = []
        self.is_running = False
        self._heartbeat_task = None
    
    async def connect(self, asset_ids: List[str]):
        """
        Connect to WebSocket and subscribe to specified markets.
        
        Args:
            asset_ids: List of Polymarket token IDs to subscribe to
        """
        self.asset_ids = asset_ids
        self.is_running = True
        
        logger.info(f"Connecting to Polymarket WebSocket: {self.WS_URL}")
        logger.info(f"Subscribing to {len(asset_ids)} markets")
        
        # Create SSL context (disable verification for now - SSL cert issues on some systems)
        # TODO: Use proper cert verification in production
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        try:
            async with websockets.connect(
                self.WS_URL,
                ping_interval=None,  # We'll handle heartbeat manually
                ssl=ssl_context,
            ) as ws:
                self.ws = ws
                
                # Send subscription message
                await self._subscribe(asset_ids)
                
                # Start heartbeat task
                self._heartbeat_task = asyncio.create_task(self._heartbeat())
                
                # Listen for messages
                await self._listen()
                
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            self.is_running = False
            raise
    
    async def _subscribe(self, asset_ids: List[str]):
        """Send subscription message to WebSocket."""
        subscription = {
            "assets_ids": asset_ids,
            "type": "market",
            "custom_feature_enabled": True,  # Enable best_bid_ask, new_market, market_resolved
        }
        
        await self.ws.send(json.dumps(subscription))
        logger.info(f"Sent subscription for {len(asset_ids)} assets")
    
    async def _heartbeat(self):
        """Send PING every 10 seconds to keep connection alive."""
        try:
            while self.is_running:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                if self.ws:
                    try:
                        await self.ws.send("PING")
                        logger.debug("Sent PING heartbeat")
                    except:
                        # Connection closed
                        break
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
    
    async def _listen(self):
        """Listen for incoming WebSocket messages."""
        try:
            async for message in self.ws:
                # Handle PONG response
                if message == "PONG":
                    logger.debug("Received PONG")
                    continue
                
                # Parse JSON message
                try:
                    data = json.loads(message)
                    
                    # Handle array responses (initial subscription confirmation)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                await self._handle_message(item)
                    elif isinstance(data, dict):
                        await self._handle_message(data)
                    else:
                        logger.debug(f"Unhandled message type: {type(data)}")
                        
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse message: {message[:100]}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self.is_running = False
        except Exception as e:
            logger.error(f"Error in listen loop: {e}")
            self.is_running = False
    
    async def _handle_message(self, data: Dict):
        """
        Route incoming messages to appropriate handlers.
        
        Message types:
        - price_change: Price level updates
        - last_trade_price: Trade executions
        - best_bid_ask: Best prices update
        - book: Full orderbook snapshot
        - new_market: New market created
        - market_resolved: Market resolution
        """
        event_type = data.get("event_type")
        
        if not event_type:
            # Initial subscription confirmation or other non-event message
            logger.debug(f"Non-event message: {data.get('type', 'unknown')}")
            return
        
        # Extract common fields
        asset_id = data.get("asset_id")
        timestamp = data.get("timestamp") or datetime.now().isoformat()
        
        if event_type == "price_change":
            # Price update - critical for spike detection
            price_data = {
                "market_id": asset_id,
                "price": float(data.get("price", 0)),
                "timestamp": timestamp,
                "event_type": "price_change",
                "hash": data.get("hash"),  # Transaction hash
            }
            self.on_price_update(price_data)
            logger.debug(f"Price change: {asset_id[:8]}... @ {price_data['price']:.4f}")
        
        elif event_type == "last_trade_price":
            # Trade execution - for volume analysis
            trade_data = {
                "market_id": asset_id,
                "price": float(data.get("price", 0)),
                "size": float(data.get("size", 0)),
                "side": data.get("side"),  # BUY or SELL
                "timestamp": timestamp,
                "event_type": "trade",
            }
            self.on_trade(trade_data)
            logger.debug(f"Trade: {asset_id[:8]}... {trade_data['side']} {trade_data['size']:.2f} @ {trade_data['price']:.4f}")
        
        elif event_type == "best_bid_ask":
            # Best prices - for spread analysis
            bid = float(data.get("bid", 0))
            ask = float(data.get("ask", 0))
            spread = ask - bid if ask and bid else 0
            
            price_data = {
                "market_id": asset_id,
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2 if bid and ask else 0,
                "spread": spread,
                "timestamp": timestamp,
                "event_type": "best_bid_ask",
            }
            self.on_price_update(price_data)
            logger.debug(f"Best bid/ask: {asset_id[:8]}... {bid:.4f}/{ask:.4f} (spread: {spread:.4f})")
        
        elif event_type == "book":
            # Full orderbook snapshot - for deep liquidity analysis
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            
            orderbook_data = {
                "market_id": asset_id,
                "bids": bids,  # List of [price, size]
                "asks": asks,
                "timestamp": timestamp,
                "event_type": "orderbook",
            }
            self.on_orderbook(orderbook_data)
            logger.debug(f"Orderbook: {asset_id[:8]}... {len(bids)} bids, {len(asks)} asks")
        
        elif event_type in ("new_market", "market_resolved"):
            # Market lifecycle events
            if asset_id:
                logger.info(f"Market event: {event_type} - {asset_id}")
            else:
                logger.debug(f"Market event: {event_type} (no asset_id)")
        
        else:
            logger.debug(f"Unhandled event type: {event_type}")
    
    async def subscribe_to_assets(self, asset_ids: List[str]):
        """Dynamically subscribe to additional markets without reconnecting."""
        if not self.ws or self.ws.closed:
            logger.error("WebSocket not connected")
            return
        
        subscription = {
            "assets_ids": asset_ids,
            "operation": "subscribe",
            "custom_feature_enabled": True,
        }
        
        await self.ws.send(json.dumps(subscription))
        self.asset_ids.extend(asset_ids)
        logger.info(f"Subscribed to {len(asset_ids)} additional assets")
    
    async def unsubscribe_from_assets(self, asset_ids: List[str]):
        """Dynamically unsubscribe from markets."""
        if not self.ws or self.ws.closed:
            logger.error("WebSocket not connected")
            return
        
        unsubscription = {
            "assets_ids": asset_ids,
            "operation": "unsubscribe",
        }
        
        await self.ws.send(json.dumps(unsubscription))
        self.asset_ids = [aid for aid in self.asset_ids if aid not in asset_ids]
        logger.info(f"Unsubscribed from {len(asset_ids)} assets")
    
    async def disconnect(self):
        """Close WebSocket connection gracefully."""
        self.is_running = False
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        
        if self.ws:
            try:
                await self.ws.close()
                logger.info("WebSocket disconnected")
            except:
                pass  # Already closed


# Helper function for easy integration
async def stream_polymarket_prices(
    asset_ids: List[str],
    on_price_update: Callable[[Dict], None],
    on_trade: Optional[Callable[[Dict], None]] = None,
):
    """
    Convenience function to stream Polymarket prices.
    
    Example:
        async def handle_price(data):
            print(f"Price: {data['price']}")
        
        await stream_polymarket_prices(
            asset_ids=["token_1", "token_2"],
            on_price_update=handle_price
        )
    """
    connector = PolymarketWebSocketConnector(
        on_price_update=on_price_update,
        on_trade=on_trade,
    )
    await connector.connect(asset_ids)
