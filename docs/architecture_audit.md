# Pythia BACE Architecture Audit

Generated: 2026-03-13
Scope: 10 core modules — what they do, inputs/outputs, durable orchestration integration points.

---

## 1. `src/core/bace.py` — Entrypoint

### What it does
Unified depth-configurable attribution entrypoint. Routes spikes to the correct pipeline based on depth (1/2/3). Wraps results with standard `bace_metadata`. Also provides `attribute_spike_with_governance()` which adds circuit breaker pre-check, decision gate evaluation, and audit trail persistence.

### Inputs / Outputs
| Function | Inputs | Output |
|----------|--------|--------|
| `attribute_spike()` | `spike` (SpikeProxy-like), `all_recent_spikes`, `db`, `depth` (1\|2\|3), `llm_fast`, `llm_strong` | `Dict` — compatible with `attributor_engine.extract_attributor()` |
| `attribute_spike_with_governance()` | Same as above | `Tuple[Dict, AuditTrail]` |

### Key details
- Depth 1 → delegates to `causal_v2.attribute_spike_v2()` (legacy single-shot)
- Depth 2 → `bace_debate.attribute_spike_rce()` with `debate_rounds=0` (proposals only)
- Depth 3 → `bace_debate.attribute_spike_rce()` with `debate_rounds=2` (full adversarial)
- `_with_bace_metadata()` stamps every result with `bace_depth` and normalized metadata

### Orchestration wrap points
- **Run lifecycle**: `attribute_spike_with_governance()` already has pre/post hooks but uses wall-clock time for cost estimation (line 212: `elapsed * 0.003`). Replace with actual token-tracked costs from a run ledger.
- **Retry/resume**: If `attribute_spike()` fails mid-pipeline, the entire run is lost. Wrap with a run record that checkpoints after each stage so depth-2/3 can resume from the last successful stage.
- **Idempotency**: No deduplication — calling twice for the same spike produces two separate audit trails with different `run_id`s.

---

## 2. `src/core/bace_parallel.py` — Async Pipeline + SSE Streaming

### What it does
Async reimplementation of the serial `bace_debate` pipeline. Parallelizes four expensive operations (news evidence, domain evidence, agent proposals, counterfactual testing). Yields progress events for SSE streaming. This is the **primary execution path** used by the API server.

### Inputs / Outputs
| Function | Inputs | Output |
|----------|--------|--------|
| `attribute_spike_streaming()` | `spike`, `all_recent_spikes`, `llm_fast`, `llm_strong`, `db`, `depth` | `AsyncGenerator[Dict, None]` — yields `{"step": str, "data": dict}` events |
| `gather_evidence_parallel()` | `ontology` (CausalOntology), `spike_context` | `Dict[str, List[Dict]]` — `{"all": [news items]}` |
| `gather_domain_evidence_parallel()` | `agents`, `spike_context`, `shared_news` | `Dict[str, AgentEvidence]` |
| `run_proposals_parallel()` | `agents`, `spike_context`, `ontology`, `evidence`, `llm_call`, `agent_evidence` | `List[CausalHypothesis]` |
| `run_counterfactual_parallel()` | `agents`, `hypotheses`, `spike_context`, `llm_call` | `List[CausalHypothesis]` (mutated) |

### SSE event sequence (happy path)
```
context → heartbeat* → ontology → heartbeat* → evidence →
agents → domain_evidence → heartbeat* → proposal (×N agents) →
sim_round → sim_action* → sim_status → [repeat per round] →
sim_complete → scenarios → graph_update → result → done
```

### Key details
- Uses `ThreadPoolExecutor(max_workers=12)` for sync→async bridging (LLM calls, HTTP fetches)
- Early evidence: kicks off basic entity search *while* ontology extraction runs (lines 337-386), then merges/deduplicates
- Heartbeat events prevent Railway/Vercel SSE timeout (every 8s during long operations)
- Falls back to single-pass `bace_interaction.run_interaction_round()` if simulation fails (line 488-498)
- Generates `run_id` only at graph persistence time (line 597), not at pipeline start

### Orchestration wrap points
- **Run record**: No `run_id` exists until the very end. Generate one at pipeline start and thread it through all events.
- **Stage checkpointing**: Each `yield` is a natural checkpoint. Persist stage results (ontology, evidence, proposals, simulation actions) to the run record so partial runs can be inspected or resumed.
- **Event envelope**: Events are bare `{"step", "data"}` dicts. Wrap with canonical envelope: `{event_id, run_id, stage, event_type, sequence, payload, timestamp}`.
- **Error recovery**: If `run_proposals_parallel()` fails after ontology + evidence succeeded, the entire run restarts from scratch. With checkpointing, it could resume from cached evidence.

---

## 3. `src/core/bace_simulation.py` — Multi-Round Agent Debate

### What it does
Replaces the serial critique + counterfactual steps with a genuine multi-round adversarial simulation. Agents take autonomous actions (SUPPORT, CHALLENGE, REBUT, CONCEDE, SYNTHESIZE, etc.) over N rounds. Confidence evolves from agent behavior, not self-assessment. Actions are logged to a JSONL file and emitted as SSE events. Post-simulation, convergence/divergence patterns are derived from the action log.

### Inputs / Outputs
| Function | Inputs | Output |
|----------|--------|--------|
| `run_agent_simulation()` | `agents`, `hypotheses`, `spike_context`, `llm_call`, `num_rounds`, `_run_in_thread`, `action_log_path` | `AsyncGenerator[Dict, None]` — yields sim events |
| `_derive_convergence()` | `state`, `hypotheses`, `agents` | `Dict[str, List[str]]` — label → [hyp_id, supporter_ids] |
| `_derive_divergence()` | `state`, `hypotheses` | `List[Dict]` — unresolved challenge pairs |

### SSE events emitted
- `sim_round` — round start with active hypothesis count
- `sim_action` — each individual agent action (compact `.to_sse()` format)
- `sim_status` — per-round summary
- `sim_complete` — final state with confidence history

### Key details
- Round 0 = existing proposals logged as PROPOSE actions (lines 291-300)
- Turn order: challenged agents go first (REBUT priority), then by tier, adversarial last
- Early termination: if no CHALLENGE actions in a round after round 1, simulation converges (lines 433-443)
- Confidence changes are small and deterministic: SUPPORT +0.03, CHALLENGE -0.04, REBUT +0.02, CONCEDE → 0.0
- Action log file opened with `open()` and never closed on exception (resource leak, line 281-282)

### Orchestration wrap points
- **Action persistence**: Currently writes to local JSONL file. Move to run record (SQLite row per action) for queryability and idempotent replay.
- **Round checkpointing**: After each round, persist `SimulationState` snapshot. If interrupted mid-round, replay from last completed round.
- **Heartbeat integration**: Already yields heartbeats before each LLM call (line 345). No run_id in the heartbeat payload.
- **File handle leak**: `log_file = open(...)` at line 281 is not closed on exception. Use context manager or move to DB persistence.

---

## 4. `src/core/bace_debate.py` — Proposals, Critique, Counterfactual

### What it does
Serial (non-async) BACE debate pipeline. Used by `bace.py` at depth 2-3 for blocking execution. Contains the proposal round, critique rounds, counterfactual testing, and the full `attribute_spike_rce()` orchestration. Also provides `_parse_json_response()` used by multiple modules, and `format_evidence_for_agent()`.

### Inputs / Outputs
| Function | Inputs | Output |
|----------|--------|--------|
| `attribute_spike_rce()` | `spike`, `all_recent_spikes`, `llm_call`, `ontology_llm`, `db`, `debate_rounds` | `Dict` — full result with hypotheses, ontology, attribution |
| `run_proposal_round()` | `agents`, `spike_context`, `ontology`, `evidence`, `llm_call`, `agent_evidence` | `List[CausalHypothesis]` |
| `run_critique_round()` | `agents`, `hypotheses`, `spike_context`, `round_num`, `llm_call` | `List[CausalHypothesis]` (mutated) |
| `run_counterfactual_round()` | `agents`, `hypotheses`, `spike_context`, `llm_call` | `List[CausalHypothesis]` (mutated) |
| `_parse_json_response()` | `response: str` | `Optional[Dict]` |

### Key details
- `gather_evidence()` is the serial version of `gather_evidence_parallel()` — sequential HTTP with `time.sleep(0.5)` rate limiting (line 96)
- `_parse_json_response()` strips markdown fences, tries `json.loads`, falls back to regex `\{[\s\S]*\}` extraction
- Critique is O(agents × hypotheses) — each agent critiques every other agent's hypothesis
- Confidence is capped at 0.85 in proposals (line 199), bounded [0.0, 1.0] in critiques
- `_empty_result()` provides a safe fallback when no LLM is available

### Orchestration wrap points
- **Shared utility**: `_parse_json_response()` is imported by `bace_parallel.py` and `bace_simulation.py`. It silently returns `None` on parse failure — no structured error logging. Wrap to record parse failures in the run record.
- **Serial pipeline**: `attribute_spike_rce()` is the blocking counterpart of `attribute_spike_streaming()`. Both should share the same checkpointing logic via the run record.
- **Evidence gathering**: `gather_evidence()` has `time.sleep(0.5)` — 10+ seconds of pure sleep for 20 queries. Only used in blocking path; async path uses `gather_evidence_parallel()`.

---

## 5. `src/core/bace_agents.py` — Agent Personas + Prompts

### What it does
Defines the multi-agent architecture: 7 Tier-1 core agents, category-conditional Tier-2 agents, and 2 Tier-3 adversarial agents. Provides prompt builders for proposals, critiques, and counterfactual testing. Contains the `CausalHypothesis` and `AgentPersona` dataclasses used throughout the pipeline.

### Inputs / Outputs
| Function | Inputs | Output |
|----------|--------|--------|
| `spawn_agents()` | `category: str` | `List[AgentPersona]` |
| `build_proposal_prompt()` | `agent`, `spike_context`, `ontology_context`, `news_evidence` | `str` (LLM prompt) |
| `build_critique_prompt()` | `agent`, `spike_context`, `all_hypotheses`, `target_hypothesis` | `str` |
| `build_counterfactual_prompt()` | `agent`, `spike_context`, `hypothesis` | `str` |

### Key details
- Tier 1 (always active, 7 agents): macro-policy, market-structure, geopolitical, regulatory, narrative-sentiment, informed-flow, cross-market
- Tier 2 (conditional): crypto (2), fed_rate (2), tariffs (1), geopolitical (1)
- Tier 3 (adversarial, always active, 2): devil's-advocate, null-hypothesis
- Total ensemble: 9-12 agents depending on category
- `CausalHypothesis` dataclass is mutable — confidence, status, challenges, rebuttals are modified in-place throughout the pipeline
- Confidence calibration rules are baked into the proposal prompt (0.85 hard ceiling, band descriptions)

### Orchestration wrap points
- **Agent registry**: `spawn_agents()` is a pure function — no state. The orchestrator should record which agents were spawned (and their domains) in the run record.
- **Prompt versioning**: Prompts are inline strings. If prompts change between versions, historical runs can't be reproduced. Consider versioning prompt templates.
- **Hypothesis identity**: `CausalHypothesis.id` is `f"{agent.id}-h{j}"` — deterministic but not globally unique across runs. With a run_id prefix, hypotheses become globally addressable.

---

## 6. `src/core/bace_ontology.py` — GraphRAG Entity Extraction

### What it does
Extracts a typed entity-relationship graph from spike context via LLM. Produces entities (Person, Organization, Policy, DataRelease, Market, GeopoliticalEvent, Narrative, FinancialInstrument, TechEvent) and typed relationships (announced, triggers, preceded, etc.). The ontology drives search query generation for evidence gathering. Falls back to keyword-based templates if LLM is unavailable.

### Inputs / Outputs
| Function | Inputs | Output |
|----------|--------|--------|
| `extract_causal_ontology()` | `spike_context: Dict`, `llm_call` | `CausalOntology` |
| `CausalOntology.get_all_search_terms()` | (self) | `List[str]` — unique search terms from entities + queries |

### Key details
- LLM prompt asks for ≥12 entities and ≥15 relationships
- `_parse_ontology_response()` is a duplicate of `_parse_json_response()` in bace_debate.py (same logic, different function)
- Category templates for fallback: fed_rate, tariffs, crypto, geopolitical
- `llm_category` field lets the LLM override keyword-based category classification
- At depth ≤2, uses `llm_fast` instead of `llm_strong` for ontology (5-8s vs 27s)

### Orchestration wrap points
- **Cache opportunity**: Ontology extraction is the single most expensive step (20-40s with strong LLM). For the same market title within a time window, the ontology could be cached in the run record and reused.
- **Persist to run record**: Store the full ontology (entities, relationships, search queries) as a stage artifact. Currently only persisted indirectly via graph memory.

---

## 7. `src/core/bace_evidence_provider.py` — Per-Agent Domain Data

### What it does
Solves the critical gap where all agents received identical news articles. Wires existing data source modules (crypto_onchain, fixed_income, macro_calendar, twitter_signals, congressional, equities, orderbook_analyzer) into each agent's evidence pipeline. Each agent gets shared news + domain-specific structured data + timing context (before/after/concurrent relative to spike).

### Inputs / Outputs
| Function | Inputs | Output |
|----------|--------|--------|
| `gather_all_agent_evidence()` | `agents`, `spike_context`, `shared_news` | `Dict[str, AgentEvidence]` |
| `gather_agent_evidence()` | `agent_id`, `agent_domain`, `spike_context`, `shared_news` | `AgentEvidence` |
| `format_domain_evidence_for_prompt()` | `evidence: AgentEvidence` | `str` — formatted for LLM prompt injection |

### Key details
- `DOMAIN_FETCHERS` maps agent domain → list of fetcher functions (lines 408-423)
- `gather_all_agent_evidence()` caches fetcher results to avoid duplicate calls across agents sharing fetchers
- `_compute_timing()` computes temporal relationship: "before:2h", "after:30m", "concurrent", "unknown"
- `_build_timing_summary()` groups evidence into preceded/concurrent/followed/unknown for prompt injection
- Each fetcher wraps an existing data module (crypto_onchain, fixed_income, etc.) and returns `List[EvidenceItem]`
- Fetcher failures are caught and logged as `fetch_errors` — non-fatal

### Orchestration wrap points
- **Evidence snapshot**: Domain evidence should be persisted to the run record. Currently ephemeral — if a run is inspected later, the actual evidence used by each agent is not recoverable.
- **Fetcher health**: Track which fetchers succeeded/failed/timed-out per run. Pattern of failures indicates data source degradation.

---

## 8. `src/core/bace_scenarios.py` — Scenario Clustering

### What it does
Groups hypotheses into competing causal narratives (scenarios) with three tiers: primary (top 3 by confidence ≥0.3), alternative (confidence ≥0.15), and dismissed. Clustering uses keyword-based mechanism classification, agent convergence data from simulation, and evidence overlap.

### Inputs / Outputs
| Function | Inputs | Output |
|----------|--------|--------|
| `cluster_hypotheses_into_scenarios()` | `hypotheses`, `interaction_round`, `agents` | `List[Scenario]` |
| `scenarios_to_sse()` | `scenarios: List[Scenario]` | `Dict` — SSE-friendly summary |

### Key details
- `_classify_mechanism()` uses keyword matching against 8 mechanism categories (macro_policy, informed_flow, sentiment_narrative, cross_market, geopolitical, regulatory, technical, null)
- Tier assignment: top 3 with confidence ≥0.3 → primary; ≥0.15 → alternative; rest → dismissed
- `_generate_scenario_label()` appends a detail phrase from the top hypothesis
- Uses `interaction_round.convergence_groups` for cross-mechanism convergence detection (but doesn't actually merge groups — line 155 comment: "keep them separate")
- `what_breaks_this` populated from the first challenge against the lead agent's hypothesis

### Orchestration wrap points
- **Scenario persistence**: Scenarios are the user-facing output. Persist full `Scenario` objects to the run record.
- **No LLM-assisted clustering**: Currently pure keyword matching. Could optionally use LLM for better mechanism classification, but would need to be wrapped as a tracked step.

---

## 9. `src/core/governance.py` — Circuit Breakers, Audit Trails

### What it does
Enterprise governance layer providing: (1) `GovernanceConfig` with env-var overrides, (2) `CircuitBreaker` for cost containment, (3) `GovernanceValidator` as decision gate (AUTO_RELAY / FLAG_REVIEW / REJECT), (4) `AuditTrail` with immutable action logging, and (5) `AuditExporter` for JSON persistence. Defines autonomy levels (L0-L5) and BACE agent role mappings.

### Inputs / Outputs
| Component | Inputs | Output |
|-----------|--------|--------|
| `CircuitBreaker.check_before_run()` | `estimated_cost` | `Tuple[bool, Optional[str]]` |
| `GovernanceValidator.evaluate()` | `result: Dict`, `trail: AuditTrail` | `Tuple[str, str, Dict]` — (decision, reason, factors) |
| `create_audit_trail()` | `spike`, `depth`, `exchange` | `AuditTrail` |

### Key details
- Global singletons: `_governance_config`, `_circuit_breaker`, `_validator`, `_audit_exporter` (lines 539-542)
- `init_governance()` must be called before use; `get_governance()` raises if not initialized
- Circuit breaker tracks: per-run cost, hourly cost, emergency shutdown threshold, trip state
- Decision gate evaluates 4 factors: confidence floor, evidence sufficiency, agent consensus, adversarial signal strength
- `AuditTrail` is append-only during a run, then finalized with `finalize()`
- `AuditExporter` writes JSON files to disk (one per run)
- Backward-compat aliases: `validate_final_output()`, `validate_agent_output()`, `AgentRole`

### Orchestration wrap points
- **Single source of truth**: Governance is currently applied in two places — `bace.py:attribute_spike_with_governance()` and `server.py` (lines 170-191). Consolidate into the orchestrator so governance is always applied exactly once per run.
- **Global singletons**: Thread-unsafe. Move to dependency injection via the run context.
- **Audit trail gap**: The streaming pipeline (`bace_parallel.py`) creates its own trail in `server.py` (line 181) that's separate from the one in `bace.py`. Two different code paths = two different trail shapes.
- **Cost tracking**: Uses rough estimate (`elapsed * 0.003`), not actual token counts. The orchestrator should track real LLM costs.

---

## 10. `src/api/server.py` — FastAPI + SSE Streaming

### What it does
FastAPI application serving BACE attribution via two endpoints: `GET /api/attribute/stream` (SSE streaming, preferred) and `POST /api/attribute` (blocking, compat). Also provides health checks, LLM connectivity test, and post-attribution interrogation chat (`POST /api/interrogate`).

### Inputs / Outputs
| Endpoint | Method | Input | Output |
|----------|--------|-------|--------|
| `/api/attribute/stream` | GET | query params (market_title, timestamp, direction, magnitude, etc.) | SSE stream (`text/event-stream`) |
| `/api/attribute` | POST | `AttributeRequest` (Pydantic) | `AttributeResponse` (Pydantic) |
| `/api/interrogate` | POST | `InterrogateRequest` | SSE stream (chunked LLM response) |
| `/health` | GET | — | `{"status": "ok"}` |
| `/health/llm` | GET | — | LLM connectivity check |

### Key details
- `SpikeProxy` dataclass mimics the database SpikeEvent (lines 57-71)
- LLM loaded lazily on first request via `_get_llm()` global
- SSE events emitted as: `event: {step}\ndata: {json.dumps(data, default=str)}\n\n`
- Governance applied inline in the streaming handler (lines 170-191) — separate from `bace.py`'s governance
- `_extract_hypotheses()` normalizes raw BACE output to `HypothesisOut` Pydantic models with evidence parsing (lines 297-371)
- Interrogation supports both general Q&A and in-character agent interviews (using `agent_id` parameter)
- CORS configured for Vercel + localhost

### Orchestration wrap points
- **Run initiation**: The server should create the run record before starting `attribute_spike_streaming()`, assign the `run_id`, and pass it through the pipeline.
- **Governance dedup**: Remove inline governance from `server.py` and rely on the orchestrator applying it via the run record.
- **Response normalization**: `_extract_hypotheses()` does heavy normalization of messy LLM output. This should happen once in the pipeline, not at the API layer.

---

## Current SSE Event Format

### Backend emission (server.py:193)
```
event: {step}\ndata: {json.dumps(data, default=str)}\n\n
```

### Internal event shape (bace_parallel.py)
```python
{"step": "context",          "data": {"market_title": str, "category": str, "entities": [str]}}
{"step": "ontology",         "data": {"entity_count": int, "relationship_count": int, "search_queries": int, "entities": [str]}}
{"step": "evidence",         "data": {"count": int}}
{"step": "agents",           "data": {"count": int, "agents": [{"id", "name", "tier", "domain"}]}}
{"step": "domain_evidence",  "data": {"count": int}}
{"step": "proposal",         "data": {"agent": str, "hypotheses": [{"cause", "confidence"}]}}
{"step": "sim_round",        "data": {"round": int, "total": int, "active_hypotheses": int}}
{"step": "sim_action",       "data": {"round", "agent", "agent_name", "action", "target_agent", "target_hyp", "content", "confidence_before", "confidence_after"}}
{"step": "sim_status",       "data": {"total_rounds", "current_round", "total_actions", "active_hypotheses", ...}}
{"step": "sim_complete",     "data": {"rounds_completed", "total_actions", "confidence_history", ...}}
{"step": "scenarios",        "data": {"total", "primary": [...], "alternative": [...], "dismissed": [...]}}
{"step": "graph_update",     "data": {"entities", "relationships", "facts"}}
{"step": "heartbeat",        "data": {"status": str, "elapsed": float}}
{"step": "result",           "data": {<full attribution result>}}
```

### What's missing from the envelope
Per CLAUDE.md, the canonical envelope should be:
```
{event_id, run_id, stage, event_type, sequence, payload, timestamp}
```

Currently missing: `event_id`, `run_id`, `sequence`, `timestamp`. Without these:
- No deduplication on reconnect
- No ordering guarantee
- No way to associate events with a specific run
- No way to replay events from a checkpoint

---

## Known SSE Parsing Bug

### The bug: `json.dumps(data, default=str)` silent coercion

**Location**: `server.py:193`

```python
yield f"event: {step}\ndata: {json.dumps(data, default=str)}\n\n"
```

The `default=str` fallback silently stringifies any non-JSON-serializable object (datetime, dataclass, Enum, etc.) instead of raising a serialization error. This causes two problems:

1. **Type corruption**: The frontend receives `"2024-01-01 00:00:00"` (string) where it expects a structured timestamp, or `"DecisionGate.AUTO_RELAY"` where it expects `"AUTO_RELAY"`. The frontend parser (`bace-runner.ts`) does `JSON.parse(eventData)` which succeeds, but downstream field access produces unexpected values. This is a **silent data integrity bug** — it never throws, just produces wrong data.

2. **Potential SSE frame break**: If any object's `__str__()` representation contains a literal newline (`\n`), `json.dumps` will embed it as `\\n` inside the JSON string (which is safe). However, if a raw string with an actual newline is somehow injected into the data dict *after* `json.dumps` (not currently possible but fragile), it would split the `data:` line and break SSE framing. The frontend parser splits on `\n\n` and expects each message line to start with `event:` or `data:` — a bare continuation line would be silently dropped.

### Secondary issue: duplicate governance application

The streaming endpoint applies governance at `server.py:170-191` (creating a *new* trail with a *new* `run_id`), while the blocking path goes through `bace.py:attribute_spike_with_governance()` which creates its *own* trail. The streaming path's trail is never persisted — it's created, evaluated, and discarded. This means:
- Streaming runs have no audit trail on disk
- The `run_id` in the SSE `governance` payload doesn't match anything persisted
- The blocking path has a complete audit trail but is rarely used

---

## Integration Map

```
                    ┌─────────────────────────────────────────┐
                    │           server.py (API)                │
                    │  GET /api/attribute/stream                │
                    │  POST /api/attribute                     │
                    │  POST /api/interrogate                   │
                    └────────┬───────────────┬─────────────────┘
                             │ streaming     │ blocking
                             ▼               ▼
                    ┌────────────────┐  ┌─────────────┐
                    │ bace_parallel  │  │   bace.py   │
                    │ (async pipeline)│  │ (entrypoint)│
                    └───┬──┬──┬──┬──┘  └──────┬──────┘
                        │  │  │  │             │
            ┌───────────┘  │  │  └──────┐      │
            ▼              ▼  ▼         ▼      ▼
    ┌──────────────┐ ┌─────────┐ ┌──────────┐ ┌─────────────┐
    │bace_ontology │ │  bace_  │ │  bace_   │ │ bace_debate │
    │(GraphRAG)    │ │ agents  │ │simulation│ │ (serial)    │
    └──────────────┘ │(personas│ │(N-round  │ └──────┬──────┘
                     │+prompts)│ │ debate)  │        │
                     └─────────┘ └──────────┘   uses all of:
                                                ontology, agents,
            ┌───────────────────────────┐       evidence, proposals,
            │  bace_evidence_provider   │       critique, counterfactual
            │  (per-agent domain data)  │
            └───────────────────────────┘
                         │
            ┌────────────┼────────────────┐
            ▼            ▼                ▼
    crypto_onchain  fixed_income   macro_calendar ...
    twitter_signals congressional  equities
    orderbook_analyzer

            ┌───────────────────────────┐
            │     bace_scenarios        │
            │  (hypothesis clustering)  │
            └───────────────────────────┘

            ┌───────────────────────────┐
            │       governance          │
            │  (circuit breaker, audit, │
            │   decision gate)          │
            └───────────────────────────┘
```

### Data flow
1. `server.py` creates `SpikeProxy` from request params
2. `bace_parallel.attribute_spike_streaming()` runs the async pipeline
3. `bace_ontology` extracts entity graph (LLM call)
4. `bace_parallel.gather_evidence_parallel()` + `gather_domain_evidence_parallel()` fetch news + domain data
5. `bace_agents.spawn_agents()` creates the agent ensemble
6. `bace_parallel.run_proposals_parallel()` generates hypotheses (parallel LLM calls)
7. `bace_simulation.run_agent_simulation()` runs N-round debate (sequential rounds, parallel agents within round)
8. `bace_scenarios.cluster_hypotheses_into_scenarios()` groups surviving hypotheses
9. `governance` evaluates the result (decision gate)
10. Final result yielded as SSE `result` event

### Where the orchestrator wraps
The durable orchestrator sits between `server.py` and `bace_parallel.py`:
- Creates run record with `run_id` before pipeline starts
- Passes `run_id` to all downstream modules for event tagging
- Checkpoints after each stage (ontology, evidence, proposals, simulation, scenarios)
- Applies governance exactly once via the run record
- Persists audit trail to SQLite (not just JSON files)
- Enables resume-from-checkpoint on failure
