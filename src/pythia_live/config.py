"""
Pythia Live - Real-time Prediction Market Intelligence
Configuration
"""
import os
from dataclasses import dataclass

@dataclass
class Config:
    # Database
    DB_PATH = "data/pythia_live.db"
    
    # Telegram (for alerts)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8280876077")
    
    # Polling intervals (seconds)
    POLL_INTERVAL = 30  # Main loop
    PRICE_CHECK_INTERVAL = 60  # Price movement checks
    
    # Signal thresholds
    PROBABILITY_SPIKE_THRESHOLD = 0.05  # 5% move
    VOLUME_SPIKE_THRESHOLD = 3.0  # 3x average volume
    ARBITRAGE_THRESHOLD = 0.02  # 2% edge minimum
    
    # Risk limits
    MAX_POSITION_PCT = 0.25  # 25% max position
    MAX_DAILY_LOSS = 0.10  # 10% daily stop
    
    # Market filters
    MIN_LIQUIDITY = 10000  # $10k minimum
    MIN_VOLUME_24H = 5000  # $5k daily volume
    
    # Signal cooldown (seconds)
    SIGNAL_COOLDOWN = 300  # 5 minutes
