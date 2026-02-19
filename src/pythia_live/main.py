"""
Pythia Live - Main Orchestrator
Real-time prediction market intelligence engine
"""
import time
import sys
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd

from .config import Config
from .database import PythiaDB
from .detector import SignalDetector, Signal
from .alerts import TelegramAlerter

# Import connectors
try:
    from .connectors.polymarket import PolymarketConnector
    HAS_POLYGON = True
except ImportError:
    HAS_POLYGON = False
    
try:
    from .connectors.kalshi import KalshiConnector
    HAS_KALSHI = True
except ImportError:
    HAS_KALSHI = False


class PythiaLive:
    """
    Main orchestrator for real-time prediction market monitoring.
    
    Flow:
    1. Fetch active markets from all sources
    2. Get current prices
    3. Store in database
    4. Run signal detection
    5. Send alerts for high-confidence signals
    6. Repeat every POLL_INTERVAL seconds
    """
    
    def __init__(self):
        self.config = Config()
        self.db = PythiaDB(self.config.DB_PATH)
        self.detector = SignalDetector(self.db, {
            'SIGNAL_COOLDOWN': self.config.SIGNAL_COOLDOWN,
            'PROBABILITY_SPIKE_THRESHOLD': self.config.PROBABILITY_SPIKE_THRESHOLD
        })
        self.alerter = TelegramAlerter(
            self.config.TELEGRAM_BOT_TOKEN,
            self.config.TELEGRAM_CHAT_ID,
            self.db
        )
        
        # Initialize connectors
        self.connectors = {}
        if HAS_POLYGON:
            self.connectors['polymarket'] = PolymarketConnector()
        if HAS_KALSHI:
            self.connectors['kalshi'] = KalshiConnector()
        
        self.running = False
        self.cycle_count = 0
        
    def run(self):
        """Main execution loop."""
        print("🎯 PYTHIA LIVE - Starting...")
        print(f"📡 Connectors: {', '.join(self.connectors.keys())}")
        
        self.running = True
        
        # Initial market discovery
        markets = self._discover_markets()
        print(f"📊 Found {len(markets)} liquid markets")
        
        # Send startup message
        self.alerter.send_startup_message(len(markets))
        
        print(f"\n⏱️  Polling every {self.config.POLL_INTERVAL}s")
        print("Press Ctrl+C to stop\n")
        
        try:
            while self.running:
                self.cycle_count += 1
                cycle_start = time.time()
                
                print(f"\n{'='*60}")
                print(f"🔄 Cycle {self.cycle_count} | {datetime.now().strftime('%H:%M:%S')}")
                print('='*60)
                
                # 1. Update market list (every 10 cycles)
                if self.cycle_count % 10 == 0:
                    markets = self._discover_markets()
                
                # 2. Fetch prices and detect signals
                all_signals = []
                for market in markets[:50]:  # Top 50 liquid markets
                    signals = self._process_market(market)
                    all_signals.extend(signals)
                
                # 3. Send batch summary if signals found
                if all_signals:
                    print(f"\n🚨 {len(all_signals)} signals detected")
                    self._handle_signals(all_signals)
                else:
                    print("\n✓ No significant signals")
                
                # 4. Sleep until next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.config.POLL_INTERVAL - elapsed)
                
                if sleep_time > 0:
                    print(f"⏳ Sleeping {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    
        except KeyboardInterrupt:
            print("\n\n👋 Stopping Pythia Live...")
            self.running = False
    
    def _discover_markets(self) -> List[Dict]:
        """Discover liquid markets from all sources."""
        all_markets = []
        
        for source, connector in self.connectors.items():
            try:
                print(f"🔍 Fetching {source} markets...")
                markets = connector.get_active_markets(limit=100)
                
                # Filter by liquidity
                liquid = [m for m in markets 
                         if m.get('liquidity', 0) >= self.config.MIN_LIQUIDITY]
                
                all_markets.extend(liquid)
                
                # Save to database
                for m in liquid:
                    self.db.save_market(m)
                    
                print(f"  ✓ {source}: {len(liquid)} liquid markets")
                
            except Exception as e:
                print(f"  ✗ {source} error: {e}")
        
        # Sort by liquidity
        all_markets.sort(key=lambda x: x.get('liquidity', 0), reverse=True)
        return all_markets
    
    def _process_market(self, market: Dict) -> List[Signal]:
        """
        Process a single market:
        1. Get current price
        2. Save to database
        3. Run signal detection
        """
        market_id = market['id']
        source = market['source']
        
        try:
            # Get connector
            connector = self.connectors.get(source)
            if not connector:
                return []
            
            # Fetch price
            price_data = connector.get_market_price(market_id)
            if not price_data:
                return []
            
            # Save price
            yes_price = price_data.get('yes_price') or price_data.get('mid_price', 0.5)
            no_price = price_data.get('no_price', 1 - yes_price)
            volume = price_data.get('volume', 0)
            
            self.db.save_price(market_id, yes_price, no_price, volume)
            
            # Get price history
            price_history = self.db.get_market_history(market_id, hours=24)
            
            # Combine current data with market info
            market_data = {
                **market,
                'yes_price': yes_price,
                'no_price': no_price,
                'yes_bid': price_data.get('yes_bid', yes_price),
                'yes_ask': price_data.get('yes_ask', yes_price),
                'spread': price_data.get('spread', 0),
                'volume': volume
            }
            
            # Run signal detection
            signals = self.detector.detect_all(market_data, price_history)
            
            return signals
            
        except Exception as e:
            print(f"  Error processing {market_id}: {e}")
            return []
    
    def _handle_signals(self, signals: List[Signal]):
        """Process detected signals: save, alert, log."""
        critical_count = 0
        high_count = 0
        
        for signal in signals:
            # Save to database
            signal_id = self.db.save_signal(
                market_id=signal.market_id,
                signal_type=signal.signal_type,
                severity=signal.severity,
                description=signal.description,
                old_price=signal.old_price,
                new_price=signal.new_price,
                expected_return=signal.expected_return
            )
            
            # Count by severity
            if signal.severity == "CRITICAL":
                critical_count += 1
            elif signal.severity == "HIGH":
                high_count += 1
            
            # Send Telegram alert for HIGH and CRITICAL
            if signal.severity in ["HIGH", "CRITICAL"]:
                # Get market info
                market_title = "Unknown"
                for conn_name, conn in self.connectors.items():
                    if conn_name in signal.market_id.lower():
                        market_title = f"{conn_name.upper()} Market"
                        break
                
                sent = self.alerter.send_signal(
                    signal=signal,
                    market_title=market_title,
                    market_url=self._get_market_url(signal.market_id)
                )
                
                # Mark as alerted
                status = "SENT" if sent else "FAILED"
                self.db.mark_alert_sent(signal_id, "telegram", status)
                
                if sent:
                    print(f"  📤 Alert sent: {signal.signal_type} ({signal.severity})")
        
        # Summary
        print(f"\n📊 Signal Summary:")
        print(f"  🔴 Critical: {critical_count}")
        print(f"  🟠 High: {high_count}")
        print(f"  🟡 Medium: {len([s for s in signals if s.severity == 'MEDIUM'])}")
    
    def _get_market_url(self, market_id: str) -> str:
        """Generate market URL based on ID pattern."""
        if 'polymarket' in market_id.lower() or len(market_id) == 64:
            return f"https://polymarket.com/event/{market_id[:16]}"
        elif 'kalshi' in market_id.lower():
            return f"https://kalshi.com/markets/{market_id}"
        return ""


def main():
    """Entry point."""
    pythia = PythiaLive()
    pythia.run()


if __name__ == "__main__":
    main()
