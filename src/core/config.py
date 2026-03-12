"""
Pythia Live - Real-time Prediction Market Intelligence
Configuration
"""
import os
from dataclasses import dataclass
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "pythia_live.db"

@dataclass
class Config:
    # Database
    DB_PATH = os.getenv("PYTHIA_DB_PATH", str(_DEFAULT_DB_PATH))
    
    # Polling intervals (seconds)
    POLL_INTERVAL = 30  # Main loop
    PRICE_CHECK_INTERVAL = 60  # Price movement checks
    
    # Signal thresholds
    PROBABILITY_SPIKE_THRESHOLD = 0.05  # 5% move
    VOLUME_SPIKE_THRESHOLD = 3.0  # 3x average volume
    ARBITRAGE_THRESHOLD = 0.02  # 2% edge minimum
    PROB_ENGINE_WINDOW_HOURS = 168  # 7-day fitting window
    
    # Risk limits
    MAX_POSITION_PCT = 0.25  # 25% max position
    MAX_DAILY_LOSS = 0.10  # 10% daily stop
    EVT_CONFIDENCE_LEVEL = 0.99
    EVT_LOOKBACK_DAYS = 30
    EVT_THRESHOLD_PERCENTILE = 0.90
    MAX_PORTFOLIO_VAR_PCT = 0.05
    STRESS_TEST_INTERVAL = 3600
    EMERGENCY_ES_THRESHOLD = 0.15

    # Calibration
    CALIBRATION_WINDOW_DAYS = 30
    CALIBRATION_CHECK_INTERVAL = 100

    # Cross-correlation
    MIN_CORRELATION_HISTORY = 20
    CORRELATION_REFRESH_CYCLES = 50
    CORRELATION_BREAKDOWN_ZSCORE = 2.0
    MAX_CORRELATED_EXPOSURE_PENALTY = 0.60
    
    # Market filters
    MIN_LIQUIDITY = 10000  # $10k minimum
    MIN_VOLUME_24H = 5000  # $5k daily volume
    
    # Signal cooldown (seconds)
    SIGNAL_COOLDOWN = 300  # 5 minutes

    # Attribution engine mode: fast (PCE), deep (RCE), shadow (PCE + RCE eval)
    ATTRIBUTION_MODE = os.getenv("PYTHIA_ATTRIBUTION_MODE", "fast").strip().lower()
    # BACE depth: 1=fast, 2=standard, 3=deep
    BACE_DEPTH = int(os.getenv("PYTHIA_BACE_DEPTH", "2"))
