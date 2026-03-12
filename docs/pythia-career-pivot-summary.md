# Pythia — Career Pivot Summary

## What It Is

Pythia is a **prediction market intelligence engine** that detects probability spikes and anomalies across Polymarket and Kalshi, then explains *why* they happened using multi-agent causal reasoning.

Built by XJ (Jie Xi) and cofounder Bangshan. Two-person team augmented by AI agents for execution.

---

## Architecture (Current — Multi-Scenario)

### BACE — Backward Attribution Causal Engine

The core differentiator. A multi-agent causal attribution system that:

1. **Detects spikes** — Monitors prediction markets for ≥5% moves, 3x volume anomalies, liquidity edge, momentum breakouts
2. **Builds a causal ontology** — Entity-relationship graph extraction (People, Organizations, Policies, Data Releases, Markets, Geopolitical Events) with typed relationships (triggers, correlates_with, announced, contradicts)
3. **Spawns specialist agents** — 9 domain-specific AI agents (Macro Policy, Informed Flow, Narrative/Sentiment, Cross-Market, Geopolitical, Regulatory, Technical Microstructure, Devil's Advocate, Null Hypothesis)
4. **Runs adversarial cross-examination** — Agents respond to each other's hypotheses (support, challenge, subsume, neutral). Convergence groups and divergence pairs form organically.
5. **Clusters into competing scenarios** — Hypotheses grouped by causal mechanism into Primary, Alternative, and Dismissed scenarios. Each scenario has: confidence score, lead + supporting agents, evidence chain, causal narrative, "what breaks this scenario", and temporal fit analysis.
6. **Persists to graph memory** — GraphRAG-style entity/relationship/fact storage for cross-attribution intelligence accumulation.

### Frontend — Interactive Intelligence Dashboard

- **TypeScript/Next.js** single-page app on Vercel
- **Force-directed knowledge graph** — Entities and agents appear organically as SSE streams them; convergence/divergence visualized as clustering/conflict edges
- **Scenario tabs** — Primary scenarios as tabs with full evidence chains; alternatives expandable; dismissed with rejection reasoning
- **Post-result interrogation** — Chat interface for follow-up questions ("why did Devil's Advocate disagree?", "what evidence would change Scenario B?")
- **Real SSE streaming** — All visualization mirrors actual backend state, not decorative animation

### Backend — FastAPI on Railway

- SSE streaming with event types: `context`, `ontology`, `evidence`, `agents`, `domain_evidence`, `proposal`, `interaction`, `scenarios`, `graph_update`, `counterfactual`, `result`
- Depth-configurable: Depth 1 (~$0.03), Depth 2 (~$0.15), Depth 3 (~$0.47)
- Governance layer: circuit breakers, decision gates, audit trails
- Multi-LLM: Qwen (default), DeepSeek, Claude, Ollama

---

## Key Differentiators

| Feature | What It Shows |
|---|---|
| Multi-agent causal reasoning | AI product design — not just calling an API |
| Adversarial cross-examination | AI safety thinking — agents challenge each other |
| Scenario-based output (not flat list) | Product sense — users need narratives, not rankings |
| Force-directed knowledge graph | Real-time data visualization, not static mockups |
| Post-result interrogation | AI UX innovation — users explore, not just consume |
| GraphRAG memory accumulation | System design — intelligence compounds across runs |
| Governance layer (audit + circuit breakers) | Enterprise-grade thinking for institutional deployment |

---

## Career Pivot Framing

### General

> "Built a prediction market intelligence engine with multi-agent causal reasoning, adversarial cross-examination, and scenario-based attribution — demonstrates AI product ownership end-to-end."

### For Anthropic / AI Safety Roles

> "Designed a multi-agent system where AI agents propose competing causal hypotheses, then adversarially challenge each other — with governance controls, circuit breakers, and human-in-the-loop decision gates. The architecture embodies responsible AI principles: transparency (full evidence chains), skepticism (Devil's Advocate + Null Hypothesis agents), and auditability (immutable audit trails for every run)."

### For Product/Strategy Leadership

> "End-to-end AI product: problem identification → architecture design → multi-agent system implementation → interactive frontend → deployment pipeline. Two-person team augmented by AI agents for 10x execution leverage. Currently in design partner evaluation with quant traders."

---

## Technical Proof Points

- **9 specialized agents** with domain-specific evidence providers (not generic LLM calls)
- **~15 LLM calls/spike** at depth 2 with cost-conscious architecture (~$0.15/spike on Qwen)
- **Real-time SSE streaming** with organic graph visualization
- **SQLite → GraphRAG** memory for cross-attribution intelligence
- **Paper trading engine** with EVT-aware Kelly sizing and risk controls
- **Dual-exchange** support (Polymarket CLOB + Kalshi regulated contracts)

---

## Status

- **Live demo**: pythia-demo.vercel.app
- **Backend**: Railway auto-deploy from GitHub
- **Stage**: Pre-revenue. Design partner conversations with quant traders.
- **Repo**: github.com/jxi5410/Pythia

---

*Last updated: March 2026. Reflects multi-scenario architecture (commit 8894332+).*
