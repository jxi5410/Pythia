# Pythia

**Prediction market intelligence engine. Detects probability spikes across Polymarket and Kalshi, then explains *why* they happened using multi-agent causal reasoning.**

Built for institutional traders and quant researchers. Two-person team augmented by AI agents for execution.

**Demo:** [pythia-demo.vercel.app](https://pythia-demo.vercel.app)

---

## What Pythia Does

1. **Detects** — Monitors prediction markets for probability spikes (≥5% in 1h), volume anomalies (≥3x baseline), maker edge opportunities, and momentum breakouts
2. **Attributes** — Identifies *why* a spike happened using BACE (Backward Attribution Causal Engine) — a depth-configurable multi-agent system combining adversarial debate, domain-specific evidence, and scenario clustering
3. **Presents** — Clusters competing hypotheses into Primary, Alternative, and Dismissed scenarios with evidence chains, confidence scores, and "what breaks this" analysis
4. **Interrogates** — Users can question individual agents in-character about their reasoning, evidence, and confidence post-attribution

---

## BACE — Backward Attribution Causal Engine

One engine, three depth levels. Configure via `PYTHIA_BACE_DEPTH=1|2|3`.

```
Detection → BACE Attribution → Scenario Clustering → Graph Memory
               │
          depth 1|2|3
               │
  ┌────────────┼─────────────────────────────┐
  │ Depth 1    │ Depth 2 (default)           │ Depth 3                 │
  │ FAST       │ STANDARD                    │ DEEP                    │
  │ ~3 LLM     │ ~15 LLM calls              │ ~95 LLM calls           │
  │ $0.03      │ $0.15/spike                 │ $0.47/spike             │
  │ Single-shot│ Multi-agent proposals       │ Full adversarial debate │
  │ reasoning  │ + domain evidence           │ + counterfactual testing│
  └────────────┴─────────────────────────────┘
```

### Depth 1 — Fast (~3 LLM calls, ~$0.03/spike)

Single-shot attribution: extract entities → retrieve news → filter candidates → reason about cause.

### Depth 2 — Standard (~15 LLM calls, ~$0.15/spike) **← default**

Multi-agent proposals with domain-specific evidence. 9 agents each propose hypotheses from different data perspectives. Synthesis step selects the strongest hypothesis and clusters into scenarios.

### Depth 3 — Deep (~95 LLM calls, ~$0.47/spike)

Everything in depth 2 plus 2 rounds of adversarial debate (agents critique each other's hypotheses) and counterfactual testing (would the spike persist if this cause hadn't happened?).

### Multi-Agent Architecture

**9 specialized agents**, each with domain-specific evidence providers (not generic LLM calls):

| Agent | Domain | Evidence Sources |
|---|---|---|
| Macro Policy Analyst | Central bank, fiscal policy | FedWatch, economic calendar, equities |
| Market Microstructure | Order flow, liquidity | Orderbook snapshots, equity moves |
| Geopolitical Risk | Diplomacy, conflict | Social media signals, equities |
| Regulatory & Legal | SEC, legislation | Congressional trading data, equities |
| Narrative & Sentiment | Social media, crowd behavior | Twitter/X signals |
| Informed Flow Analyst | Insider vs retail detection | Orderbook, equities, crypto flows |
| Cross-Market Contagion | Propagation from other markets | Equities, fixed income, crypto |
| Devil's Advocate | Challenges all hypotheses | Cross-references all evidence |
| Null Hypothesis | Tests if spike is noise | Statistical baselines |

**8 autonomous action types:** PROPOSE, SUPPORT, CHALLENGE, REBUT, UPDATE_CONFIDENCE, PRESENT_EVIDENCE, CONCEDE, SYNTHESIZE

**Confidence from behavior** — evolves from debate actions (challenges, concessions, rebuttals), not self-assessed scores.

### Scenario-Based Output

Hypotheses are clustered by causal mechanism into competing scenarios:

- **Primary** — Highest-confidence explanation with full evidence chain
- **Alternative** — Plausible alternatives with supporting evidence
- **Dismissed** — Considered and rejected, with rejection reasoning

Each scenario includes: confidence score, lead + supporting agents, evidence chain, causal narrative, "what breaks this scenario", and temporal fit analysis.

### Governance Layer

- **Circuit breakers** — Cost and runtime limits per BACE run
- **Decision gates** — AUTO_RELAY / FLAG_REVIEW / REJECT classification
- **Audit trails** — Immutable JSONL logging of every agent action
- **Autonomy levels** — L0 (human-controlled) through L5 (full autonomy)
- **Configurable** via `governance.yaml` or `PYTHIA_GOV_*` env vars

---

## Frontend — Staged Intelligence Dashboard

4-stage workflow, each with its own route (shareable, resumable):

1. **Market Selection** (`/`) — Search Polymarket/Kalshi markets, spike count badges, interactive price charts
2. **Attribution** (`/attribution`) — Live BACE run with force-directed knowledge graph growing from SSE events, real-time action feed (CHALLENGE=red, SUPPORT=green, REBUT=blue)
3. **Scenarios** (`/scenarios`) — Primary scenario with evidence chains and agent consensus. Alternatives expandable. Dismissed with rejection reasoning. "What breaks this" callouts.
4. **Interrogation** (`/interrogation`) — Select a specific agent, interrogate it in-character about its analysis, evidence, and reasoning via streaming chat

**Visualization:** Force-directed knowledge graph where entities and agents appear organically as SSE streams them. Convergence = clustering, divergence = conflict edges.

---

## Quick Start

### Backend

```bash
pip install -r requirements.txt

# Monitor mode — detect and alert
python3 run.py

# With paper trading automation
python3 run.py --auto

# API server (SSE streaming for frontend)
uvicorn src.api.server:app --reload

# Backfill historical spikes (recommended first run)
python3 scripts/backfill_spikes.py --markets 50
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
│   ├── api/
│   │   └── server.py                    # FastAPI + SSE streaming endpoints
│   ├── core/
│   │   ├── main.py                      # Orchestrator — polling + signal loop
│   │   ├── bace.py                      # BACE entrypoint — attribute_spike(depth=1|2|3)
│   │   ├── bace_parallel.py             # Async BACE pipeline with SSE streaming
│   │   ├── bace_simulation.py           # Multi-round agent debate (8 action types)
│   │   ├── bace_debate.py              # Debate engine (proposals, critique, counterfactual)
│   │   ├── bace_agents.py              # Agent personas, prompts, timing rules
│   │   ├── bace_scenarios.py           # Scenario clustering (primary/alt/dismissed)
│   │   ├── bace_ontology.py            # Entity-relationship extraction (GraphRAG)
│   │   ├── bace_evidence_provider.py   # Per-agent domain-specific data
│   │   ├── bace_interaction.py         # Agent interview mode
│   │   ├── bace_graph_memory.py        # GraphRAG entity/relationship storage
│   │   ├── governance.py               # Circuit breakers, audit trails, decision gates
│   │   ├── causal_v2.py                # Depth 1: single-shot fast attribution
│   │   ├── llm_integration.py          # Multi-backend LLM (Qwen/DeepSeek/Claude/Ollama)
│   │   ├── market_classifier.py        # Market category classification
│   │   ├── spike_context.py            # Spike context builder
│   │   ├── confluence.py               # Multi-layer signal convergence detection
│   │   ├── forward_signals.py          # Causal graph propagation → predictions
│   │   ├── track_record.py             # Prediction accuracy tracking
│   │   ├── database.py                 # SQLite persistence
│   │   ├── evidence/
│   │   │   └── news_retrieval.py       # Shared news retrieval (4 sources)
│   │   └── evaluation/
│   │       └── attribution_compare.py  # Depth comparison persistence
│   ├── connectors/
│   │   ├── polymarket.py               # Polymarket CLOB API
│   │   └── kalshi.py                   # Kalshi event contracts
│   ├── detection/
│   │   └── detector.py                 # Signal detection (4 strategies)
│   ├── trading/
│   │   ├── paper_trading.py            # Simulated execution + P&L
│   │   └── automation.py               # Auto-trade controller
│   └── alerts/
│       └── alerts.py                   # Telegram notifications
├── frontend/                            # Next.js — Staged Intelligence Dashboard
│   ├── app/
│   │   ├── page.tsx                    # Stage 1: Market selection + search
│   │   ├── attribution/page.tsx        # Stage 2: Live BACE run + graph
│   │   ├── scenarios/page.tsx          # Stage 3: Scenario view
│   │   ├── interrogation/page.tsx      # Stage 4: Agent interview
│   │   └── api/                        # Next.js API routes (proxy to backend)
│   │       ├── polymarket/             # Market search + history
│   │       ├── attribute/              # BACE attribution proxy
│   │       └── markets/                # Market data
│   ├── components/
│   │   ├── BACEGraphAnimation.tsx      # Force-directed knowledge graph
│   │   ├── ScenarioPanel.tsx           # Scenario display + evidence chains
│   │   ├── InterrogationChat.tsx       # Agent interview streaming chat
│   │   ├── SpikeChart.tsx              # Price chart with spike overlay
│   │   └── NavHeader.tsx               # Stage progression breadcrumb
│   ├── lib/
│   │   └── run-store.tsx               # Cross-stage state management
│   └── types/
├── governance.yaml                      # Governance config (circuit breakers, gates)
├── scripts/
│   ├── backfill_spikes.py              # Historical spike ingestion
│   └── retrain_model.py               # Weekly model retraining
└── tests/
```

---

## Deployment

| Component | Platform | URL |
|---|---|---|
| Backend API | Railway (auto-deploy from GitHub) | `pythia-production.up.railway.app` |
| Frontend | Vercel (auto-deploy from GitHub) | `pythia-demo.vercel.app` |

---

## Credits

Built by **XJ (Jie Xi)** & **Bangshan**
