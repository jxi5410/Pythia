"""
Signal Detection Engine
Identifies trading opportunities in prediction market data
"""
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from .database import PythiaDB


@dataclass
class Signal:
    market_id: str
    market_title: str
    timestamp: datetime
    signal_type: str  # PROBABILITY_SPIKE, VOLUME_ANOMALY, ARBITRAGE, CORRELATION_DEV, OPTIMISM_TAX
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    old_price: Optional[float]
    new_price: Optional[float]
    expected_return: float
    metadata: Dict
    # Intelligence fields
    asset_class: str = ""
    instruments: str = ""
    why_it_matters: str = ""
    correlated_markets: List[Dict] = field(default_factory=list)
    news_context: List[Dict] = field(default_factory=list)


class SignalDetector:
    """
    Multi-strategy signal detector for prediction markets.

    Detects:
    1. Probability spikes (large price moves)
    2. Volume anomalies (unusual trading activity)
    3. Arbitrage opportunities (maker/taker edge)
    4. Momentum (trend breakouts)
    5. Optimism tax (taker YES skew on longshots)
    """

    def __init__(self, db: PythiaDB, config: Dict):
        self.db = db
        self.config = config
        self.recent_signals = {}  # Cooldown tracking

    def detect_all(self, market_data: Dict, price_history: pd.DataFrame,
                   trades: Optional[List[Dict]] = None) -> List[Signal]:
        """
        Run all detection strategies on market data.

        Args:
            market_data: Current market snapshot
            price_history: Historical prices (last 24h)
            trades: Optional list of recent trades for this market

        Returns:
            List of detected signals
        """
        signals = []
        market_id = market_data['id']

        # Check cooldown
        if self._is_on_cooldown(market_id):
            return signals

        # 1. Probability spike detection
        spike_signal = self._detect_probability_spike(market_data, price_history)
        if spike_signal:
            signals.append(spike_signal)

        # 2. Volume anomaly detection
        volume_signal = self._detect_volume_anomaly(market_data, price_history)
        if volume_signal:
            signals.append(volume_signal)

        # 3. Arbitrage opportunity (maker edge)
        arb_signal = self._detect_maker_edge(market_data, price_history)
        if arb_signal:
            signals.append(arb_signal)

        # 4. Momentum detection
        momentum_signal = self._detect_momentum(market_data, price_history)
        if momentum_signal:
            signals.append(momentum_signal)

        # 5. Optimism tax (requires trade data)
        if trades:
            tax_signal = self._detect_optimism_tax(market_data, trades)
            if tax_signal:
                signals.append(tax_signal)

        # Update cooldown if signals found
        if signals:
            self.recent_signals[market_id] = datetime.now()

        return signals

    def _is_on_cooldown(self, market_id: str) -> bool:
        """Check if market is on signal cooldown."""
        if market_id not in self.recent_signals:
            return False

        cooldown = timedelta(seconds=self.config.get('SIGNAL_COOLDOWN', 300))
        return datetime.now() - self.recent_signals[market_id] < cooldown

    def _detect_probability_spike(self, market_data: Dict,
                                  price_history: pd.DataFrame) -> Optional[Signal]:
        """
        Detect significant probability changes.

        A 5%+ move in probability is notable.
        A 10%+ move is critical.
        """
        if price_history.empty or len(price_history) < 2:
            return None

        current_price = market_data.get('yes_price', 0.5)

        # Compare to price 1 hour ago
        one_hour_ago = price_history[price_history['timestamp'] >
                                     (datetime.now() - timedelta(hours=1)).isoformat()]

        if one_hour_ago.empty:
            # Use earliest available
            old_price = price_history.iloc[-1]['yes_price']
        else:
            old_price = one_hour_ago.iloc[0]['yes_price']

        price_change = abs(current_price - old_price)

        if price_change >= 0.10:  # 10%+
            severity = "CRITICAL"
        elif price_change >= 0.05:  # 5%+
            severity = "HIGH"
        elif price_change >= 0.03:  # 3%+
            severity = "MEDIUM"
        else:
            return None

        direction = "UP" if current_price > old_price else "DOWN"

        return Signal(
            market_id=market_data['id'],
            market_title=market_data.get('title', 'Unknown'),
            timestamp=datetime.now(),
            signal_type="PROBABILITY_SPIKE",
            severity=severity,
            description=f"{direction} {price_change:.1%} in 1h | "
                       f"{market_data.get('title', 'Unknown')[:80]}",
            old_price=old_price,
            new_price=current_price,
            expected_return=price_change * 0.5,  # Conservative estimate
            metadata={
                'change_pct': price_change,
                'timeframe': '1h',
                'direction': 'up' if current_price > old_price else 'down'
            }
        )

    def _detect_volume_anomaly(self, market_data: Dict,
                               price_history: pd.DataFrame) -> Optional[Signal]:
        """Detect unusual volume spikes."""
        if price_history.empty:
            return None

        current_volume = market_data.get('volume_24h', 0)

        # Calculate average volume from history
        avg_volume = price_history['volume'].mean() if 'volume' in price_history.columns else 0

        if avg_volume == 0 or current_volume == 0:
            return None

        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        if volume_ratio >= 5:  # 5x average
            severity = "CRITICAL"
        elif volume_ratio >= 3:  # 3x average
            severity = "HIGH"
        elif volume_ratio >= 2:  # 2x average
            severity = "MEDIUM"
        else:
            return None

        return Signal(
            market_id=market_data['id'],
            market_title=market_data.get('title', 'Unknown'),
            timestamp=datetime.now(),
            signal_type="VOLUME_ANOMALY",
            severity=severity,
            description=f"Volume spike: {volume_ratio:.1f}x normal | "
                       f"${current_volume:,.0f} traded",
            old_price=None,
            new_price=market_data.get('yes_price'),
            expected_return=0.02,  # Volume often precedes moves
            metadata={
                'volume_ratio': volume_ratio,
                'current_volume': current_volume,
                'avg_volume': avg_volume
            }
        )

    def _detect_maker_edge(self, market_data: Dict,
                          price_history: pd.DataFrame) -> Optional[Signal]:
        """
        Detect maker/taker arbitrage opportunities.

        Based on the Becker model: makers earn +0.77% to +1.25% per trade.
        """
        # Need orderbook data
        spread = market_data.get('spread', 0)

        if spread < 0.02:  # Less than 2% spread = not enough edge
            return None

        # Estimate maker edge
        maker_edge = spread * 0.4  # Rough estimate

        if maker_edge < 0.01:  # Need at least 1% edge
            return None

        return Signal(
            market_id=market_data['id'],
            market_title=market_data.get('title', 'Unknown'),
            timestamp=datetime.now(),
            signal_type="MAKER_EDGE",
            severity="MEDIUM",
            description=f"Maker edge: {maker_edge:.2%} | "
                       f"Spread: {spread:.2%} | Provide liquidity",
            old_price=market_data.get('yes_bid'),
            new_price=market_data.get('yes_ask'),
            expected_return=maker_edge,
            metadata={
                'spread': spread,
                'maker_edge': maker_edge,
                'yes_bid': market_data.get('yes_bid'),
                'yes_ask': market_data.get('yes_ask')
            }
        )

    def _detect_momentum(self, market_data: Dict,
                        price_history: pd.DataFrame) -> Optional[Signal]:
        """Detect price momentum using simple moving averages."""
        if price_history.empty or len(price_history) < 10:
            return None

        # Skip micro-cap / penny markets — too noisy for momentum signals
        current_price = market_data.get('yes_price', 0)
        if current_price < 0.05 or current_price > 0.95:
            return None
        if market_data.get('liquidity', 0) < 50000:
            return None

        prices = price_history['yes_price'].values

        # Calculate short and long MA
        short_ma = np.mean(prices[:5])  # Last 5 points
        long_ma = np.mean(prices[-10:])  # Earlier 10 points

        current = prices[0]

        # Breakout detection
        if current > short_ma * 1.02 and short_ma > long_ma * 1.01:
            return Signal(
                market_id=market_data['id'],
                market_title=market_data.get('title', 'Unknown'),
                timestamp=datetime.now(),
                signal_type="MOMENTUM_BREAKOUT",
                severity="HIGH",
                description=f"UPWARD MOMENTUM | Price breaking above trends | "
                           f"Potential continuation",
                old_price=long_ma,
                new_price=current,
                expected_return=(current - long_ma) * 0.8,
                metadata={
                    'short_ma': short_ma,
                    'long_ma': long_ma,
                    'momentum': 'up'
                }
            )
        elif current < short_ma * 0.98 and short_ma < long_ma * 0.99:
            return Signal(
                market_id=market_data['id'],
                market_title=market_data.get('title', 'Unknown'),
                timestamp=datetime.now(),
                signal_type="MOMENTUM_BREAKDOWN",
                severity="HIGH",
                description=f"DOWNWARD MOMENTUM | Price breaking below trends | "
                           f"Potential continuation",
                old_price=long_ma,
                new_price=current,
                expected_return=(long_ma - current) * 0.8,
                metadata={
                    'short_ma': short_ma,
                    'long_ma': long_ma,
                    'momentum': 'down'
                }
            )

        return None

    def _detect_optimism_tax(self, market_data: Dict,
                             trades: List[Dict]) -> Optional[Signal]:
        """
        Detect the "Optimism Tax" — takers overpaying for YES on longshot contracts.

        Based on Becker's research: on low-probability markets (< 20 cents),
        taker flow is heavily skewed toward YES. This creates a persistent edge
        for makers who sell YES (buy NO) at these levels.

        Signals a maker opportunity when:
        - Market YES price is below 0.20 (longshot)
        - Taker flow is heavily YES-skewed (>= 70% YES by volume)
        - Sufficient volume to be meaningful
        """
        if not trades:
            return None

        yes_price = market_data.get('yes_price', 0.5)

        # Only applies to longshots (< 20 cents)
        if yes_price >= 0.20:
            return None

        # Compute taker-side skew
        yes_volume = 0.0
        no_volume = 0.0
        for t in trades:
            amount = float(t.get('amount', 0) or 0)
            if t.get('taker_side', '').lower() == 'yes':
                yes_volume += amount
            else:
                no_volume += amount

        total_volume = yes_volume + no_volume
        if total_volume < 10:  # Need meaningful sample
            return None

        yes_pct = yes_volume / total_volume

        # Need >= 70% YES skew to trigger
        if yes_pct < 0.70:
            return None

        # Severity based on skew magnitude and volume
        if yes_pct >= 0.90 and total_volume >= 100:
            severity = "CRITICAL"
        elif yes_pct >= 0.85 or total_volume >= 200:
            severity = "HIGH"
        elif yes_pct >= 0.75:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        # Expected edge: the difference between taker-implied probability and market price
        # Takers are paying `yes_price` for something worth even less (longshot bias)
        implied_overpay = yes_pct - 0.5  # How much more YES flow than balanced
        expected_edge = implied_overpay * yes_price  # Rough maker profit estimate

        return Signal(
            market_id=market_data['id'],
            market_title=market_data.get('title', 'Unknown'),
            timestamp=datetime.now(),
            signal_type="OPTIMISM_TAX",
            severity=severity,
            description=(
                f"Optimism tax detected | YES taker flow: {yes_pct:.0%} "
                f"(volume: {total_volume:.0f}) at {yes_price:.0%} | "
                f"Sell YES / Buy NO opportunity | "
                f"{market_data.get('title', 'Unknown')[:60]}"
            ),
            old_price=yes_price,
            new_price=yes_price,
            expected_return=expected_edge,
            metadata={
                'yes_taker_pct': yes_pct,
                'yes_volume': yes_volume,
                'no_volume': no_volume,
                'total_volume': total_volume,
                'market_yes_price': yes_price,
                'strategy': 'sell_yes_buy_no',
            }
        )
