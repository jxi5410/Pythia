"""
Pythia Live - Main Orchestrator
Real-time prediction market intelligence engine
"""
import time
import sys
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd

from .config import Config
from .database import PythiaDB
from .detector import SignalDetector, Signal
from .alerts import TelegramAlerter
from .alert_relay import relay_signal
from .asset_map import classify_market
from .correlations import find_correlated_markets
from .news_context import get_news_context
from .spike_archive import detect_spike, attribute_spike, save_spike, SpikeEvent
from .patterns import build_patterns, find_matching_pattern, format_pattern_insight

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

logger = logging.getLogger(__name__)


class PythiaLive:
    """
    Main orchestrator for real-time prediction market monitoring.

    Flow:
    1. Fetch active markets from all sources
    2. Get current prices + trades
    3. Store in database (markets, prices, trades)
    4. Run signal detection (including optimism tax on trade data)
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
        self._patterns = []  # Causal pattern cache
        self._patterns_last_built = None

    def run(self):
        """Main execution loop."""
        print("PYTHIA LIVE - Starting...")
        print(f"Connectors: {', '.join(self.connectors.keys())}")

        self.running = True

        # Initial market discovery
        markets = self._discover_markets()
        print(f"Found {len(markets)} liquid markets")

        # Send startup message
        self.alerter.send_startup_message(len(markets))

        print(f"\nPolling every {self.config.POLL_INTERVAL}s")
        print("Press Ctrl+C to stop\n")

        try:
            while self.running:
                self.cycle_count += 1
                cycle_start = time.time()

                print(f"\n{'='*60}")
                print(f"Cycle {self.cycle_count} | {datetime.now().strftime('%H:%M:%S')}")
                print('='*60)

                # 1. Update market list and rebuild patterns (every 10 cycles)
                if self.cycle_count % 10 == 0:
                    markets = self._discover_markets()
                    try:
                        self._patterns = build_patterns(self.db)
                        logger.info("Rebuilt %d causal patterns", len(self._patterns))
                    except Exception as e:
                        logger.warning("Pattern build failed: %s", e)

                # 2. Fetch recent trades (batch per source)
                all_trades = self._fetch_all_trades()

                # 3. Fetch prices, store trades, and detect signals
                all_signals = []
                for market in markets[:50]:  # Top 50 liquid markets
                    market_trades = [
                        t for t in all_trades
                        if t.get('market_id') == market['id']
                    ]
                    signals = self._process_market(market, market_trades)
                    all_signals.extend(signals)

                # 4. Send batch summary if signals found
                if all_signals:
                    print(f"\n{len(all_signals)} signals detected")
                    self._handle_signals(all_signals)
                else:
                    print("\nNo significant signals")

                # 5. Sleep until next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.config.POLL_INTERVAL - elapsed)

                if sleep_time > 0:
                    print(f"Sleeping {sleep_time:.1f}s...")
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\n\nStopping Pythia Live...")
            self.running = False

    def _discover_markets(self) -> List[Dict]:
        """Discover liquid markets from all sources."""
        all_markets = []

        for source, connector in self.connectors.items():
            try:
                print(f"Fetching {source} markets...")
                markets = connector.get_active_markets(limit=100)

                # Filter by liquidity
                liquid = [m for m in markets
                         if m.get('liquidity', 0) >= self.config.MIN_LIQUIDITY]

                all_markets.extend(liquid)

                # Save to database
                for m in liquid:
                    self.db.save_market(m)

                print(f"  {source}: {len(liquid)} liquid markets")

            except Exception as e:
                print(f"  {source} error: {e}")

        # Sort by liquidity
        all_markets.sort(key=lambda x: x.get('liquidity', 0), reverse=True)
        return all_markets

    def _fetch_all_trades(self) -> List[Dict]:
        """Fetch recent trades from all connectors and save to DB."""
        all_trades: List[Dict] = []

        for source, connector in self.connectors.items():
            try:
                trades = connector.get_recent_trades(limit=200)
                if trades:
                    self.db.save_trades_batch(trades)
                    all_trades.extend(trades)
                    logger.info("Fetched %d trades from %s", len(trades), source)
            except Exception as e:
                logger.warning("Failed to fetch trades from %s: %s", source, e)

        return all_trades

    def _process_market(self, market: Dict,
                        trades: Optional[List[Dict]] = None) -> List[Signal]:
        """
        Process a single market:
        1. Get current price
        2. Save to database (price + snapshot)
        3. Run signal detection (including optimism tax with trades)
        """
        market_id = market['id']
        source = market['source']

        try:
            # Use prices already available from market listing (avoids per-market API calls)
            yes_price = market.get('yes_price', 0.5)
            no_price = market.get('no_price', 1 - yes_price)
            volume = market.get('volume_24h', 0)

            price_data = {
                'yes_price': yes_price,
                'no_price': no_price,
                'volume': volume,
                'yes_bid': yes_price,
                'yes_ask': yes_price,
                'spread': 0,
            }

            self.db.save_price(market_id, yes_price, no_price, volume)

            # Save full snapshot
            self.db.save_snapshot(market_id, source, {
                **price_data,
                'volume_24h': market.get('volume_24h', 0),
                'liquidity': market.get('liquidity', 0),
            })

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

            # Run signal detection — pass trades for optimism tax analysis
            signals = self.detector.detect_all(market_data, price_history, trades=trades)

            # Enrich signals with intelligence context
            for signal in signals:
                # 1. Asset class mapping
                classification = classify_market(
                    market.get('title', ''),
                    market.get('description', ''),
                )
                signal.asset_class = classification['asset_class']
                signal.instruments = classification['instruments']
                signal.why_it_matters = classification['how_it_matters']

                # 2. Correlated markets (only for HIGH/CRITICAL to save DB queries)
                if signal.severity in ('HIGH', 'CRITICAL'):
                    signal.correlated_markets = find_correlated_markets(
                        self.db, market['id'], market.get('title', ''),
                    )

                # 3. News context (only for CRITICAL)
                if signal.severity == 'CRITICAL':
                    signal.news_context = get_news_context(market.get('title', ''))

                # 4. Pattern matching — find historical causal patterns
                if signal.severity in ('HIGH', 'CRITICAL'):
                    matched = find_matching_pattern(self._patterns, signal)
                    if matched:
                        insight = format_pattern_insight(matched, signal)
                        signal.metadata['pattern_insight'] = insight
                        signal.description += f" | {insight}"

            # 5. Spike detection — archive significant price moves
            spike = detect_spike(price_history, threshold=self.config.PROBABILITY_SPIKE_THRESHOLD)
            if spike:
                spike.market_id = market_id
                spike.market_title = market.get('title', '')
                spike.asset_class = classify_market(
                    market.get('title', ''), market.get('description', '')
                )['asset_class']
                try:
                    spike = attribute_spike(spike)
                except Exception as e:
                    logger.warning("Spike attribution failed for %s: %s", market_id, e)
                save_spike(self.db, spike)
                logger.info("Spike archived: %s %s %.1f%% on %s",
                            spike.direction, spike.market_title,
                            spike.magnitude * 100, market_id)

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

            # Relay all HIGH/CRITICAL signals for OpenClaw to push
            if signal.severity in ["HIGH", "CRITICAL"]:
                relay_signal(signal, pattern_insight=signal.metadata.get('pattern_insight', ''))
                print(f"  Signal relayed: {signal.signal_type} ({signal.severity})")

                # Also try Telegram direct (if configured)
                sent = self.alerter.send_signal(
                    signal=signal,
                    market_title=signal.market_title,
                    market_url=self._get_market_url(signal.market_id)
                )
                if sent:
                    self.db.mark_alert_sent(signal_id, "telegram", "SENT")

        # Summary
        print(f"\nSignal Summary:")
        print(f"  Critical: {critical_count}")
        print(f"  High: {high_count}")
        print(f"  Medium: {len([s for s in signals if s.severity == 'MEDIUM'])}")

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
