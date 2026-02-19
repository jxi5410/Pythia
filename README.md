# Pythia Live

🎯 **Real-time Prediction Market Intelligence Engine**

Built for institutional traders. Detects alpha in prediction markets before retail catches on.

## Quick Start

```bash
cd /Users/xj.ai/.openclaw/workspace/Pythia.live
pip install -r requirements.txt

# Start monitoring only
python run.py

# Start with automation (paper trading mode)
python run.py --auto

# Start web dashboard
python run.py --dash
```

## Architecture

### Core Components

| Module | Purpose |
|--------|---------|
| `main.py` | Market data polling, signal detection |
| `detector.py` | 4 signal strategies (spike, volume, maker edge, momentum) |
| `alerts.py` | Telegram notifications |
| `database.py` | SQLite for prices, signals, trades |
| `paper_trading.py` | Simulated execution with P&L tracking |
| `automation.py` | Auto-trade from HIGH/CRITICAL signals |
| `dashboard.py` | Streamlit web interface |

### Signal Types

| Signal | Description | Threshold |
|--------|-------------|-----------|
| **PROBABILITY_SPIKE** | Large price moves | ≥5% in 1h |
| **VOLUME_ANOMALY** | Unusual trading activity | ≥3x normal volume |
| **MAKER_EDGE** | Liquidity provision opportunity | ≥1% spread |
| **MOMENTUM_BREAKOUT** | Trend continuation | MA crossover |

## Data Sources

- **Polymarket** — CLOB API (orderbook data)
- **Kalshi** — Event contracts

## Automation Features

When running with `--auto`:

- ✅ Auto-create paper trades from HIGH/CRITICAL signals
- ✅ Kelly Criterion position sizing (Half Kelly, max 25%)
- ✅ Risk limits: Daily loss (10%), Max drawdown (20%)
- ✅ Max 10 trades/day
- ✅ Hourly portfolio snapshots
- ✅ End-of-day Telegram reports

## Dashboard

```bash
python run.py --dash
# Opens at http://localhost:8504
```

Features:
- Real-time signal feed
- Performance analytics
- Market liquidity overview
- Export to CSV

## Telegram Alerts

Set environment variables:
```bash
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="8280876077"
```

Or edit `config.json`.

## Paper Trading Results

Track simulated P&L:
- Win rate by signal type
- Total return vs benchmark
- Open position exposure
- Risk-adjusted returns

## Monitoring with Mission Control

Mission Control (separate dashboard) monitors Pythia Live status:
```bash
cd /Users/xj.ai/.openclaw/workspace/MissionControl
./start.sh  # http://localhost:8503
```

## File Structure

```
Pythia.live/
├── run.py                  # Main entry point
├── dashboard.py            # Streamlit web UI
├── config.json             # Runtime configuration
├── requirements.txt
├── src/pythia_live/
│   ├── main.py            # Core orchestrator
│   ├── config.py          # Settings
│   ├── database.py        # SQLite layer
│   ├── detector.py        # Signal detection
│   ├── alerts.py          # Telegram integration
│   ├── paper_trading.py   # Simulated trading
│   ├── automation.py      # Auto-trade controller
│   └── connectors/
│       ├── polymarket.py  # Polymarket CLOB API
│       └── kalshi.py      # Kalshi API
└── data/
    └── pythia_live.db     # SQLite database
```

## Performance Targets

Based on hedge fund research (Becker model):
- Maker edge: +0.77% to +1.25% per trade
- Target Sharpe: >1.5
- Max drawdown: <20%
- Win rate: >55%

## Next Steps

1. **Live trading** — Integrate with exchange APIs for real execution
2. **ML signals** — Add ML-based signal detection
3. **Portfolio optimization** — Multi-market correlation strategies
4. **Backtesting** — Walk-forward analysis on historical data

## Credits

Built by XJ & Bangshan  
Architecture inspired by quant trading research on prediction market microstructure.
