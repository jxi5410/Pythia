"""
Quick test script for Polymarket WebSocket connector.

Tests real-time price streaming with a few liquid markets.
"""

import asyncio
import logging
from src.pythia_live.connectors.polymarket_ws import PolymarketWebSocketConnector

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Track updates
update_count = {"price": 0, "trade": 0, "orderbook": 0}

def on_price_update(data):
    """Handle price updates"""
    update_count["price"] += 1
    event_type = data.get("event_type", "unknown")
    
    if event_type == "price_change":
        logger.info(f"💰 PRICE: {data['market_id'][:12]}... @ {data['price']:.4f}")
    elif event_type == "best_bid_ask":
        logger.info(f"📊 BID/ASK: {data['market_id'][:12]}... {data['bid']:.4f}/{data['ask']:.4f} spread={data['spread']:.4f}")

def on_trade(data):
    """Handle trade executions"""
    update_count["trade"] += 1
    logger.info(f"🔄 TRADE: {data['market_id'][:12]}... {data['side']} {data['size']:.2f} @ {data['price']:.4f}")

def on_orderbook(data):
    """Handle orderbook snapshots"""
    update_count["orderbook"] += 1
    logger.info(f"📖 BOOK: {data['market_id'][:12]}... {len(data['bids'])} bids / {len(data['asks'])} asks")

async def test_websocket():
    """Test WebSocket connector with liquid markets"""
    
    # Real liquid markets (Trump deportation markets, Feb 2026)
    test_asset_ids = [
        "101676997363687199724245607342877036148401850938023978421879460310389391082353",  # Trump deport <250k (YES token)
        "13244681086321087932946246027856416106585284024824496763706748621681543444582",   # Trump deport 250k-500k (YES token)
    ]
    
    logger.info("=" * 60)
    logger.info("Polymarket WebSocket Connector Test")
    logger.info("=" * 60)
    logger.info(f"Testing with {len(test_asset_ids)} markets")
    logger.info("Will run for 30 seconds to collect data...")
    logger.info("")
    
    connector = PolymarketWebSocketConnector(
        on_price_update=on_price_update,
        on_trade=on_trade,
        on_orderbook=on_orderbook,
    )
    
    # Run for 30 seconds then stop
    try:
        connection_task = asyncio.create_task(connector.connect(test_asset_ids))
        await asyncio.sleep(30)
        await connector.disconnect()
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("Test Summary:")
        logger.info(f"  Price updates received: {update_count['price']}")
        logger.info(f"  Trades received: {update_count['trade']}")
        logger.info(f"  Orderbook snapshots: {update_count['orderbook']}")
        logger.info(f"  Total updates: {sum(update_count.values())}")
        logger.info("=" * 60)
        
        if sum(update_count.values()) > 0:
            logger.info("✅ WebSocket connector working!")
        else:
            logger.warning("⚠️  No updates received - check token IDs or market activity")
        
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        await connector.disconnect()
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(test_websocket())
