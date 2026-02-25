"""
Phase 3: Orderbook Intelligence Analyzer

Analyzes real-time orderbook data to detect:
- Liquidity spikes (sudden depth changes)
- Whale orders (large limit orders appearing/disappearing)
- Spread compression/expansion
- Orderbook imbalance (bid/ask pressure)
- Iceberg detection (partial fills suggesting hidden size)

This is the "critical information" layer - who is moving markets,
not just that they are moving.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


@dataclass
class OrderbookLevel:
    """Single price level in orderbook."""
    price: float
    size: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class OrderbookSnapshot:
    """Full orderbook snapshot."""
    market_id: str
    timestamp: datetime
    bids: List[OrderbookLevel] = field(default_factory=list)
    asks: List[OrderbookLevel] = field(default_factory=list)
    sequence: int = 0
    
    @property
    def best_bid(self) -> Optional[OrderbookLevel]:
        return self.bids[0] if self.bids else None
    
    @property
    def best_ask(self) -> Optional[OrderbookLevel]:
        return self.asks[0] if self.asks else None
    
    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None
    
    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None
    
    @property
    def bid_depth(self) -> float:
        """Total bid volume within 2% of mid."""
        mid = self.mid_price
        if not mid:
            return 0
        threshold = mid * 0.02
        return sum(level.size for level in self.bids 
                  if mid - level.price <= threshold)
    
    @property
    def ask_depth(self) -> float:
        """Total ask volume within 2% of mid."""
        mid = self.mid_price
        if not mid:
            return 0
        threshold = mid * 0.02
        return sum(level.size for level in self.asks 
                  if level.price - mid <= threshold)
    
    @property
    def imbalance(self) -> Optional[float]:
        """Bid/ask imbalance ratio (-1 to 1, positive = more bids)."""
        bid_d = self.bid_depth
        ask_d = self.ask_depth
        if bid_d + ask_d == 0:
            return None
        return (bid_d - ask_d) / (bid_d + ask_d)


@dataclass
class LiquiditySignal:
    """Detected liquidity anomaly."""
    market_id: str
    signal_type: str  # 'whale', 'liquidity_spike', 'spread_compression', 'iceberg'
    timestamp: datetime
    severity: float  # 0-1 scale
    description: str
    metrics: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'market_id': self.market_id,
            'signal_type': self.signal_type,
            'timestamp': self.timestamp.isoformat(),
            'severity': self.severity,
            'description': self.description,
            'metrics': self.metrics
        }


class OrderbookAnalyzer:
    """
    Analyzes orderbook streams to detect market microstructure signals.
    
    Critical for institutional traders because it reveals:
    - Intent: Large orders = informed traders positioning
    - Liquidity: Depth changes = execution risk
    - Momentum: Imbalance = directional pressure
    """
    
    # Thresholds for signal detection
    WHALE_SIZE_THRESHOLD = 50000  # $50k minimum for whale alert
    LIQUIDITY_CHANGE_THRESHOLD = 0.3  # 30% change = significant
    SPREAD_COMPRESSION_THRESHOLD = 0.5  # 50% tighter spread
    ICEBERG_DETECTION_THRESHOLD = 3  # 3+ partial fills at same level
    
    def __init__(self, history_window: int = 100):
        """
        Args:
            history_window: Number of snapshots to keep per market
        """
        self.history_window = history_window
        self.orderbook_history: Dict[str, List[OrderbookSnapshot]] = {}
        self.recent_trades: Dict[str, List[Dict]] = {}  # For iceberg detection
        self.signals: List[LiquiditySignal] = []
        
    def process_orderbook(self, market_id: str, 
                         bids: List[Tuple[float, float]],
                         asks: List[Tuple[float, float]],
                         sequence: int = 0) -> List[LiquiditySignal]:
        """
        Process new orderbook snapshot and detect signals.
        
        Args:
            market_id: Market identifier
            bids: List of (price, size) tuples
            asks: List of (price, size) tuples
            sequence: Orderbook sequence number
            
        Returns:
            List of detected signals
        """
        # Create snapshot
        snapshot = OrderbookSnapshot(
            market_id=market_id,
            timestamp=datetime.now(),
            bids=[OrderbookLevel(price=p, size=s) for p, s in bids[:10]],
            asks=[OrderbookLevel(price=p, size=s) for p, s in asks[:10]],
            sequence=sequence
        )
        
        # Initialize history
        if market_id not in self.orderbook_history:
            self.orderbook_history[market_id] = []
            logger.info(f"Initialized orderbook tracking for {market_id}")
        
        # Get previous snapshot
        history = self.orderbook_history[market_id]
        prev_snapshot = history[-1] if history else None
        
        # Detect signals
        detected = []
        
        if prev_snapshot:
            # Whale detection
            whale_signals = self._detect_whale_orders(snapshot, prev_snapshot)
            detected.extend(whale_signals)
            
            # Liquidity spike
            liq_signals = self._detect_liquidity_changes(snapshot, prev_snapshot)
            detected.extend(liq_signals)
            
            # Spread compression
            spread_signals = self._detect_spread_changes(snapshot, prev_snapshot)
            detected.extend(spread_signals)
        
        # Store snapshot
        history.append(snapshot)
        if len(history) > self.history_window:
            history.pop(0)
        
        # Store signals
        self.signals.extend(detected)
        
        return detected
    
    def process_trade(self, market_id: str, price: float, 
                     size: float, side: str) -> Optional[LiquiditySignal]:
        """
        Process trade for iceberg detection.
        
        Icebergs are large orders hidden as smaller pieces.
        Detected by: multiple trades at same price, similar size,
        suggesting one large order being filled in parts.
        """
        if market_id not in self.recent_trades:
            self.recent_trades[market_id] = []
        
        trade = {
            'price': price,
            'size': size,
            'side': side,
            'timestamp': datetime.now()
        }
        
        trades = self.recent_trades[market_id]
        trades.append(trade)
        
        # Keep only last 50 trades
        cutoff = datetime.now() - timedelta(minutes=5)
        trades[:] = [t for t in trades if t['timestamp'] > cutoff]
        
        # Check for iceberg pattern
        return self._detect_iceberg(market_id, price, trades)
    
    def _detect_whale_orders(self, current: OrderbookSnapshot,
                            previous: OrderbookSnapshot) -> List[LiquiditySignal]:
        """Detect large limit orders appearing or disappearing."""
        signals = []
        
        # Check bids for new whale orders
        for bid in current.bids[:5]:  # Top 5 levels
            if bid.size >= self.WHALE_SIZE_THRESHOLD:
                # Check if this is new
                prev_size = next((b.size for b in previous.bids 
                                 if abs(b.price - bid.price) < 0.001), 0)
                if bid.size > prev_size * 1.5:  # 50% increase
                    signals.append(LiquiditySignal(
                        market_id=current.market_id,
                        signal_type='whale',
                        timestamp=current.timestamp,
                        severity=min(bid.size / 100000, 1.0),
                        description=f"Large bid: ${bid.size:,.0f} @ {bid.price:.4f}",
                        metrics={
                            'side': 'bid',
                            'price': bid.price,
                            'size': bid.size,
                            'previous_size': prev_size,
                            'increase_pct': ((bid.size - prev_size) / prev_size * 100) if prev_size > 0 else 100
                        }
                    ))
        
        # Check asks for new whale orders
        for ask in current.asks[:5]:
            if ask.size >= self.WHALE_SIZE_THRESHOLD:
                prev_size = next((a.size for a in previous.asks 
                                 if abs(a.price - ask.price) < 0.001), 0)
                if ask.size > prev_size * 1.5:
                    signals.append(LiquiditySignal(
                        market_id=current.market_id,
                        signal_type='whale',
                        timestamp=current.timestamp,
                        severity=min(ask.size / 100000, 1.0),
                        description=f"Large ask: ${ask.size:,.0f} @ {ask.price:.4f}",
                        metrics={
                            'side': 'ask',
                            'price': ask.price,
                            'size': ask.size,
                            'previous_size': prev_size,
                            'increase_pct': ((ask.size - prev_size) / prev_size * 100) if prev_size > 0 else 100
                        }
                    ))
        
        return signals
    
    def _detect_liquidity_changes(self, current: OrderbookSnapshot,
                                 previous: OrderbookSnapshot) -> List[LiquiditySignal]:
        """Detect significant liquidity additions or removals."""
        signals = []
        
        bid_change = (current.bid_depth - previous.bid_depth) / previous.bid_depth if previous.bid_depth > 0 else 0
        ask_change = (current.ask_depth - previous.ask_depth) / previous.ask_depth if previous.ask_depth > 0 else 0
        
        # Significant bid liquidity removal (bearish)
        if bid_change < -self.LIQUIDITY_CHANGE_THRESHOLD:
            signals.append(LiquiditySignal(
                market_id=current.market_id,
                signal_type='liquidity_drop',
                timestamp=current.timestamp,
                severity=abs(bid_change),
                description=f"Bid liquidity dropped {abs(bid_change)*100:.1f}%",
                metrics={
                    'previous_depth': previous.bid_depth,
                    'current_depth': current.bid_depth,
                    'change_pct': bid_change * 100
                }
            ))
        
        # Significant ask liquidity removal (bullish)
        if ask_change < -self.LIQUIDITY_CHANGE_THRESHOLD:
            signals.append(LiquiditySignal(
                market_id=current.market_id,
                signal_type='liquidity_drop',
                timestamp=current.timestamp,
                severity=abs(ask_change),
                description=f"Ask liquidity dropped {abs(ask_change)*100:.1f}%",
                metrics={
                    'previous_depth': previous.ask_depth,
                    'current_depth': current.ask_depth,
                    'change_pct': ask_change * 100
                }
            ))
        
        return signals
    
    def _detect_spread_changes(self, current: OrderbookSnapshot,
                              previous: OrderbookSnapshot) -> List[LiquiditySignal]:
        """Detect spread compression/expansion."""
        signals = []
        
        prev_spread = previous.spread
        curr_spread = current.spread
        
        if not prev_spread or not curr_spread or prev_spread == 0:
            return signals
        
        spread_change = (curr_spread - prev_spread) / prev_spread
        
        # Spread compression (more efficient market)
        if spread_change < -self.SPREAD_COMPRESSION_THRESHOLD:
            signals.append(LiquiditySignal(
                market_id=current.market_id,
                signal_type='spread_compression',
                timestamp=current.timestamp,
                severity=abs(spread_change),
                description=f"Spread compressed {abs(spread_change)*100:.1f}%",
                metrics={
                    'previous_spread': prev_spread,
                    'current_spread': curr_spread,
                    'mid_price': current.mid_price
                }
            ))
        
        # Spread expansion (less liquid)
        elif spread_change > self.SPREAD_COMPRESSION_THRESHOLD:
            signals.append(LiquiditySignal(
                market_id=current.market_id,
                signal_type='spread_expansion',
                timestamp=current.timestamp,
                severity=spread_change,
                description=f"Spread expanded {spread_change*100:.1f}%",
                metrics={
                    'previous_spread': prev_spread,
                    'current_spread': curr_spread,
                    'mid_price': current.mid_price
                }
            ))
        
        return signals
    
    def _detect_iceberg(self, market_id: str, price: float,
                       trades: List[Dict]) -> Optional[LiquiditySignal]:
        """Detect potential iceberg order being filled."""
        # Look for multiple trades at same price level
        price_trades = [t for t in trades if abs(t['price'] - price) < 0.001]
        
        if len(price_trades) < self.ICEBERG_DETECTION_THRESHOLD:
            return None
        
        # Check if sizes are similar (suggesting same parent order)
        sizes = [t['size'] for t in price_trades[-5:]]  # Last 5 at this price
        avg_size = sum(sizes) / len(sizes)
        size_variance = sum((s - avg_size)**2 for s in sizes) / len(sizes)
        
        # Low variance = likely iceberg
        if size_variance < avg_size * 0.2:  # Within 20% of average
            total_size = sum(t['size'] for t in price_trades)
            return LiquiditySignal(
                market_id=market_id,
                signal_type='iceberg',
                timestamp=datetime.now(),
                severity=min(total_size / 100000, 1.0),
                description=f"Potential iceberg: {len(price_trades)} fills @ {price:.4f}",
                metrics={
                    'price': price,
                    'fills': len(price_trades),
                    'total_size': total_size,
                    'avg_fill_size': avg_size,
                    'side': price_trades[0]['side']
                }
            )
        
        return None
    
    def get_imbalance_signal(self, market_id: str) -> Optional[Dict]:
        """Get current orderbook imbalance for a market."""
        history = self.orderbook_history.get(market_id, [])
        if not history:
            return None
        
        current = history[-1]
        imbalance = current.imbalance
        
        if imbalance is None:
            return None
        
        return {
            'market_id': market_id,
            'timestamp': current.timestamp.isoformat(),
            'imbalance': imbalance,  # -1 to 1, positive = more bids
            'bid_depth': current.bid_depth,
            'ask_depth': current.ask_depth,
            'interpretation': 'bullish' if imbalance > 0.2 else 'bearish' if imbalance < -0.2 else 'neutral'
        }
    
    def get_recent_signals(self, market_id: Optional[str] = None,
                          limit: int = 50) -> List[LiquiditySignal]:
        """Get recent liquidity signals."""
        signals = self.signals
        if market_id:
            signals = [s for s in signals if s.market_id == market_id]
        return sorted(signals, key=lambda s: s.timestamp, reverse=True)[:limit]
    
    def export_signals(self, filepath: str):
        """Export all signals to JSON."""
        data = {
            'exported_at': datetime.now().isoformat(),
            'total_signals': len(self.signals),
            'signals': [s.to_dict() for s in self.signals]
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Exported {len(self.signals)} signals to {filepath}")
