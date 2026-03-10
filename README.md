# Pythia

**Narrative intelligence engine for prediction markets.**

Pythia detects probability spikes in prediction markets, identifies their causes as persistent **attributors**, and propagates forward signals to predict downstream market moves — before they happen.

## What It Does

1. **Monitors** — Polls Polymarket (CLOB) and Kalshi for real-time price and volume data
2. **Detects** — Identifies probability spikes, volume anomalies, maker edge opportunities, and momentum breakouts
3. **Attributes** — 8-layer hybrid statistical + LLM pipeline explains *why* a move happened, validated by Bayesian counterfactual analysis and causal DAGs
4. **Predicts** — Walks the causal graph forward to generate actionable signals for downstream markets that haven't moved yet
5. **Learns** — Tracks prediction accuracy, adjusts confidence from user feedback, retrains effect models weekly

## Pythia Causal Engine (PCE)

The core differentiator. An 8-layer hybrid pipeline combining statistical causal inference with LLM reasoning:

| Layer | What | Method |
|---|---|---|
| 1 | Context Builder | Keyword classification + entity extraction |
| 1.5 | Counterfactual Validation | CausalImpact / z-score — filters false positives before LLM calls |
| 2 | News Retrieval | Multi-source (NewsAPI, Google News, DuckDuckGo, Reddit) |
| 3 | Candidate Filter | LLM relevance scoring (Sonnet) |
| 4 | Causal Reasoning | LLM deep analysis (Opus) with statistical evidence |
| 4.5 | DAG Refutation | DoWhy formal causal graphs + refutation tests per category |
| 4.6 | Heterogeneous Effects | EconML CausalForestDML — predicts expected effect size by market type |
| 5 | Store & Learn | Feedback loop, outcome tracking, model retraining |

## Attributors & Forward Signals

**Attributors** are persistent causal entities — the fundamental intelligence unit.

When a spike occurs, PCE extracts an attributor (e.g., "Fed hawkish surprise"). That attributor is tracked across markets and time. When it fires, Pythia walks the PCMCI causal graph to predict which downstream markets will move, by how much, and when.

**Forward signals** are time-stamped predictions: "Market B will move up ~3% within 2 hours because of attributor X in Market A." Signals have user-tunable confidence thresholds and are resolved against actual prices for accuracy tracking.

## Quick Start

```bash
pip install -r requirements.txt

# Monitor mode — detect and alert only
python3 run.py

# Automation mode — paper trading from signals
python3 run.py --auto

# Backfill historical spikes from Polymarket (recommended first run)
python3 scripts/backfill_spikes.py --markets 50 --threshold 0.02

# Retrain heterogeneous effects model
python3 scripts/retrain_model.py

# API server
uvicorn src.core.api:app --reload
```

## API

Intelligence endpoints (all under `/api/v1`):

| Endpoint | What |
|---|---|
| `GET /analyze/{market_id}` | On-demand full analysis: price history + spikes + attributors + forward signals |
| `GET /attributors` | List active/fading/resolved attributors |
| `GET /markets/{id}/attributors` | Attributors linked to a specific market |
| `GET /signals/forward` | Pending forward signal predictions |
| `GET /narratives` | Auto-clustered narrative groups |
| `POST /preferences/thresholds` | Set user confidence thresholds for spike/attribution/signal |
| `GET /watchlists/{name}/signals` | Forward signals for watchlisted markets |
| `POST /feedback` | Submit feedback for PCE self-learning |

## Architecture

```
pythia/
├── run.py                           # Entry point
├── config.json                      # Runtime configuration
├── src/
│   ├── core/
│   │   ├── main.py                  # Orchestrator — polling + signal loop
│   │   ├── api.py                   # FastAPI REST API
│   │   ├── intelligence_api.py      # Attributor, signal, narrative endpoints
│   │   ├── database.py              # SQLite persistence layer
│   │   ├── causal_v2.py             # 8-layer PCE attribution pipeline
│   │   ├── attributor_engine.py     # Persistent causal entities + lifecycle
│   │   ├── forward_signals.py       # Causal graph propagation + predictions
│   │   ├── counterfactual.py        # CausalImpact spike validation
│   │   ├── causal_discovery.py      # PCMCI + Transfer Entropy
│   │   ├── causal_dag.py            # DoWhy formal DAGs per category
│   │   ├── heterogeneous_effects.py # EconML CausalForestDML
│   │   ├── confluence.py            # Multi-layer signal convergence
│   │   ├── calibration.py           # Brier score tracking
│   │   └── cross_correlation.py     # Spearman + factor decomposition
│   ├── detection/
│   │   └── detector.py              # Signal detection (4 strategies)
│   ├── connectors/
│   │   ├── polymarket.py            # Polymarket CLOB API
│   │   └── kalshi.py                # Kalshi event contracts API
│   ├── trading/
│   │   ├── paper_trading.py         # Simulated execution + P&L
│   │   └── automation.py            # Auto-trade controller
│   └── alerts/
│       └── alerts.py                # Signal formatting
├── frontend/                        # Next.js demo (Vercel)
│   └── components/
│       └── SpikeChart.tsx           # 30-day chart with spike overlay
├── scripts/
│   ├── backfill_spikes.py           # Historical spike ingestion from Polymarket
│   └── retrain_model.py             # Weekly P3 model retraining
└── tests/
```

## Signal Types

| Signal | What It Detects | Threshold |
|---|---|---|
| `PROBABILITY_SPIKE` | Large price moves in short windows | ≥2% in 2h |
| `VOLUME_ANOMALY` | Unusual trading activity vs baseline | ≥3x normal volume |
| `MAKER_EDGE` | Liquidity provision opportunities | ≥1% spread |
| `MOMENTUM_BREAKOUT` | Trend continuation signals | MA crossover |
| `CAUSAL_PROPAGATION` | Forward signal from attributor via causal graph | User-configurable |

## Causal Inference Stack

| Library | Purpose |
|---|---|
| Tigramite (PCMCI) | Directional causal discovery between markets |
| Transfer Entropy | Information flow detection (lead-lag) |
| pyCausalImpact | Bayesian counterfactual spike validation |
| DoWhy | Formal causal DAGs with refutation tests |
| EconML | Heterogeneous treatment effects by market type |

## Data Sources

- **Polymarket** — CLOB API for orderbook data + historical price series
- **Kalshi** — Regulated event contracts

## Risk Controls (Paper Trading)

- Half-Kelly position sizing (max 25% per trade)
- Daily loss limit: 10%
- Max drawdown: 20%
- Max 10 trades/day
- Hourly portfolio snapshots

## Credits

Built by XJ & Bangshan
