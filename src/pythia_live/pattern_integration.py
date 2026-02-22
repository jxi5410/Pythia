"""
Pattern Library Integration — Enhances signals with Becker-derived patterns.

Loads pythia_pattern_library.json and applies temporal filters,
velocity signatures, and risk filters to live signals.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .detector import Signal

logger = logging.getLogger(__name__)


class PatternLibrary:
    """Loads and queries the Becker-derived pattern library."""

    def __init__(self, library_path: Optional[str] = None):
        if library_path is None:
            # Look in workspace root
            workspace = Path(__file__).parent.parent.parent.parent
            library_path = workspace / "pythia_pattern_library.json"
        else:
            library_path = Path(library_path)

        self.library_path = library_path
        self.data = self._load_library()

    def _load_library(self) -> Dict:
        """Load pattern library from JSON."""
        try:
            with open(self.library_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load pattern library: {e}")
            return {}

    def get_temporal_context(self, hour: Optional[int] = None) -> Dict:
        """
        Get temporal context for current hour.

        Returns which time window we're in and its characteristics.
        """
        if hour is None:
            hour = datetime.now().hour

        temporal = self.data.get('temporal_patterns', {})

        # Check each window
        evening = temporal.get('evening_news_window', {})
        asia = temporal.get('asia_open', {})
        quiet = temporal.get('quiet_hours', {})

        if hour in evening.get('hours', []):
            return {
                'window': 'evening_news',
                'quality': evening.get('signal_quality', 'High'),
                'characteristics': evening.get('characteristics', ''),
                'peak_hour': evening.get('peak_hour')
            }
        elif hour in asia.get('hours', []):
            return {
                'window': 'asia_open',
                'quality': asia.get('signal_quality', 'Medium'),
                'characteristics': asia.get('characteristics', '')
            }
        elif hour in quiet.get('hours', []):
            return {
                'window': 'quiet_hours',
                'quality': quiet.get('signal_quality', 'Low'),
                'characteristics': quiet.get('characteristics', '')
            }
        else:
            return {
                'window': 'normal',
                'quality': 'Medium',
                'characteristics': 'Regular trading hours'
            }

    def get_velocity_signature(self, velocity: float) -> Dict:
        """
        Classify velocity into signature type.

        Velocity = price_change / time (in % per minute)
        """
        signatures = self.data.get('velocity_signatures', [])

        for sig in signatures:
            v_range = sig.get('velocity_range', [0, 0])
            if v_range[0] <= velocity < v_range[1]:
                return sig

        return signatures[0] if signatures else {
            'name': 'unknown',
            'characteristics': 'Unclassified velocity'
        }

    def check_trading_signal(self, hour: int, velocity: float,
                             volume: float, change_pct: float) -> Optional[Dict]:
        """
        Check if current conditions match any defined trading signals.

        Returns matching signal or None.
        """
        signals = self.data.get('trading_signals', [])

        for sig in signals:
            sid = sig.get('id', '')
            conditions = sig.get('conditions', [])

            # SIG-001: Evening Momentum Burst
            if sid == 'SIG-001':
                if hour in [18, 19, 20] and velocity > 75 and volume > 10000:
                    return sig

            # SIG-002: Late Night Fade
            elif sid == 'SIG-002':
                if hour in [2, 3, 4] and change_pct > 0.15:
                    return sig

            # SIG-003: Extreme Spike Alert
            elif sid == 'SIG-003':
                if change_pct > 0.50:  # 50% in 5 min = extreme
                    return sig

        return None

    def apply_risk_filters(self, volume: float, change_pct: float,
                          last_trade_minutes: Optional[float] = None) -> Tuple[bool, List[str]]:
        """
        Apply risk filters from pattern library.

        Returns: (passes_filters, list_of_warnings)
        """
        filters = self.data.get('risk_filters', [])
        warnings = []

        for f in filters:
            name = f.get('name', '')
            action = f.get('action', '')

            if name == 'illiquidity_filter':
                threshold = f.get('condition', '').replace('Volume < ', '')
                try:
                    threshold = int(threshold)
                    if volume < threshold:
                        warnings.append(f"Low volume: {volume:.0f} < {threshold}")
                        if action == 'exclude':
                            return False, warnings
                except:
                    pass

            elif name == 'data_error_filter':
                threshold = f.get('condition', '').replace('Change > ', '')
                try:
                    threshold = int(threshold.replace('%', ''))
                    if change_pct * 100 > threshold:
                        warnings.append(f"Extreme change: {change_pct:.1%} — possible data error")
                        if action == 'flag_for_review':
                            warnings.append("⚠️ FLAGGED FOR REVIEW")
                except:
                    pass

            elif name == 'stale_market_filter':
                if last_trade_minutes and last_trade_minutes > 60:
                    warnings.append(f"Stale market: no trades in {last_trade_minutes:.0f} min")
                    if action == 'exclude':
                        return False, warnings

        return len(warnings) == 0 or True, warnings

    def enhance_signal(self, signal) -> "Signal":
        """
        Enhance a detected signal with pattern library context.

        Adds:
        - Temporal context (time window quality)
        - Velocity signature classification
        - Trading signal match (SIG-001, SIG-002, SIG-003)
        - Risk filter warnings
        """
        metadata = signal.metadata or {}

        # 1. Temporal context
        temporal = self.get_temporal_context()
        metadata['temporal_context'] = temporal

        # Boost/reduce severity based on time window
        if temporal['window'] == 'evening_news' and temporal['quality'] == 'High':
            metadata['quality_boost'] = 'Evening window — institutional activity likely'
        elif temporal['window'] == 'quiet_hours':
            metadata['quality_discount'] = 'Quiet hours — lower liquidity, higher noise'

        # 2. Velocity signature
        velocity = metadata.get('velocity', 0)
        if velocity:
            v_sig = self.get_velocity_signature(velocity)
            metadata['velocity_signature'] = v_sig

        # 3. Check for specific trading signals
        hour = datetime.now().hour
        volume = metadata.get('current_volume', 0)
        change_pct = metadata.get('change_pct', 0)

        trading_sig = self.check_trading_signal(hour, velocity, volume, change_pct)
        if trading_sig:
            metadata['pattern_match'] = {
                'signal_id': trading_sig.get('id'),
                'signal_name': trading_sig.get('name'),
                'action': trading_sig.get('action'),
                'historical_frequency': trading_sig.get('historical_frequency')
            }
            # Add pattern insight to description
            signal.description += f" | PATTERN: {trading_sig.get('name')}"

        # 4. Risk filters
        last_trade = metadata.get('minutes_since_last_trade')
        passes, warnings = self.apply_risk_filters(volume, change_pct, last_trade)
        if warnings:
            metadata['risk_warnings'] = warnings
            if not passes:
                metadata['filtered'] = True

        signal.metadata = metadata
        return signal


def enrich_signals_with_patterns(signals: List[Signal],
                                 library_path: Optional[str] = None) -> List[Signal]:
    """
    Convenience function: enrich list of signals with pattern library context.
    """
    library = PatternLibrary(library_path)
    return [library.enhance_signal(s) for s in signals]
