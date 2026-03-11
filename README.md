# Pythia

**Prediction market intelligence engine. Detects probability spikes, attributes their causes, and predicts downstream market effects.**

Built for institutional traders and quant researchers. Monitors Polymarket and Kalshi in real-time.

**Demo:** [pythia-demo.vercel.app](https://pythia-demo.vercel.app)

---

## What Pythia Does

1. **Detects** — Monitors prediction markets for probability spikes (≥5% in 1h), volume anomalies (≥3x baseline), maker edge opportunities, and momentum breakouts
2. **Attributes** — Identifies *why* a spike happened using a multi-layer causal pipeline: entity extraction → news retrieval → LLM relevance filtering → causal reasoning → statistical validation
3. **Predicts** — Walks the causal graph forward to generate signals for downstream markets that haven't moved yet
4. **Tracks** — Resolves predictions against actual prices. Measures hit rate, lead time, and calibration.

---

## Architecture

```
Detection → Attribution → Attributor Storage → Forward Signals → Track Record
                │                                                      │
           (fast or deep)                                              │
                │                                                      │
       ┌────────┴─────────┐                                           │
       │   PCE (default)   │  3 LLM calls, ~$0.03/spike               │
       │   causal_v2.py    │  Production path                         │
       ├───────────────────┤                                           │
       │   RCE (deep mode) │  ~35 LLM calls, ~$0.40/spike             │
       │   rce_engine.py   │  Experimental — multi-agent debate        │
       └──────────────────┘                                           │
                                                                       │
         Evaluated by track_record.py ◄────────────────────────────────┘
```

### Core Pipeline (Production)

| Layer | Module | What |
|---|---|---|
| Detection | `src/detection/detector.py` | 4 signal strategies: spike, volume, maker edge, momentum |
| Context | `src/core/causal_v2.py` | Entity extraction, concurrent spike detection |
| News Retrieval | `src/core/causal_v2.py` | NewsAPI, Google News RSS, DuckDuckGo, Reddit — temporal filtered |
| LLM Filter | `src/core/causal_v2.py` | Sonnet scores candidate relevance |
| Causal Reasoning | `src/core/causal_v2.py` | Opus determines most likely cause + confidence |
| Statistical Validation | `src/core/counterfactual.py` | CausalImpact / z-score filters false positives |
| DAG Refutation | `src/core/causal_dag.py` | DoWhy formal causal graphs + refutation tests |
| Effect Prediction | `src/core/heterogeneous_effects.py` | EconML CausalForestDML predicts magnitude by market type |
| Storage | `src/core/attributor_engine.py` | Persistent causal entities with 3-tier confidence (active/unconfirmed/eliminated) |
| Propagation | `src/core/forward_signals.py` | PCMCI causal graph → downstream market predictions |
| Evaluation | `src/core/track_record.py` | Hit rate, calibration, lead time, realized P&L |

### RCE — Reverse Causal Engine (Experimental)

Multi-agent adversarial attribution inspired by MiroFish/OASIS simulation architecture. Higher accuracy on complex spikes, ~13x cost of PCE. Not yet wired into production — will be activated via `PYTHIA_ATTRIBUTION_MODE=deep` once evaluated against PCE on real spikes.

| Module | What |
|---|---|
| `src/core/rce_ontology.py` | Rich entity-relationship extraction (12-20 typed entities vs PCE's 3-5 keywords) |
| `src/core/rce_agents.py` | 7 agents: 5 domain specialists + 2 adversarial (Devil's Advocate, Null Hypothesis) |
| `src/core/rce_engine.py` | Orchestrator: propose → debate (2 rounds) → counterfactual test → surviving attributors |

### Frontend

Next.js 16 dashboard deployed on Vercel.

| Component | What |
|---|---|
| `frontend/app/page.tsx` | Hero panel with market carousel, category filters, market cards |
| `frontend/components/SpikeChart.tsx` | 30-day price chart with spike detection, volume bars, crosshair tooltip, 3-tier attributor popups |
| `frontend/components/CausalGraphView.tsx` | PCE pipeline visualization — shows elimination funnel from candidates to final attributors |

---

## Quick Start

### Backend

```bash
pip install -r requirements.txt

# Monitor mode — detect and alert
python3 run.py

# With paper trading automation
python3 run.py --auto

# Backfill historical spikes (recommended first run)
python3 scripts/backfill_spikes.py --markets 50

# API server
uvicorn src.core.api:app --reload
```

### Frontend

```bash
cd frontend && npm install && npm run dev
# http://localhost:3000 — auto-deploys to Vercel on push
```

### LLM Configuration

Supports multiple backends. Default: Qwen (cheapest).

```bash
# Copy .env.example to .env and set:
PYTHIA_LLM_BACKEND=openai
PYTHIA_LLM_API_KEY=sk-xxxxx
PYTHIA_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
PYTHIA_LLM_MODEL=qwen-plus
PYTHIA_LLM_MODEL_STRONG=qwen-max
```

| Provider | Cost/spike (PCE) | Cost/spike (RCE) |
|---|---|---|
| Qwen (recommended) | ~$0.03 | ~$0.40 |
| DeepSeek | ~$0.02 | ~$0.30 |
| Ollama (local) | $0 | $0 |
| Claude | ~$0.30 | ~$3.00 |

---

## Signal Types

| Signal | Threshold |
|---|---|
| `PROBABILITY_SPIKE` | ≥5% in 1h |
| `VOLUME_ANOMALY` | ≥3x normal volume |
| `MAKER_EDGE` | ≥1% spread |
| `MOMENTUM_BREAKOUT` | MA crossover |
| `CAUSAL_PROPAGATION` | Forward signal via causal graph |

## Causal Inference Stack

| Library | Purpose |
|---|---|
| Tigramite (PCMCI) | Directional causal discovery |
| pyCausalImpact | Bayesian counterfactual validation |
| DoWhy | Formal causal DAGs + refutation |
| EconML | Heterogeneous treatment effects |
| Transfer Entropy | Information flow detection |

## Risk Controls (Paper Trading)

- EVT-aware Kelly sizing (max 25%)
- Daily loss limit: 10%, Max drawdown: 20%
- Correlation penalty for concentrated exposure
- Hourly portfolio snapshots

---

## Project Structure

```
pythia/
├── src/
│   ├── core/
│   │   ├── main.py                    # Orchestrator
│   │   ├── causal_v2.py              # PCE attribution (production)
│   │   ├── rce_engine.py             # RCE attribution (experimental)
│   │   ├── rce_agents.py             # Agent personas + debate
│   │   ├── rce_ontology.py           # Entity-relationship extraction
│   │   ├── attributor_engine.py       # Persistent causal entities
│   │   ├── forward_signals.py         # Causal propagation
│   │   ├── track_record.py           # Prediction accuracy
│   │   ├── llm_integration.py         # Multi-backend LLM
│   │   ├── counterfactual.py          # CausalImpact validation
│   │   ├── causal_dag.py             # DoWhy DAGs
│   │   ├── heterogeneous_effects.py   # EconML effects
│   │   ├── intelligence_api.py        # REST endpoints
│   │   └── database.py               # SQLite
│   ├── detection/detector.py          # Signal detection
│   ├── connectors/                    # Polymarket + Kalshi APIs
│   ├── trading/                       # Paper trading + automation
│   └── alerts/                        # Telegram notifications
├── frontend/                          # Next.js 16 (Vercel)
├── scripts/                           # Backfill + model retraining
└── tests/
```

---

## Credits

Built by **XJ (Jie Xi)** & **Bangshan**
