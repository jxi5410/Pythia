"""
Pythia Live — Real-time prediction market intelligence engine.
"""

from .database import PythiaDB
from .detector import Signal, SignalDetector
from .config import Config
from .spike_archive import SpikeEvent, detect_spike, attribute_spike, save_spike, get_spike_history, tag_spike
from .patterns import CausalPattern, build_patterns, find_matching_pattern, format_pattern_insight
from .alert_relay import relay_signal
from .asset_map import classify_market
from .correlations import find_correlated_markets
from .news_context import get_news_context
