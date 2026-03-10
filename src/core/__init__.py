"""
Pythia Live — Real-time prediction market intelligence engine.
"""

from .database import PythiaDB
from .config import Config

# detector lives in src/detection/ — import with fallback
try:
    from .detector import Signal, SignalDetector
except ImportError:
    try:
        from detection.detector import Signal, SignalDetector
    except ImportError:
        Signal = None
        SignalDetector = None

try:
    from .spike_archive import SpikeEvent, detect_spike, attribute_spike, save_spike, get_spike_history, tag_spike
except ImportError:
    pass

try:
    from .patterns import CausalPattern, build_patterns, find_matching_pattern, format_pattern_insight
    from .alert_relay import relay_signal
    from .asset_map import classify_market
    from .correlations import find_correlated_markets
    from .news_context import get_news_context
except ImportError:
    pass
