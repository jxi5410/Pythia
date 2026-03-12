# Pythia

**Prediction market intelligence engine. Detects probability spikes, attributes their causes, and predicts downstream market effects.**

Built for institutional traders and quant researchers. Monitors Polymarket and Kalshi in real-time.

**Demo:** [pythia-demo.vercel.app](https://pythia-demo.vercel.app)

---

## What Pythia Does

1. **Detects** — Monitors prediction markets for probability spikes (≥5% in 1h), volume anomalies (≥3x baseline), maker edge opportunities, and momentum breakouts
2. **Attributes** — Identifies *why* a spike happened using BACE (Backward Attribution Causal Engine) — a depth-configurable pipeline combining multi-agent reasoning, domain-specific evidence, and statistical validation
3. **Predicts** — Walks the causal graph forward to generate signals for downstream markets that haven't moved yet
4. **Tracks** — Resolves predictions against actual prices. Measures hit rate, lead time, and calibration.

---

## BACE — Backward Attribution Causal Engine

One engine, three depth levels. Configure via `PYTHIA_BACE_DEPTH=1|2|3`.

```
Detection → BACE Attribution → Attributor Storage → Forward Signals → Track Record
               │                                                          │
          depth 1|2|3                                                     │
               │                                                          │
  ┌────────────┼─────────────────────────────┐                           │
  │ Depth 1    │ Depth 2 (default)           │ Depth 3                   │
  │ FAST       │ STANDARD                    │ DEEP                      │
  │ ~3 LLM     │ ~15 LLM calls              │ ~95 LLM calls             │
  │ $0.03      │ $0.15/spike                 │ $0.47/spike               │
  │ Single-shot│ Multi-agent proposals       │ Full adversarial debate   │
  │ reasoning  │ + domain evidence           │ + counterfactual testing  │
  └────────────┴─────────────────────────────┘                           │
                                                                          │
       Evaluated by track_record.py ◄─────────────────────────────────────┘
```

### Depth 1 — Fast (~3 LLM calls, ~$0.03/spike)

Single-shot attribution: extract entities → retrieve news → filter candidates → reason about cause.

### Depth 2 — Standard (~15 LLM calls, ~$0.15/spike) **← default**

Multi-agent proposals with domain-specific evidence. 9 agents each propose hypotheses from different data perspectives. No debate rounds — a synthesis step selects the strongest hypothesis.

### Depth 3 — Deep (~95 LLM calls, ~$0.47/spike)

Everything in depth 2 plus 2 rounds of adversarial debate (agents critique each other's hypotheses) and counterfactual testing (would the spike persist if this cause hadn't happened?).

### Agent Roster

**7 core agents** (always active):

| Agent | Domain | Evidence Sources |
|---|---|---|
| Macro Policy Analyst | Central bank, fiscal policy | FedWatch, economic calendar, equities |
| Market Microstructure | Order flow, liquidity | Orderbook snapshots, equity moves |
| Geopolitical Risk | Diplomacy, conflict | Social media signals, equities |
| Regulatory & Legal | SEC, legislation | Congressional trading data, equities |
| Narrative & Sentiment | Social media, crowd behavior | Twitter/X signals |
| Informed Flow Analyst | Insider vs retail detection | Orderbook, equities, crypto flows |
| Cross-Market Contagion | Propagation from other markets | Equities, fixed income, crypto |

**2 adversarial agents** (always active): Devil's Advocate + Null Hypothesis

**6 conditional agents** (spawned per category): On-chain, ETF Flows (crypto), Fixed Income, FX/Carry (fed_rate), Supply Chain (tariffs), Defense Intel (geopolitical)

### Timing-First Reasoning

Every hypothesis must classify its impact speed: immediate (minutes), fast (hours), delayed (days), or slow (weeks). Evidence items carry timing metadata relative to the spike (before/concurrent/after). Agents are instructed that causes must precede effects and concurrent evidence is ambiguous.

### Statistical Validation (all depths, zero LLM cost)

| Layer | Library | What |
|---|---|---|
| Counterfactual | pyCausalImpact | Bayesian test — exits early if spike is noise |
| DAG Refutation | DoWhy | Formal causal graph + refutation tests |
| Effect Prediction | EconML | CausalForestDML predicts expected magnitude |
| Causal Discovery | Tigramite (PCMCI) | Directional discovery between markets |

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
PYTHIA_LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
PYTHIA_LLM_MODEL=qwen-plus
PYTHIA_LLM_MODEL_STRONG=qwen-max

# Attribution depth (1=fast, 2=standard, 3=deep)
PYTHIA_BACE_DEPTH=2
```

| Provider | Cost/spike (depth 1) | Cost/spike (depth 2) | Cost/spike (depth 3) |
|---|---|---|---|
| Qwen (recommended) | ~$0.03 | ~$0.15 | ~$0.47 |
| DeepSeek | ~$0.02 | ~$0.10 | ~$0.35 |
| Ollama (local) | $0 | $0 | $0 |
| Claude | ~$0.30 | ~$1.50 | ~$4.50 |

---

## Signal Types

| Signal | Threshold |
|---|---|
| `PROBABILITY_SPIKE` | ≥5% in 1h |
| `VOLUME_ANOMALY` | ≥3x normal volume |
| `MAKER_EDGE` | ≥1% spread |
| `MOMENTUM_BREAKOUT` | MA crossover |
| `CAUSAL_PROPAGATION` | Forward signal via causal graph |

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
│   │   ├── main.py                      # Orchestrator — polling + signal loop
│   │   ├── bace.py                      # BACE entrypoint — attribute_spike(depth=1|2|3)
│   │   ├── causal_v2.py                 # Depth 1: single-shot fast attribution
│   │   ├── bace_debate.py              # Depth 2-3: multi-agent debate engine
│   │   ├── bace_agents.py              # Agent personas, prompts, timing rules
│   │   ├── bace_ontology.py            # Entity-relationship extraction
│   │   ├── bace_evidence_provider.py   # Per-agent domain-specific data
│   │   ├── market_classifier.py         # Market category classification
│   │   ├── spike_context.py            # Spike context builder
│   │   ├── attributor_engine.py         # Persistent causal entities + lifecycle
│   │   ├── forward_signals.py          # Causal graph propagation → predictions
│   │   ├── track_record.py             # Prediction accuracy tracking
│   │   ├── llm_integration.py          # Multi-backend LLM (Qwen/DeepSeek/Claude/Ollama)
│   │   ├── counterfactual.py           # CausalImpact validation
│   │   ├── causal_dag.py              # DoWhy formal DAGs
│   │   ├── heterogeneous_effects.py    # EconML effect prediction
│   │   ├── intelligence_api.py         # REST endpoints
│   │   ├── feedback.py                 # Attribution feedback loop
│   │   ├── database.py                 # SQLite persistence
│   │   ├── evidence/
│   │   │   └── news_retrieval.py       # Shared news retrieval (4 sources)
│   │   └── evaluation/
│   │       └── attribution_compare.py  # Depth comparison persistence
│   ├── detection/
│   │   └── detector.py                 # Signal detection (4 strategies)
│   ├── connectors/
│   │   ├── polymarket.py               # Polymarket CLOB API
│   │   └── kalshi.py                   # Kalshi event contracts
│   ├── trading/
│   │   ├── paper_trading.py            # Simulated execution + P&L
│   │   └── automation.py               # Auto-trade controller
│   └── alerts/
│       └── alerts.py                   # Telegram notifications
├── frontend/                            # Next.js 16 dashboard (Vercel)
│   ├── app/page.tsx                    # Hero panel + market cards
│   ├── components/SpikeChart.tsx       # Price chart with spike overlay
│   └── components/CausalGraphView.tsx  # Attribution pipeline visualization
├── scripts/
│   ├── backfill_spikes.py              # Historical spike ingestion
│   └── retrain_model.py               # Weekly model retraining
└── tests/
```

---

## Credits

Built by **XJ (Jie Xi)** & **Bangshan**
