# Pythia — Claude Code Context

## What this is
Prediction market intelligence engine. Detects probability spikes across Polymarket/Kalshi, explains them using BACE (Backward Attribution Causal Engine) — a multi-agent causal reasoning system.

## Stack
- Backend: Python/FastAPI in `src/`, deployed on Railway
- Frontend: TypeScript/Next.js in `frontend/`, deployed on Vercel
- LLM: Qwen via DashScope (default), configurable
- Database: SQLite
- Repo: github.com/jxi5410/Pythia

## Key modules
- `src/core/bace.py` — BACE entrypoint
- `src/core/bace_parallel.py` — async pipeline + SSE streaming
- `src/core/bace_simulation.py` — multi-round agent debate
- `src/core/bace_debate.py` — proposals, critique, counterfactual
- `src/core/bace_agents.py` — agent personas + prompts
- `src/core/bace_ontology.py` — GraphRAG entity extraction
- `src/core/bace_evidence_provider.py` — per-agent domain data
- `src/core/bace_scenarios.py` — scenario clustering
- `src/core/governance.py` — circuit breakers, audit trails
- `src/api/server.py` — FastAPI + SSE streaming

## Engineering rules
- WRAP existing BACE modules with durable orchestration — do NOT rewrite them
- Pydantic v2 for all models, SQLite for persistence
- Keep modules small and composable
- Prefer explicit typed models over ad hoc dicts
- Timestamp everything with ISO8601
- All changes must preserve existing functionality
- Idempotent writes: skip duplicates on retry, don't append blindly
- SSE events use canonical envelope: event_id, run_id, stage, event_type, sequence, payload, timestamp

## What we're building (current sprint)
Upgrading from prototype to production-grade run-centric system. See docs/architecture_audit.md (once created) for integration map.
