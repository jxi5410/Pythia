# Pythia Live

Real-time prediction market intelligence engine.

## Features

- **Multi-source data**: Polymarket, Kalshi
- **Signal detection**: Probability spikes, volume anomalies, maker edges, momentum
- **Real-time alerts**: Telegram notifications for HIGH/CRITICAL signals
- **SQLite storage**: Historical data and signal tracking
- **Risk management**: Position sizing, cooldowns, correlation tracking

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set Telegram config (optional, for alerts)
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="8280876077"

# Run
python run.py
```

## Signal Types

| Signal | Description | Threshold |
|--------|-------------|-----------|
| PROBABILITY_SPIKE | Large price moves | ≥5% in 1h |
| VOLUME_ANOMALY | Unusual trading | ≥3x normal |
| MAKER_EDGE | Liquidity provision | ≥1% spread |
| MOMENTUM | Trend breakout | MA crossover |

## Architecture

```
run.py
  └── main.py (orchestrator)
        ├── connectors/
        │     ├── polymarket.py
        │     └── kalshi.py
        ├── detector.py
        ├── alerts.py
        ├── database.py
        └── config.py
```
