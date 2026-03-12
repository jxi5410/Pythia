# Pythia Attribution Refactor Plan (Incremental, Repo-Aware)

## Recommended architecture

### Canonical runtime flow

1. **Detection** remains in `src/detection/detector.py` and `src/core/pipeline.py` spike loop.
2. **Attribution Orchestrator** (new module) chooses engine by mode flag and emits one standardized `AttributionResult`.
3. **Attributor persistence** remains in `src/core/attributor_engine.py` and consumes only standardized results.
4. **Forward propagation** remains in `src/core/forward_signals.py`, using attributor IDs and source spike context.
5. **Evaluation** remains in `src/core/track_record.py` (plus a new attribution-comparison table) as the only ground-truth quality layer.
6. **API surface** (`src/core/intelligence_api.py`) reads persisted attributors/signals/eval metrics; it should not know whether attribution came from PCE or RCE.

### Canonical subsystem boundaries

- **Attribution (decision logic):**
  - `src/core/causal_v2.py` (fast/default engine)
  - `src/core/rce_engine.py` (deep/experimental engine)
  - `src/core/attribution/` (new shared protocol, schemas, dispatcher)
- **Evidence retrieval (I/O):**
  - move reusable retrieval functions out of `causal_v2.py` into `src/core/evidence/news_retrieval.py`
  - RCE and PCE both call this package
- **Persistent attributors:** `src/core/attributor_engine.py`
- **Forward signal generation:** `src/core/forward_signals.py`
- **Evaluation / track record:** `src/core/track_record.py` + new `src/core/evaluation/attribution_compare.py`

This keeps existing behavior while making `causal_v2` and `rce_engine` interchangeable rather than parallel dead-ends.

---

## Canonical interfaces

## 1) Attribution engine protocol

```python
# src/core/attribution/interfaces.py
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Protocol

Confidence = Literal["HIGH", "MEDIUM", "LOW"]
EngineName = Literal["pce_v2", "rce_v1"]

@dataclass
class AttributionResult:
    spike_id: int
    engine: EngineName
    engine_version: str
    attribution: Dict[str, Any]              # most_likely_cause, confidence, chain...
    context: Dict[str, Any]                  # category, spike, correlated_spikes
    candidates_retrieved: int = 0
    candidates_filtered: int = 0
    top_candidates: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)  # full engine output for replay

class AttributionEngine(Protocol):
    name: EngineName
    version: str

    def attribute_spike(self, spike: Any, all_recent_spikes: List[Any], db: Any) -> AttributionResult:
        ...
```

## 2) Adapters for existing engines

- `PCEEngineAdapter.attribute_spike(...)` wraps `attribute_spike_v2(...)`
- `RCEEngineAdapter.attribute_spike(...)` wraps `attribute_spike_rce(...)`
- both normalize to `AttributionResult`
- both preserve original payload in `raw` for debugging

## 3) Orchestrator API

```python
# src/core/attribution/orchestrator.py
class AttributionOrchestrator:
    def __init__(self, mode: str, engines: dict[str, AttributionEngine]): ...
    def attribute_spike(self, spike, all_recent_spikes, db) -> AttributionResult: ...
```

### Required config flags

Add to `src/core/config.py`:

- `PYTHIA_ATTRIBUTION_MODE=fast|deep|shadow`
  - `fast`: run PCE only
  - `deep`: run RCE only
  - `shadow`: run PCE for production output + RCE side-by-side for evaluation (no user-facing effect)
- `PYTHIA_ENABLE_FORWARD_SIMULATION=false` (default false; remove usage and then remove module)

---

## Migration plan (causal_v2 vs RCE)

### What stays (core)

1. `causal_v2.attribute_spike_v2` as default production engine.
2. `attributor_engine` as canonical persistence and confidence-tier lifecycle.
3. `forward_signals.propagate_signals` as downstream action layer.
4. `track_record` as empirical truth layer.

### What gets wrapped

1. `attribute_spike_v2(...)` -> `PCEEngineAdapter`.
2. `attribute_spike_rce(...)` -> `RCEEngineAdapter`.
3. shared evidence functions in `causal_v2` -> `evidence/news_retrieval.py` and imported by both.
4. `rce_ontology` fallback/entity templates -> reused by PCE entity extraction path where possible.

### What gets deprecated

1. `src/core/forward_simulation.py` (first disable by flag, then delete after one release).
2. direct calls from pipeline to engine-specific functions (`attribute_spike_v2` import in `pipeline.py`).
3. stale tests importing `pythia_live.*` paths (`tests/test_causal_v2.py`) in favor of isolated adapter/orchestrator tests.

### What stays feature-flagged (experimental)

1. RCE full debate mode.
2. Tier-2 specialized agents in `rce_agents.py` (optional via `PYTHIA_RCE_ENABLE_TIER2=false` default).
3. ontology LLM-heavy extraction path (fallback templates always available).

---

## Directory structure (incremental target)

```text
src/core/
  attribution/
    interfaces.py          # AttributionEngine protocol + AttributionResult schema
    orchestrator.py        # mode dispatch and optional shadow execution
    adapters/
      pce_adapter.py       # wraps causal_v2
      rce_adapter.py       # wraps rce_engine
  evidence/
    news_retrieval.py      # shared retrieval functions extracted from causal_v2
    entity_extraction.py   # shared entity extraction hooks (optional)
  evaluation/
    attribution_compare.py # side-by-side harness + persistence
  causal_v2.py             # remains, thinner internals over time
  rce_engine.py            # remains experimental, wrapped
  attributor_engine.py
  forward_signals.py
  track_record.py
  intelligence_api.py
```

Keep old files during migration; add new modules first, then migrate call sites.

---

## Refactor tickets (first 10)

1. **Add attribution schema + protocol**
   - create `attribution/interfaces.py`
   - add `AttributionResult` dataclass and `AttributionEngine` protocol
2. **Build PCE adapter**
   - create `attribution/adapters/pce_adapter.py`
   - normalize `attribute_spike_v2` output to schema
3. **Build RCE adapter**
   - create `attribution/adapters/rce_adapter.py`
   - normalize `attribute_spike_rce` output to schema
4. **Create orchestrator + mode flag handling**
   - `attribution/orchestrator.py`
   - config wiring in `config.py`
5. **Switch pipeline call site to orchestrator**
   - replace direct `attribute_spike_v2` call in `pipeline.py`
6. **Extract shared evidence retrieval module**
   - move retrieval functions from `causal_v2.py` to `evidence/news_retrieval.py`
   - update both engines to import from shared module
7. **Introduce shadow-run persistence table**
   - DB migration for `attribution_runs` and `attribution_comparisons`
   - store per-engine output per spike
8. **Add attribution comparison harness service**
   - `evaluation/attribution_compare.py`
   - run both engines against same spikes and score downstream outcomes
9. **Gate forward_simulation behind explicit flag and default off**
   - remove any implicit runtime references
   - add deprecation warning logs
10. **Publish comparison endpoint in intelligence API**
   - add read-only endpoint for PCE vs RCE metrics (coverage, confidence calibration, forward hit-rate)

---

## Test plan (first 10 tests before major behavior changes)

1. **Schema contract test:** PCE adapter returns valid `AttributionResult` fields.
2. **Schema contract test:** RCE adapter returns valid `AttributionResult` fields.
3. **Orchestrator mode test (fast):** only PCE executes.
4. **Orchestrator mode test (deep):** only RCE executes.
5. **Orchestrator mode test (shadow):** both execute, primary output uses configured winner.
6. **Pipeline integration test:** `pipeline.run_cycle()` routes attribution via orchestrator, not direct engine import.
7. **Evidence parity test:** extracted `news_retrieval` module returns equivalent structure for representative query fixture.
8. **Attributor compatibility test:** `extract_attributor()` accepts standardized result from both adapters.
9. **Comparison harness test:** same spike set produces two rows per spike (`pce_v2`, `rce_v1`) and one comparison row.
10. **Feature-flag safety test:** with forward simulation disabled, no `forward_simulation` code path executes.

Use deterministic stubs for LLM calls in all tests to avoid flaky/network-dependent behavior.

---

## Side-by-side comparison harness (old vs new)

### Data model additions

- `attribution_runs`
  - `spike_id`, `engine`, `engine_version`, `mode`, `result_json`, `attributor_id`, `created_at`
- `attribution_outcomes`
  - `spike_id`, `engine`, `forward_signal_count`, `hit_24h`, `hit_72h`, `avg_return_bps`
- `attribution_comparisons`
  - `spike_id`, `winner_metric`, `winner_engine`, `notes`

### Execution model

1. Pull same spike set (from `spike_events`) by date range/category.
2. Run both adapters with identical spike context.
3. Persist raw standardized results.
4. Push both through same attributor + forward signal pipeline in dry-run evaluation mode.
5. Compute outcomes using existing track-record logic windows.
6. Aggregate metrics:
   - attribution coverage
   - confidence calibration
   - forward signal directional hit rate
   - cost/latency per spike

### Why this is better than a rewrite

- preserves all working code paths
- enables empirical promotion/demotion of RCE
- contains blast radius with adapters and flags

---

## What to postpone

1. **Deleting Tier-2 RCE agents** until comparison harness shows no lift.
2. **Large module moves for all unused data sources** (`china_*`, `fixed_income`, etc.) until attribution interface stabilization is complete.
3. **UI-level replay/animation of RCE debate artifacts** until backend comparison metrics exist.
4. **Major DB normalization of attributors/signals** until new interfaces settle.
5. **Prompt-level optimization of RCE rounds** until baseline fast-vs-deep metrics are collected for at least 2–4 weeks.

The immediate objective is not “best theoretical architecture”; it is **single interface + side-by-side measurable attribution quality** with minimal disruption.
