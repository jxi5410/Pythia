# Codex Implementation Plan — Slice 2-7

## Context

Slice 1 (complete): Attribution orchestrator + adapters + pipeline wiring.
- `src/core/attribution/` — interfaces, orchestrator, PCE adapter, RCE adapter
- `pipeline.py` updated to use orchestrator
- 3 tests passing
- `PYTHIA_ATTRIBUTION_MODE=fast|deep|shadow` config flag

Slice 1 left 4 gaps that create bypass paths around the orchestrator.
This plan addresses them in priority order.

---

## Slice 2: Wire remaining callers through orchestrator

**Problem:** `main.py` and `spike_archive.py` still call `causal_v2` directly,
bypassing the orchestrator. This means the live polling loop and the backfill
script never use RCE, even in shadow mode.

### 2a: Update `src/core/main.py`

**Current state (line 29, 631):**
```python
from .causal_v2 import attribute_spike_with_governance
# ...
result, audit_trail = attribute_spike_with_governance(spike)
```

`attribute_spike_with_governance` is a governance-wrapped version of
`attribute_spike_v2` that adds circuit breakers, validation checkpoints,
and audit trails. The orchestrator needs to support this.

**Implementation:**
1. Create `src/core/attribution/adapters/pce_governance_adapter.py`
   - Wraps `attribute_spike_with_governance` instead of `attribute_spike_v2`
   - Returns `AttributionResult` with `diagnostics.audit_trail` and `diagnostics.decision`
   - Preserves the `AUTO_RELAY / FLAG_REVIEW / REJECT` decision gate
2. In `main.py`, replace:
   ```python
   from .causal_v2 import attribute_spike_with_governance
   ```
   with:
   ```python
   from .attribution.orchestrator import AttributionOrchestrator
   from .attribution.adapters import PCEGovernanceAdapter, RCEEngineAdapter
   ```
3. Initialize orchestrator in `__init__` of the `PythiaLive` class (around line 560)
4. Replace the `attribute_spike_with_governance(spike)` call at line 631 with:
   ```python
   attribution_result = self._orchestrator.attribute_spike(spike, recent_spikes, self.db)
   result = attribution_result.to_legacy_result()
   decision = attribution_result.diagnostics.get("decision", "AUTO_RELAY")
   audit_trail = attribution_result.diagnostics.get("audit_trail")
   ```
5. Keep the existing `AUTO_RELAY / FLAG_REVIEW / REJECT` branching unchanged —
   it reads from `result` which now comes from the orchestrator.

**Note:** The governance wrapper (`attribute_spike_with_governance`) adds
circuit breakers and validation checkpoints that `attribute_spike_v2` doesn't have.
The PCEGovernanceAdapter should delegate to the governance version, not the raw v2.
For RCE in deep/shadow mode, governance wrapping is not yet implemented — log a
warning and skip governance gates for RCE results.

### 2b: Update `src/core/spike_archive.py`

**Current state (line 259):**
```python
from .causal_v2 import attribute_spike_v2
result = attribute_spike_v2(spike, ...)
```

**Implementation:**
1. `attribute_spike_v2_wrapper` (line 251) should accept an optional
   `orchestrator: AttributionOrchestrator` parameter
2. If orchestrator is provided, use it. Otherwise fall back to direct call (backward compat).
3. Update callers of `attribute_spike_v2_wrapper` (check `backfill_spikes.py`)
   to pass the orchestrator when available.

**Simpler alternative:** Since `spike_archive.py`'s wrapper is only called from
`backfill_spikes.py`, and backfill is a batch script not a live path, it's
acceptable to leave this as-is for now and add a `# TODO: route through orchestrator`
comment. Prioritize `main.py` which is the live path.

### 2c: Test

Add `tests/test_main_orchestrator_wiring.py`:
- Mock the orchestrator
- Verify `main.py` calls `orchestrator.attribute_spike()`, not `attribute_spike_with_governance` directly
- Verify decision gate logic still works with orchestrator output

**Files changed:** `src/core/main.py`, `src/core/attribution/adapters/pce_governance_adapter.py` (new),
`src/core/attribution/adapters/__init__.py`, `tests/test_main_orchestrator_wiring.py` (new)

**Risk:** Medium. `main.py` is the live polling loop. Test thoroughly.
Keep `attribute_spike_with_governance` import available as emergency fallback.

---

## Slice 3: Add RCE adapter test

**Problem:** `test_pce_adapter.py` exists but `test_rce_adapter.py` does not.
Asymmetric test coverage.

**Implementation:**
Create `tests/test_rce_adapter.py`:
```python
def test_rce_adapter_normalizes_result(monkeypatch):
    def fake_attribute_spike_rce(**kwargs):
        return {
            "spike_id": 42,
            "context": {"category": "tariffs", "spike": {"market_id": "abc"}},
            "attribution": {"most_likely_cause": "Tariff EO", "confidence": "HIGH"},
            "candidates_retrieved": 14,
            "candidates_filtered": 5,
            "top_candidates": [{"headline": "Trump EO"}],
            "debate_rounds": 3,
            "agents_spawned": 7,
            "elapsed_seconds": 12.5,
            "total_hypotheses": 9,
        }

    monkeypatch.setattr(
        "core.attribution.adapters.rce_adapter.attribute_spike_rce",
        fake_attribute_spike_rce
    )

    adapter = RCEEngineAdapter()
    result = adapter.attribute_spike(spike=MockSpike(), all_recent_spikes=[], db=None)

    assert result.engine == "rce_v1"
    assert result.spike_id == 42
    assert result.attribution["most_likely_cause"] == "Tariff EO"
    assert result.diagnostics["debate_rounds"] == 3
    assert result.diagnostics["agents_spawned"] == 7
```

**Files changed:** `tests/test_rce_adapter.py` (new)

**Risk:** Low. Pure unit test.

---

## Slice 4: Extract `news_retrieval.py` from `causal_v2.py`

**Problem:** `rce_engine.py` lazily imports news retrieval functions from
`causal_v2.py` (lines 63-68). This couples RCE to PCE's monolith and blocks
future simplification of `causal_v2`.

**Implementation:**
1. Create `src/core/evidence/__init__.py` and `src/core/evidence/news_retrieval.py`
2. Move these functions from `causal_v2.py` to `news_retrieval.py`:
   - `newsapi_search()`
   - `google_news_rss()`
   - `duckduckgo_search()`
   - `reddit_search()`
   - `filter_by_temporal_window()`
   - `_parse_published_date()`
   - `SUBREDDIT_MAP` constant
   - `retrieve_candidate_news()`
3. In `causal_v2.py`, replace the moved functions with imports:
   ```python
   from .evidence.news_retrieval import (
       newsapi_search, google_news_rss, duckduckgo_search,
       reddit_search, filter_by_temporal_window, retrieve_candidate_news,
   )
   ```
4. In `rce_engine.py`, update the lazy import (line 63) to:
   ```python
   from .evidence.news_retrieval import (
       retrieve_candidate_news, newsapi_search, google_news_rss,
       duckduckgo_search, reddit_search, filter_by_temporal_window,
   )
   ```
5. Verify no other files import these functions directly from `causal_v2`.

**Test:**
Add `tests/test_news_retrieval.py`:
- Test that `newsapi_search`, `google_news_rss`, etc. are importable from new path
- Test `filter_by_temporal_window` with a fixture of articles and a time range
- Test `retrieve_candidate_news` with a mock context (stub HTTP calls)

**Files changed:** `src/core/evidence/__init__.py` (new), `src/core/evidence/news_retrieval.py` (new),
`src/core/causal_v2.py` (imports updated), `src/core/rce_engine.py` (imports updated),
`tests/test_news_retrieval.py` (new)

**Risk:** Medium. Many functions to move. Run all existing tests after move to catch
import breakage. The key safety check: `causal_v2.py` re-exports everything it used
to define, so callers outside the module don't break.

---

## Slice 5: Gate `forward_simulation.py` behind flag, default off

**Problem:** `forward_simulation.py` is 481 lines of dead code. It validates
attributors against LLM agent opinions rather than ground truth. Per architecture
audit, it should be deprecated. But deletion without a flag is risky.

**Implementation:**
1. Add to `src/core/config.py`:
   ```python
   ENABLE_FORWARD_SIMULATION = os.getenv("PYTHIA_ENABLE_FORWARD_SIMULATION", "false").lower() == "true"
   ```
2. In `forward_simulation.py`, add at top of both public functions:
   ```python
   def run_forward_simulation(...):
       if not Config().ENABLE_FORWARD_SIMULATION:
           logger.warning("Forward simulation disabled (PYTHIA_ENABLE_FORWARD_SIMULATION=false)")
           return ForwardSimulationResult(
               seed_cause=attributed_cause, seed_confidence=cause_confidence,
               initial_price=0, final_price=0, actual_spike_magnitude=0,
               simulated_magnitude=0, magnitude_match=0, direction_match=False,
               validation_verdict="disabled", reasoning="Forward simulation disabled by config",
           )
       # ... existing code
   ```
3. Same pattern for `validate_rce_attributors()`.
4. Add deprecation docstring: `"DEPRECATED: Will be removed. Use track_record.py for attribution validation."`

**Test:**
Add `tests/test_forward_simulation_gate.py`:
- With default config, `run_forward_simulation` returns "disabled" verdict without LLM calls
- With `PYTHIA_ENABLE_FORWARD_SIMULATION=true`, it would proceed (mock the LLM)

**Files changed:** `src/core/config.py`, `src/core/forward_simulation.py`,
`tests/test_forward_simulation_gate.py` (new)

**Risk:** Low. No one calls this module.

---

## Slice 6: Shadow-run persistence table

**Problem:** Shadow mode runs both engines but doesn't save results. Comparison
data disappears when the process ends. Without persistence, you can't measure
whether RCE is actually better than PCE.

**Implementation:**
1. Add to `src/core/database.py` a new table:
   ```sql
   CREATE TABLE IF NOT EXISTS attribution_runs (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       spike_id INTEGER NOT NULL,
       engine TEXT NOT NULL,          -- 'pce_v2' or 'rce_v1'
       engine_version TEXT,
       mode TEXT,                     -- 'fast', 'deep', 'shadow'
       most_likely_cause TEXT,
       confidence TEXT,               -- 'HIGH', 'MEDIUM', 'LOW'
       candidates_retrieved INTEGER DEFAULT 0,
       candidates_filtered INTEGER DEFAULT 0,
       diagnostics_json TEXT,         -- JSON blob
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       FOREIGN KEY (spike_id) REFERENCES spike_events(id)
   );
   ```
2. In `orchestrator.py`, after running an engine, persist the result:
   ```python
   def _persist_run(self, result: AttributionResult, mode: str, db):
       if db is None:
           return
       db.execute("""
           INSERT INTO attribution_runs (spike_id, engine, engine_version, mode,
               most_likely_cause, confidence, candidates_retrieved, candidates_filtered,
               diagnostics_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       """, (result.spike_id, result.engine, result.engine_version, mode,
             result.attribution.get("most_likely_cause", ""),
             result.attribution.get("confidence", ""),
             result.candidates_retrieved, result.candidates_filtered,
             json.dumps(result.diagnostics)))
   ```
3. Call `_persist_run` for both engines in shadow mode, and for the active engine
   in fast/deep mode.
4. The orchestrator needs a `db` reference. Add it to `__init__` or pass it
   through `attribute_spike()`. The cleanest option: pass `db` through since
   it's already a parameter of `attribute_spike()`.

**Test:**
- Run orchestrator in shadow mode with an in-memory SQLite DB
- Verify 2 rows inserted into `attribution_runs` (one per engine)
- Verify `engine` column values are `pce_v2` and `rce_v1`

**Files changed:** `src/core/database.py`, `src/core/attribution/orchestrator.py`,
`tests/test_shadow_persistence.py` (new)

**Risk:** Low-medium. DB migration is additive (CREATE TABLE IF NOT EXISTS).
Orchestrator change is small.

---

## Slice 7: Add `deep` mode orchestrator test

**Problem:** Codex's tests cover `fast` and `shadow` but not `deep` mode.

**Implementation:**
Add to `tests/test_attribution_orchestrator.py`:
```python
def test_orchestrator_deep_mode_runs_rce_only():
    pce = DummyEngine(name="pce_v2")
    rce = DummyEngine(name="rce_v1")
    o = AttributionOrchestrator(mode="deep", engines={"pce_v2": pce, "rce_v1": rce})

    result = o.attribute_spike(spike=object(), all_recent_spikes=[], db=None)

    assert result.engine == "rce_v1"
    assert rce.calls == 1
    assert pce.calls == 0


def test_orchestrator_unknown_mode_defaults_to_fast():
    pce = DummyEngine(name="pce_v2")
    rce = DummyEngine(name="rce_v1")
    o = AttributionOrchestrator(mode="garbage", engines={"pce_v2": pce, "rce_v1": rce})

    result = o.attribute_spike(spike=object(), all_recent_spikes=[], db=None)

    assert result.engine == "pce_v2"


def test_orchestrator_missing_engine_raises():
    pce = DummyEngine(name="pce_v2")
    o = AttributionOrchestrator(mode="deep", engines={"pce_v2": pce})

    import pytest
    with pytest.raises(RuntimeError, match="not configured"):
        o.attribute_spike(spike=object(), all_recent_spikes=[], db=None)
```

**Files changed:** `tests/test_attribution_orchestrator.py` (append)

**Risk:** None. Pure unit tests.

---

## Execution order

| Priority | Slice | Risk | Files | Why first |
|----------|-------|------|-------|-----------|
| **P0** | 2a: Wire `main.py` | Medium | 4 | Live polling loop bypasses orchestrator — biggest gap |
| **P0** | 7: Deep mode test | None | 1 | 5 minutes, closes test gap |
| **P1** | 3: RCE adapter test | Low | 1 | Closes test asymmetry |
| **P1** | 4: Extract `news_retrieval.py` | Medium | 5 | Decouples RCE from causal_v2 monolith |
| **P2** | 5: Gate `forward_simulation` | Low | 3 | Deprecation marker |
| **P2** | 6: Shadow persistence | Low-Med | 3 | Enables A/B measurement |
| **P3** | 2b: Wire `spike_archive.py` | Low | 2 | Batch path, not urgent |

---

## What NOT to do in these slices

- Do not optimize RCE prompts or agent count — no baseline metrics yet
- Do not build the comparison endpoint in intelligence_api — need persistence first (slice 6)
- Do not move data source modules (`china_*`, `fixed_income`, etc.) — interface not stable yet
- Do not delete `forward_simulation.py` — gate it first, delete in a future slice
- Do not touch the frontend — backend stability first
