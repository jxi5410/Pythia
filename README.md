# Pythia

**Context engine for prediction market probability spikes.**

Pythia detects significant probability movements in prediction markets, surfaces the context behind those moves, and delivers actionable intelligence.

## What It Does

1. **Monitors** — Polls Polymarket (CLOB) and Kalshi for real-time price and volume data
2. **Detects** — Identifies probability spikes, volume anomalies, maker edge opportunities, and momentum breakouts
3. **Contextualizes** — Explains *why* a move is happening, not just *that* it happened
4. **Alerts** — Pushes high-conviction signals via Telegram with context annotations
5. **Simulates** — Paper trades signals with Kelly sizing and institutional risk controls

## Quick Start

```bash
pip install -r requirements.txt

# Monitor mode — detect and alert only
python run.py

# Automation mode — paper trading from signals
python run.py --auto

# Dashboard — Streamlit web interface
python run.py --dash
```

## Architecture

```
pythia/
├── run.py                      # Entry point
├── config.json                 # Runtime configuration
├── requirements.txt
├── src/
│   ├── core/
│   │   ├── main.py             # Orchestrator — polling + signal loop
│   │   ├── config.py           # Settings and environment
│   │   └── database.py         # SQLite persistence layer
│   ├── detection/
│   │   └── detector.py         # Signal detection (4 strategies)
│   ├── connectors/
│   │   ├── polymarket.py       # Polymarket CLOB API
│   │   └── kalshi.py           # Kalshi event contracts API
│   ├── trading/
│   │   ├── paper_trading.py    # Simulated execution + P&L
│   │   └── automation.py       # Auto-trade controller
│   └── alerts/
│       └── alerts.py           # Telegram notifications
├── dashboard/
│   └── dashboard.py            # Streamlit web UI
├── frontend/                   # Vercel demo app
├── scripts/                    # Utility and deployment scripts
├── tests/                      # Test suite
└── docs/                       # Documentation and architecture notes
```

## Signal Types

| Signal | What It Detects | Threshold |
|---|---|---|
| `PROBABILITY_SPIKE` | Large price moves in short windows | ≥5% in 1h |
| `VOLUME_ANOMALY` | Unusual trading activity vs baseline | ≥3x normal volume |
| `MAKER_EDGE` | Liquidity provision opportunities | ≥1% spread |
| `MOMENTUM_BREAKOUT` | Trend continuation signals | MA crossover |

## Data Sources

- **Polymarket** — Central limit order book (CLOB) API for orderbook data
- **Kalshi** — Regulated event contracts

## Risk Controls (Paper Trading)

- Half-Kelly position sizing (max 25% per trade)
- Daily loss limit: 10%
- Max drawdown: 20%
- Max 10 trades/day
- Hourly portfolio snapshots
- End-of-day Telegram performance reports

## Performance Targets

Based on prediction market microstructure research (Becker model):

- Maker edge: +0.77% to +1.25% per trade
- Target Sharpe: >1.5
- Max drawdown: <20%
- Win rate: >55%

## Telegram Alerts

```bash
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

## Roadmap

1. **Live execution** — Exchange API integration for real order placement
2. **ML signals** — Model-driven signal detection
3. **Multi-market correlation** — Portfolio-level strategies
4. **Backtesting** — Walk-forward analysis on historical data

## Credits

Built by XJ & Bangshan
