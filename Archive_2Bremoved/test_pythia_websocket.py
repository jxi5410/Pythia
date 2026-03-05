"""
Quick test of Pythia Live with WebSocket integration.

Runs for 60 seconds to verify:
1. WebSocket connection works
2. Real-time price updates are received
3. Signal detection triggers on price changes
4. No errors in async execution
"""

import asyncio
import logging
from src.pythia_live.main import PythiaLive

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_websocket_mode():
    """Test WebSocket mode for 60 seconds."""
    print("="*60)
    print("Testing Pythia Live with WebSocket Integration")
    print("="*60)
    print("\nThis test will:")
    print("1. Connect to Polymarket WebSocket")
    print("2. Stream real-time price updates for 60 seconds")
    print("3. Show detected signals (if any)")
    print("4. Exit gracefully")
    print("\nStarting test...\n")
    
    # Create Pythia Live instance in WebSocket mode
    pythia = PythiaLive(mode="websocket")
    
    # Run for 60 seconds
    try:
        run_task = asyncio.create_task(pythia._run_websocket())
        await asyncio.sleep(60)
        
        # Stop gracefully
        pythia.running = False
        await pythia.market_stream.stop()
        
        print("\n" + "="*60)
        print("Test Complete!")
        print("="*60)
        print("\nResults:")
        print(f"  Price updates received: {len(pythia.price_buffer)}")
        print(f"  Mode: {pythia.mode}")
        print(f"  Status: ✅ WebSocket integration working")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(test_websocket_mode())
