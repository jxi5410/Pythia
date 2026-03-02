"""
Pythia Live - Main Orchestrator
Real-time prediction market intelligence engine with governance
"""
import time
import sys
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
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

# Governance layer — mandatory for compliance (Singapore IMDA + UC Berkeley)
from .governance import init_governance, GovernanceConfig, get_governance
from .causal_v2 import attribute_spike_with_governance
GOVERNANCE_ENABLED = True

# Import connectors
try:
    from .connectors.polymarket import PolymarketConnector
    from .connectors.polymarket_ws import PolymarketWebSocketConnector
    from .market_stream import MarketStream
    from .orderbook_analyzer import OrderbookAnalyzer, LiquiditySignal
    HAS_POLYGON = True
    HAS_WEBSOCKET = True
    HAS_ORDERBOOK = True
except ImportError:
    HAS_POLYGON = False
    HAS_WEBSOCKET = False
    HAS_ORDERBOOK = False

try:
    from .connectors.kalshi import KalshiConnector
    HAS_KALSHI = True
except ImportError:
    HAS_KALSHI = False

try:
    from .connectors.manifold import ManifoldConnector
    HAS_MANIFOLD = True
except ImportError:
    HAS_MANIFOLD = False

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

    def __init__(self, mode="auto"):
        """
        Initialize Pythia Live.
        
        Args:
            mode: "websocket", "http", or "auto" (WebSocket primary, HTTP fallback)
        """
        self.config = Config()
        self.mode = mode  # Store mode for runtime selection
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

        # Initialize connectors (priority order: Kalshi > Manifold > Polymarket)
        self.connectors = {}
        if HAS_KALSHI:
            self.connectors['kalshi'] = KalshiConnector()
        if HAS_MANIFOLD:
            self.connectors['manifold'] = ManifoldConnector()
        if HAS_POLYGON:
            self.connectors['polymarket'] = PolymarketConnector()
        
        # WebSocket stream (if available and requested)
        self.market_stream = None
        if HAS_WEBSOCKET and mode != "http":
            self.market_stream = MarketStream(mode=mode)
            logger.info(f"✓ WebSocket connector available (mode: {mode})")
        
        # Phase 3: Orderbook Analyzer (critical for institutional signals)
        self.orderbook_analyzer = None
        if HAS_ORDERBOOK:
            self.orderbook_analyzer = OrderbookAnalyzer()
            logger.info("✓ Orderbook analyzer initialized (Phase 3)")
        
        # Real-time update buffer for WebSocket mode
        self.price_buffer = {}  # {market_id: latest_price_data}
        self.last_buffer_flush = time.time()
        
        # Source health tracking
        self.source_health = {source: {"last_success": None, "consecutive_failures": 0} for source in self.connectors.keys()}

        self.running = False
        self.cycle_count = 0
        self._patterns = []  # Causal pattern cache
        self._patterns_last_built = None
        
        # Initialize governance layer
        # Governance is mandatory — system will not start without it
        audit_dir = Path(self.config.DB_PATH).parent / "audit_trails"
        gov_config = GovernanceConfig(
            max_cost_per_hour=10.0,
            max_cost_per_run=2.0,
            emergency_shutdown_threshold=50.0,
            min_confidence_auto_relay=0.85,
            min_confidence_flag_review=0.70,
            audit_trail_enabled=True,
            sandbox_mode=False  # Set True to prevent real signals
        )
        init_governance(gov_config, audit_dir)
        logger.info("Governance layer initialized (audit dir: %s)", audit_dir)

    def run(self):
        """
        Main execution loop - chooses WebSocket or HTTP based on mode.
        """
        logger.info("PYTHIA LIVE - Starting...")
        logger.info("Mode: %s", self.mode)
        logger.info("Connectors: %s", ', '.join(self.connectors.keys()))

        # Use WebSocket if available and not explicitly HTTP mode
        if self.market_stream and self.mode != "http":
            logger.info("Using REAL-TIME WebSocket streaming (sub-second updates)")
            asyncio.run(self._run_websocket())
        else:
            logger.info("Using HTTP polling (60s interval)")
            self._run_http_polling()
    
    async def _run_websocket(self):
        """WebSocket streaming mode - real-time price updates."""
        self.running = True
        
        # Initial market discovery
        markets = self._discover_markets()
        logger.info("Found %d liquid markets", len(markets))

        # Send startup message
        self.alerter.send_startup_message(len(markets))

        # Get market IDs for top 50 liquid markets
        market_ids = [m['id'] for m in markets[:50]]

        logger.info("Streaming %d markets in real-time...", len(market_ids))
        
        # Start pattern rebuild task
        pattern_rebuild_task = asyncio.create_task(self._periodic_pattern_rebuild())
        
        try:
            # Start WebSocket stream
            await self.market_stream.start(
                market_ids=market_ids,
                on_price_update=self._handle_realtime_price,
                on_trade=self._handle_realtime_trade,
            )
        except KeyboardInterrupt:
            logger.info("Stopping Pythia Live...")
            self.running = False
            pattern_rebuild_task.cancel()
            await self.market_stream.stop()
    
    async def _periodic_pattern_rebuild(self):
        """Rebuild causal patterns every 10 minutes."""
        while self.running:
            await asyncio.sleep(600)  # 10 minutes
            try:
                self._patterns = build_patterns(self.db)
                logger.info("Rebuilt %d causal patterns", len(self._patterns))
            except Exception as e:
                logger.warning("Pattern build failed: %s", e)
    
    def _handle_realtime_price(self, data: Dict):
        """Handle real-time price update from WebSocket."""
        market_id = data.get('market_id')
        if not market_id:
            return
        
        # Store in buffer
        self.price_buffer[market_id] = data
        
        # Flush buffer every 5 seconds to detect spikes
        if time.time() - self.last_buffer_flush > 5:
            self._flush_price_buffer()
            self.last_buffer_flush = time.time()
    
    def _handle_realtime_trade(self, data: Dict):
        """Handle real-time trade from WebSocket."""
        try:
            # Save trade to database
            trade_data = {
                'market_id': data.get('market_id'),
                'price': data.get('price'),
                'size': data.get('size'),
                'side': data.get('side'),
                'timestamp': data.get('timestamp'),
                'source': 'polymarket'
            }
            self.db.save_trades_batch([trade_data])
            
            # Phase 3: Process trade for iceberg detection
            if self.orderbook_analyzer:
                signal = self.orderbook_analyzer.process_trade(
                    data.get('market_id'),
                    data.get('price'),
                    data.get('size'),
                    data.get('side')
                )
                if signal:
                    self._handle_liquidity_signal(signal)
                    
        except Exception as e:
            logger.error(f"Error saving trade: {e}")
    
    def _handle_orderbook_update(self, data: Dict):
        """Handle real-time orderbook update from WebSocket (Phase 3)."""
        if not self.orderbook_analyzer:
            return
        
        try:
            market_id = data.get('market_id')
            bids = data.get('bids', [])  # List of [price, size]
            asks = data.get('asks', [])  # List of [price, size]
            sequence = data.get('sequence', 0)
            
            # Process orderbook and detect liquidity signals
            signals = self.orderbook_analyzer.process_orderbook(
                market_id=market_id,
                bids=bids,
                asks=asks,
                sequence=sequence
            )
            
            # Handle any detected signals
            for signal in signals:
                self._handle_liquidity_signal(signal)
                
        except Exception as e:
            logger.error(f"Error processing orderbook: {e}")
    
    def _flush_price_buffer(self):
        """Process buffered price updates and detect signals."""
        if not self.price_buffer:
            return
        
        updates_processed = 0
        signals_found = []
        
        for market_id, price_data in self.price_buffer.items():
            try:
                # Get market info from database
                market = self.db.get_market(market_id)
                if not market:
                    continue
                
                # Save price to database
                yes_price = price_data.get('price', 0.5)
                self.db.save_price(market_id, yes_price, 1 - yes_price, 0)
                
                # Get price history and detect signals
                price_history = self.db.get_market_history(market_id, hours=24)
                
                if len(price_history) > 1:
                    # Prepare market data for signal detection
                    market_data = {
                        **market,
                        'yes_price': yes_price,
                        'no_price': 1 - yes_price,
                    }
                    
                    # Run signal detection
                    signals = self.detector.detect_all(market_data, price_history)
                    
                    if signals:
                        signals_found.extend(signals)
                
                updates_processed += 1
                
            except Exception as e:
                logger.error(f"Error processing price update for {market_id}: {e}")
        
        # Clear buffer
        self.price_buffer.clear()
        
        # Handle detected signals
        if signals_found:
            logger.info("%d signals detected from %d updates", len(signals_found), updates_processed)
            self._handle_signals(signals_found)
        else:
            logger.debug(f"Processed {updates_processed} price updates, no signals")
    
    def _run_http_polling(self):
        """HTTP polling mode - legacy 60s interval (fallback)."""
        self.running = True

        # Initial market discovery
        markets = self._discover_markets()
        logger.info("Found %d liquid markets", len(markets))

        # Send startup message
        self.alerter.send_startup_message(len(markets))

        logger.info("Polling every %ds", self.config.POLL_INTERVAL)

        try:
            while self.running:
                self.cycle_count += 1
                cycle_start = time.time()

                logger.info("Cycle %d | %s", self.cycle_count, datetime.now().strftime('%H:%M:%S'))

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
                    logger.info("%d signals detected", len(all_signals))
                    self._handle_signals(all_signals)
                else:
                    logger.debug("No significant signals")

                # 5. Sleep until next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.config.POLL_INTERVAL - elapsed)

                if sleep_time > 0:
                    logger.debug("Sleeping %.1fs...", sleep_time)
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("Stopping Pythia Live...")
            self.running = False

    def _discover_markets(self) -> List[Dict]:
        """Discover liquid markets from all sources, then deduplicate."""
        all_markets = []

        for source, connector in self.connectors.items():
            try:
                logger.info("Fetching %s markets...", source)
                markets = connector.get_active_markets(limit=100)

                # Filter by liquidity
                liquid = [m for m in markets
                         if m.get('liquidity', 0) >= self.config.MIN_LIQUIDITY]

                all_markets.extend(liquid)

                # Save to database
                for m in liquid:
                    self.db.save_market(m)

                logger.info("  %s: %d liquid markets", source, len(liquid))

            except Exception as e:
                logger.error("  %s error: %s", source, e)

        # Deduplicate cross-platform: same event on multiple sources
        before_dedup = len(all_markets)
        all_markets = self._deduplicate_markets(all_markets)
        if before_dedup != len(all_markets):
            logger.info("Deduplicated %d → %d markets", before_dedup, len(all_markets))

        # Sort by liquidity
        all_markets.sort(key=lambda x: x.get('liquidity', 0), reverse=True)
        return all_markets

    @staticmethod
    def _deduplicate_markets(markets: List[Dict]) -> List[Dict]:
        """
        Deduplicate markets that represent the same event across platforms.

        Uses title similarity to detect duplicates. When a duplicate is found,
        keeps the entry with higher liquidity (more reliable pricing).
        """
        if not markets:
            return markets

        def _normalize_title(title: str) -> str:
            """Normalize title for comparison: lowercase, strip punctuation."""
            import re
            t = title.lower().strip()
            t = re.sub(r'[^a-z0-9\s]', '', t)
            t = re.sub(r'\s+', ' ', t)
            return t

        def _title_similarity(a: str, b: str) -> float:
            """Word-overlap Jaccard similarity between two titles."""
            words_a = set(_normalize_title(a).split())
            words_b = set(_normalize_title(b).split())
            if not words_a or not words_b:
                return 0.0
            intersection = words_a & words_b
            union = words_a | words_b
            return len(intersection) / len(union) if union else 0.0

        # Group by approximate title match
        kept = []
        used = set()
        SIMILARITY_THRESHOLD = 0.7

        for i, market in enumerate(markets):
            if i in used:
                continue

            best = market
            title_i = market.get('title', '')

            for j in range(i + 1, len(markets)):
                if j in used:
                    continue
                title_j = markets[j].get('title', '')
                if _title_similarity(title_i, title_j) >= SIMILARITY_THRESHOLD:
                    used.add(j)
                    # Keep whichever has more liquidity
                    if markets[j].get('liquidity', 0) > best.get('liquidity', 0):
                        best = markets[j]

            kept.append(best)

        return kept

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

            # 5. Spike detection — archive significant price moves with governance
            spike = detect_spike(price_history, threshold=self.config.PROBABILITY_SPIKE_THRESHOLD)
            if spike:
                spike.market_id = market_id
                spike.market_title = market.get('title', '')
                spike.asset_class = classify_market(
                    market.get('title', ''), market.get('description', '')
                )['asset_class']
                
                # Governance-wrapped attribution (mandatory)
                try:
                    result, audit_trail = attribute_spike_with_governance(spike)

                    # Check decision gate
                    decision = result.get('decision', 'REJECT')
                    confidence = result.get('final_confidence', 0.0)

                    if decision == "AUTO_RELAY":
                        spike.attributed_events = [result['attribution']['most_likely_cause']]
                        save_spike(self.db, spike)
                        logger.info("Spike AUTO-RELAYED: %s %.1f%% (confidence: %.2f)",
                                   spike.market_title[:50], spike.magnitude * 100, confidence)

                    elif decision == "FLAG_REVIEW":
                        spike.attributed_events = [result['attribution']['most_likely_cause']]
                        spike.manual_tag = "PENDING_HUMAN_REVIEW"
                        save_spike(self.db, spike)
                        logger.warning("Spike FLAGGED FOR REVIEW: %s (confidence: %.2f)",
                                      spike.market_title[:50], confidence)

                    else:  # REJECT
                        spike.manual_tag = "LOW_CONFIDENCE_REJECTED"
                        save_spike(self.db, spike)
                        logger.info("Spike REJECTED: %s (confidence: %.2f)",
                                   spike.market_title[:50], confidence)

                except Exception as e:
                    logger.error("Governance attribution failed for %s: %s", market_id, e)
                    save_spike(self.db, spike)

            return signals

        except Exception as e:
            logger.error("Error processing %s: %s", market_id, e)
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
                logger.info("Signal relayed: %s (%s)", signal.signal_type, signal.severity)

                # Also try Telegram direct (if configured)
                sent = self.alerter.send_signal(
                    signal=signal,
                    market_title=signal.market_title,
                    market_url=self._get_market_url(signal.market_id)
                )
                if sent:
                    self.db.mark_alert_sent(signal_id, "telegram", "SENT")

        # Summary
        medium_count = len([s for s in signals if s.severity == 'MEDIUM'])
        logger.info("Signal summary: Critical=%d High=%d Medium=%d", critical_count, high_count, medium_count)

    def _get_market_url(self, market_id: str) -> str:
        """Generate market URL based on ID pattern."""
        if 'polymarket' in market_id.lower() or len(market_id) == 64:
            return f"https://polymarket.com/event/{market_id[:16]}"
        elif 'kalshi' in market_id.lower():
            return f"https://kalshi.com/markets/{market_id}"
        return ""


def main():
    """
    Entry point.
    
    Usage:
        python -m src.pythia_live.main              # Auto mode (WebSocket primary, HTTP fallback)
        python -m src.pythia_live.main --websocket  # WebSocket only
        python -m src.pythia_live.main --http       # HTTP polling only
    """
    import sys
    
    # Parse mode from command line
    mode = "auto"  # Default: WebSocket primary, HTTP fallback
    if "--websocket" in sys.argv:
        mode = "websocket"
    elif "--http" in sys.argv:
        mode = "http"
    
    pythia = PythiaLive(mode=mode)
    pythia.run()


if __name__ == "__main__":
    main()
