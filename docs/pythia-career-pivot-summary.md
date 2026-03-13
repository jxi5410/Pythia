# Pythia — Career Pivot Summary

## What It Is

Pythia is a **prediction market intelligence engine** that detects probability spikes and anomalies across Polymarket and Kalshi, then explains *why* they happened using multi-agent causal reasoning.

Built by XJ (Jie Xi) and cofounder Bangshan. Two-person team augmented by AI agents for execution.

---

## Architecture (Current — Multi-Scenario)

### BACE — Backward Attribution Causal Engine

The core differentiator. A multi-agent simulation system for causal attribution:

1. **Detects spikes** — Monitors prediction markets for ≥5% moves, 3x volume anomalies, liquidity edge, momentum breakouts
2. **Builds a causal ontology** — Entity-relationship graph extraction (People, Organizations, Policies, Data Releases, Markets, Geopolitical Events) with typed relationships (triggers, correlates_with, announced, contradicts)
3. **Spawns specialist agents** — 9 domain-specific AI agents (Macro Policy, Informed Flow, Narrative/Sentiment, Cross-Market, Geopolitical, Regulatory, Technical Microstructure, Devil's Advocate, Null Hypothesis)
4. **Multi-round adversarial simulation** — Agents autonomously act over 3 rounds. Actions: PROPOSE, SUPPORT, CHALLENGE, REBUT, UPDATE_CONFIDENCE, PRESENT_EVIDENCE, CONCEDE, SYNTHESIZE. Agents *must* rebut challenges or concede. Confidence evolves from agent behavior, not self-assessment. Early termination when consensus reached (no challenges in a round). Every action logged to JSONL and streamed as individual SSE events.
5. **Clusters into competing scenarios** — Convergence/divergence patterns derived from action log (not single-pass labels). Hypotheses grouped by causal mechanism into Primary, Alternative, and Dismissed scenarios. Each scenario has: confidence score, lead + supporting agents, evidence chain, causal narrative, "what breaks this scenario", and temporal fit analysis.
6. **Persists to graph memory** — GraphRAG-style entity/relationship/fact storage for cross-attribution intelligence accumulation.

### Frontend — Staged Intelligence Dashboard

- **4-stage workflow** — Market Selection → Attribution → Scenarios → Interrogation, each with its own URL (shareable, resumable)
- **Force-directed knowledge graph** — Entities and agents appear organically as SSE streams them; convergence/divergence visualized as clustering/conflict edges
- **Real-time action feed** — Each agent action (CHALLENGE, REBUT, SUPPORT, CONCEDE) streams live during the simulation with confidence deltas
- **Scenario view** — Primary scenarios with full evidence chains; alternatives expandable; dismissed with rejection reasoning
- **Agent interview mode** — Select a specific agent and interrogate it in-character about its analysis, evidence, and reasoning
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
| Multi-round agent simulation | Agents autonomously debate — not scripted prompt-response |
| Action-level logging + streaming | Every CHALLENGE, REBUT, CONCEDE logged and visible in real-time |
| Confidence from behavior | Confidence evolves from debate actions, not self-assessment |
| Adversarial architecture | Devil's Advocate + Null Hypothesis agents challenge everything |
| Scenario-based output (not flat list) | Product sense — users need narratives, not rankings |
| Force-directed knowledge graph | Real-time data visualization, not static mockups |
| Agent interview mode | Users interrogate specific agents in-character |
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
- **Multi-round simulation** — 3 rounds of autonomous agent debate with 8 action types
- **~40-45 LLM calls/spike** at depth 2 (~$0.35/spike on Qwen) — genuine debate, not single-pass
- **Action-level SSE streaming** — each agent action streams individually to frontend
- **Real-time SSE streaming** with organic graph visualization
- **SQLite → GraphRAG** memory for cross-attribution intelligence
- **Paper trading engine** with EVT-aware Kelly sizing and risk controls
- **Dual-exchange** support (Polymarket CLOB + Kalshi regulated contracts)
- **Agent interview mode** — interrogate specific agents in-character post-attribution

---

## Status

- **Live demo**: pythia-demo.vercel.app
- **Backend**: Railway auto-deploy from GitHub
- **Stage**: Pre-revenue. Design partner conversations with quant traders.
- **Repo**: github.com/jxi5410/Pythia

---

*Last updated: March 2026. Reflects multi-scenario architecture (commit 8894332+).*
