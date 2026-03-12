# BACE Merge Plan — Unified Backward Attribution Causal Engine

## Context

PCE (`causal_v2.py`, 1297 lines) and RCE (`rce_engine.py` + `rce_agents.py` +
`rce_ontology.py` + `rce_evidence_provider.py`, ~1970 lines) are two separate
attribution engines that share context building, news retrieval, and output format.

The orchestrator layer (`attribution/`, ~190 lines) switches between them.

Total: ~3,940 lines across 12 files doing one job.

Target: one engine (`bace.py`) with a depth parameter, ~1,800-2,200 lines
across 6-7 files. The orchestrator and adapter layers are eliminated.

## Status (updated 2026-03-12)

**PR #19 (Codex slice 2-7 plan) has been superseded by this BACE plan.**
Close PR #19 without merging. The useful code from that PR has been
cherry-picked onto main:

- `src/core/evidence/news_retrieval.py` — extracted news retrieval (222 lines) ✅
- `src/core/evidence/__init__.py` — package init ✅
- `src/core/evaluation/attribution_compare.py` — shadow persistence tables (102 lines) ✅
- `src/core/evaluation/__init__.py` — package init ✅
- `tests/test_news_retrieval.py` — news retrieval tests ✅
- `tests/test_attribution_compare_persistence.py` — persistence tests ✅
- `src/core/rce_engine.py` — updated imports to use evidence.news_retrieval ✅

This means BACE Slice 1 (extract news_retrieval) is **partially complete**.
Remaining Slice 1 work: extract `market_classifier.py`, `spike_context.py`,
`feedback.py` from `causal_v2.py`, and add re-export stubs.

---

## Target Architecture

```
src/core/
  bace.py                    # NEW — unified engine, depth=1|2|3
  bace_agents.py             # RENAMED from rce_agents.py (no changes needed)
  bace_ontology.py           # RENAMED from rce_ontology.py (no changes needed)
  bace_evidence_provider.py  # RENAMED from rce_evidence_provider.py (no changes needed)
  evidence/
    news_retrieval.py        # EXTRACTED from causal_v2.py
  market_classifier.py       # EXTRACTED from causal_v2.py (classify_market + entity extraction)
  spike_context.py           # EXTRACTED from causal_v2.py (build_spike_context, find_concurrent)
  feedback.py                # EXTRACTED from causal_v2.py (log_feedback, get_feedback_summary)
```

### Files removed after migration:
```
  causal_v2.py               # DEPRECATED — replaced by bace.py + extracted modules
  rce_engine.py              # DEPRECATED — merged into bace.py
  rce_agents.py              # RENAMED to bace_agents.py
  rce_ontology.py            # RENAMED to bace_ontology.py
  rce_evidence_provider.py   # RENAMED to bace_evidence_provider.py
  forward_simulation.py      # DELETED (already gated off)
  attribution/               # DELETED (orchestrator no longer needed)
```

---

## BACE Depth Levels

```python
# src/core/bace.py

class BACEDepth:
    FAST = 1      # ~3 LLM calls, ~$0.03/spike
    STANDARD = 2  # ~15 LLM calls, ~$0.15/spike
    DEEP = 3      # ~95 LLM calls, ~$0.47/spike
```

### Depth 1 (FAST) — Today's PCE

```
spike_context()               # free — classify + entities + concurrent spikes
→ statistical_validation()    # free — CausalImpact / z-score (exits early if not significant)
→ news_retrieval()            # free — 4 sources, temporal filter
→ filter_candidates()         # 1 LLM call (qwen-plus) — score all candidates
→ reason_about_cause()        # 1 LLM call (qwen-max) — single-shot attribution
→ dag_refutation()            # free — DoWhy formal graph
→ heterogeneous_effects()     # free — EconML magnitude prediction
→ store_attributor()          # free — persist to DB
```

Entity extraction: `extract_entities_llm()` — 1 LLM call, 3-5 keywords.
Total: 3 LLM calls. No agents, no debate.

### Depth 2 (STANDARD) — New sweet spot

```
spike_context()               # free
→ statistical_validation()    # free (exits early if not significant)
→ ontology_extraction()       # 1 LLM call (qwen-max) — 15-20 typed entities
→ news_retrieval()            # free — uses ontology search terms (broader than depth 1)
→ domain_evidence()           # free — per-agent data from data source modules
→ agent_proposals()           # 7-9 LLM calls (qwen-plus) — each agent proposes 1-3 hypotheses
→ rank_and_select()           # 1 LLM call (qwen-max) — pick best hypothesis from proposals
→ dag_refutation()            # free
→ heterogeneous_effects()     # free
→ store_attributor()          # free
```

Entity extraction: `extract_causal_ontology()` — 1 LLM call, 15-20 typed entities.
Total: ~12 LLM calls. Multi-agent diversity, domain data, no debate rounds.
Key insight: you get 80% of RCE's quality for 15% of its cost.

### Depth 3 (DEEP) — Today's RCE

```
spike_context()               # free
→ statistical_validation()    # free (exits early if not significant)
→ ontology_extraction()       # 1 LLM call (qwen-max)
→ news_retrieval()            # free
→ domain_evidence()           # free
→ agent_proposals()           # 7-9 LLM calls (qwen-plus)
→ adversarial_debate()        # ~60 LLM calls (qwen-plus) — 2 rounds, all agents critique
→ counterfactual_test()       # ~10 LLM calls (qwen-plus) — 5 agents vote per surviving hyp
→ dag_refutation()            # free
→ heterogeneous_effects()     # free
→ store_attributor()          # free
```

Total: ~85 LLM calls. Full adversarial debate + counterfactual testing.

---

## Migration Slices (ordered)

### Slice 1: Extract utility modules from causal_v2.py

**Goal:** Break `causal_v2.py` into reusable pieces that both the old code
and the new BACE can import. This is prerequisite to everything else.

**Create `src/core/evidence/news_retrieval.py`:**
Move these functions from `causal_v2.py`:
- `newsapi_search()`
- `google_news_rss()`
- `brave_search()`
- `duckduckgo_search()`
- `reddit_search()`
- `filter_by_temporal_window()`
- `_parse_published_date()`
- `retrieve_candidate_news()`
- `SUBREDDIT_MAP` constant (if exists)

**Create `src/core/market_classifier.py`:**
Move from `causal_v2.py`:
- `classify_market()`
- `extract_entities_simple()`
- `extract_entities_llm()`
- All category keyword dicts used by `classify_market()`

**Create `src/core/spike_context.py`:**
Move from `causal_v2.py`:
- `build_spike_context()`
- `find_concurrent_spikes()`

These will import from `market_classifier` and `evidence.news_retrieval`.

**Create `src/core/feedback.py`:**
Move from `causal_v2.py`:
- `log_feedback()`
- `load_feedback_corrections()`
- `get_feedback_summary()`
- `FEEDBACK_FILE` constant

**Update `causal_v2.py`:**
Replace moved functions with re-exports:
```python
# Backward compatibility — callers can still import from causal_v2
from .evidence.news_retrieval import (
    newsapi_search, google_news_rss, duckduckgo_search,
    reddit_search, filter_by_temporal_window, retrieve_candidate_news,
)
from .market_classifier import classify_market, extract_entities_simple, extract_entities_llm
from .spike_context import build_spike_context, find_concurrent_spikes
from .feedback import log_feedback, load_feedback_corrections, get_feedback_summary
```

This keeps all existing callers working while the functions live in new homes.

**Update `rce_engine.py`:**
Change lazy imports (lines 63-68, 393-409) to import from new modules:
```python
from .evidence.news_retrieval import (
    retrieve_candidate_news, newsapi_search, ...
)
from .spike_context import build_spike_context
```

**Tests:**
- Import each new module and verify all functions are accessible
- Run existing `test_causal_v2.py` to confirm backward compat
- Run `test_attribution_orchestrator.py` and `test_pce_adapter.py`

**Files created:** 4 new modules + `evidence/__init__.py`
**Files modified:** `causal_v2.py` (re-exports), `rce_engine.py` (imports)
**Risk:** Medium. Many functions moving. Run full test suite after.

---

### Slice 2: Rename RCE modules to BACE

**Goal:** Rename without changing any code. Pure file renames + import updates.

```
rce_agents.py           → bace_agents.py
rce_ontology.py         → bace_ontology.py
rce_evidence_provider.py → bace_evidence_provider.py
rce_engine.py           → (keep temporarily, will be replaced by bace.py in slice 3)
```

**Update all internal imports:**
- `rce_engine.py`: `from .rce_ontology import` → `from .bace_ontology import`
- `rce_engine.py`: `from .rce_agents import` → `from .bace_agents import`
- `rce_engine.py`: `from .rce_evidence_provider import` → `from .bace_evidence_provider import`
- `attribution/adapters/rce_adapter.py`: `from ...rce_engine import` → stays (rce_engine still exists)

**Create compatibility re-exports** in case anything else imports old names:
```python
# src/core/rce_agents.py (now just re-exports)
from .bace_agents import *  # noqa
```

Same for `rce_ontology.py` and `rce_evidence_provider.py`.

**Tests:** All existing tests must still pass unchanged.

**Files created:** 3 new files (bace_agents, bace_ontology, bace_evidence_provider)
**Files modified:** rce_engine.py (imports), 3 old files become re-export stubs
**Risk:** Low. Pure renames.

---

### Slice 3: Build `bace.py` — the unified engine

**Goal:** One function `attribute_spike(spike, ..., depth=2)` that replaces both
`attribute_spike_v2()` and `attribute_spike_rce()`.

**Create `src/core/bace.py`:**

```python
"""
BACE — Backward Attribution Causal Engine.

Unified causal attribution for prediction market spikes.
Replaces causal_v2 (PCE) and rce_engine (RCE) with a single
depth-configurable pipeline.

Usage:
    from .bace import attribute_spike, BACEDepth

    result = attribute_spike(spike, db=db, depth=BACEDepth.STANDARD)
"""

from enum import IntEnum

class BACEDepth(IntEnum):
    FAST = 1      # ~3 LLM calls — single-shot attribution
    STANDARD = 2  # ~15 LLM calls — multi-agent proposals, no debate
    DEEP = 3      # ~95 LLM calls — full adversarial debate


def attribute_spike(
    spike,
    all_recent_spikes=None,
    db=None,
    depth: int = BACEDepth.STANDARD,
    llm_fast=None,    # qwen-plus equivalent
    llm_strong=None,  # qwen-max equivalent
) -> Dict:
    """
    Unified attribution pipeline.

    Returns dict compatible with attributor_engine.extract_attributor().
    """
```

**Implementation structure:**

```python
def attribute_spike(...):
    # --- Shared across all depths ---
    context = build_spike_context(spike, all_recent_spikes, entity_llm=llm_fast)

    # Statistical validation (free — gates LLM spend)
    stat = _run_statistical_validation(db, spike, context)
    if stat and not stat.get("is_significant", True):
        return _insignificant_result(spike, context, stat)

    # --- Depth 1: simple entities, single-shot reasoning ---
    if depth == BACEDepth.FAST:
        return _run_fast(spike, context, db, llm_fast, llm_strong)

    # --- Depth 2+: rich ontology + domain evidence ---
    ontology = extract_causal_ontology(context, llm_call=llm_strong)
    evidence = gather_evidence(ontology, context)
    agents = spawn_agents(context.get("category", "general"))
    agent_evidence = gather_all_agent_evidence(agents, context, evidence.get("all", []))

    if depth == BACEDepth.STANDARD:
        return _run_standard(spike, context, ontology, evidence, agents,
                            agent_evidence, db, llm_fast, llm_strong)

    # --- Depth 3: full adversarial debate ---
    return _run_deep(spike, context, ontology, evidence, agents,
                     agent_evidence, db, llm_fast, llm_strong)
```

**`_run_fast()`** — port from `causal_v2.attribute_spike_v2()`:
- `retrieve_candidate_news()` with simple entities
- `filter_candidates()` — 1 LLM call
- `reason_about_cause()` — 1 LLM call
- `_run_dag_refutation()`, `_run_heterogeneous_effects()`
- Return standard result dict

**`_run_standard()`** — NEW (doesn't exist today):
- Uses ontology-derived search terms (broader coverage)
- Gathers per-agent domain evidence
- Runs proposal round only (no debate)
- 1 LLM call (strong) to select and synthesize best hypothesis from proposals
- `_run_dag_refutation()`, `_run_heterogeneous_effects()`
- Return standard result dict

**`_run_deep()`** — port from `rce_engine.attribute_spike_rce()`:
- Everything in standard, plus:
- `run_critique_round()` × 2 rounds
- `run_counterfactual_round()`
- Return standard result dict

**Statistical validation, DAG refutation, heterogeneous effects** are shared
helper functions called by all three depth levels. Port from causal_v2.

**Governance wrapping:** Keep `attribute_spike_with_governance()` as a wrapper
around `attribute_spike()`, not inside it. This is used by `main.py` only.
Implement as:

```python
def attribute_spike_with_governance(spike, **kwargs):
    """Governance-wrapped BACE. Used by main.py live polling loop."""
    from .governance import AuditTrail, validate_attribution, ...
    trail = AuditTrail(...)
    result = attribute_spike(spike, **kwargs)
    decision = _evaluate_governance(result, trail)
    result["decision"] = decision
    return result, trail
```

**Tests:**
- `test_bace_fast.py`: Mock LLM, verify depth=1 makes exactly 3 LLM calls
- `test_bace_standard.py`: Mock LLM, verify depth=2 makes ~12 calls, agents are spawned
- `test_bace_deep.py`: Mock LLM, verify depth=3 includes debate rounds
- `test_bace_statistical_gate.py`: Spike fails validation → 0 LLM calls
- `test_bace_output_compat.py`: Output dict is accepted by `attributor_engine.extract_attributor()`

**Files created:** `src/core/bace.py`, 5 test files
**Files modified:** None yet (old code still works in parallel)
**Risk:** Medium. Core logic, but old code is untouched.

---

### Slice 4: Update config and callers to use BACE

**Update `src/core/config.py`:**
```python
# Replace ATTRIBUTION_MODE=fast|deep|shadow with:
BACE_DEPTH = int(os.getenv("PYTHIA_BACE_DEPTH", "2"))  # 1=fast, 2=standard, 3=deep
```

**Update `src/core/pipeline.py`:**
Replace the orchestrator with direct BACE call:
```python
# BEFORE:
from .attribution.orchestrator import AttributionOrchestrator
from .attribution.adapters import PCEEngineAdapter, RCEEngineAdapter
# ...
self._attribution_orchestrator = AttributionOrchestrator(mode=..., engines={...})
# ...
attribution_result = self._attribution_orchestrator.attribute_spike(spike, ...)

# AFTER:
from .bace import attribute_spike, BACEDepth
# ...
result = attribute_spike(
    spike=spike,
    all_recent_spikes=self._recent_spike_proxies,
    db=self.db,
    depth=self.config.BACE_DEPTH,
    llm_fast=llm_call,
    llm_strong=llm_call,
)
```

**Update `src/core/main.py`:**
```python
# BEFORE:
from .causal_v2 import attribute_spike_with_governance

# AFTER:
from .bace import attribute_spike_with_governance
```

The governance wrapper signature stays identical, so the decision gate
logic in `main.py` doesn't need to change.

**Update `src/core/spike_archive.py`:**
```python
# BEFORE:
from .causal_v2 import attribute_spike_v2
result = attribute_spike_v2(spike, ...)

# AFTER:
from .bace import attribute_spike, BACEDepth
result = attribute_spike(spike, ..., depth=BACEDepth.FAST)
```

**Update `src/core/intelligence_api.py`:**
```python
# BEFORE:
from .causal_v2 import log_feedback

# AFTER:
from .feedback import log_feedback
```

**Update `src/core/backtest.py`:**
```python
# BEFORE:
from .causal_v2 import classify_market

# AFTER:
from .market_classifier import classify_market
```

**Tests:** All existing tests must pass. Run full suite.

**Files modified:** `config.py`, `pipeline.py`, `main.py`, `spike_archive.py`,
`intelligence_api.py`, `backtest.py`
**Risk:** High. Multiple call sites. Test thoroughly.

---

### Slice 5: Remove deprecated code

**Only after slices 1-4 are merged, tested, and running in production.**

**Delete:**
- `src/core/causal_v2.py` (replaced by bace.py + extracted modules)
- `src/core/rce_engine.py` (merged into bace.py)
- `src/core/rce_agents.py` (re-export stub, real code in bace_agents.py)
- `src/core/rce_ontology.py` (re-export stub, real code in bace_ontology.py)
- `src/core/rce_evidence_provider.py` (re-export stub)
- `src/core/forward_simulation.py` (deprecated, gated off)
- `src/core/attribution/` (entire directory — orchestrator no longer needed)

**Verify** no remaining imports reference deleted files:
```bash
grep -rn "causal_v2\|rce_engine\|rce_agents\|rce_ontology\|rce_evidence\|forward_simulation\|attribution.orchestrator\|attribution.adapters" src/ --include="*.py"
```
Should return zero results.

**Files deleted:** 7 files + 1 directory
**Risk:** Low if slices 1-4 are passing. Just cleanup.

---

## Execution Order

| Slice | What | Prerequisite | Risk | Est. Effort |
|-------|------|-------------|------|-------------|
| 1 | Extract utility modules from causal_v2 | None | Medium | 1 day |
| 2 | Rename rce_* → bace_* | Slice 1 | Low | 2 hours |
| 3 | Build bace.py + tests | Slices 1-2 | Medium | 2 days |
| 4 | Update all callers | Slice 3 | High | 1 day |
| 5 | Delete deprecated code | Slice 4 tested in prod | Low | 1 hour |

Total: ~4-5 days of Codex work.

---

## Config Migration

| Old env var | New env var | Mapping |
|---|---|---|
| `PYTHIA_ATTRIBUTION_MODE=fast` | `PYTHIA_BACE_DEPTH=1` | Same behavior |
| `PYTHIA_ATTRIBUTION_MODE=deep` | `PYTHIA_BACE_DEPTH=3` | Same behavior |
| `PYTHIA_ATTRIBUTION_MODE=shadow` | Removed | Use depth=2 as default instead |

Shadow mode is no longer needed because there's one engine with a depth dial,
not two competing engines. The comparison question becomes "does depth 3 beat
depth 2?" which is measured by running both depths on the same spikes via
track_record, not a side-by-side shadow mode.

---

## Output Format

All depths produce the same output dict:

```python
{
    "spike_id": int,
    "context": {...},
    "attribution": {
        "most_likely_cause": str,
        "confidence": "HIGH|MEDIUM|LOW",
        "causal_chain": str,
        "temporal_plausibility": str,
        "magnitude_plausibility": str,
        "impact_speed": str,           # depth 2+ only
        "time_to_peak_impact": str,    # depth 2+ only
    },
    "candidates_retrieved": int,
    "candidates_filtered": int,
    "top_candidates": [...],
    "statistical_validation": {...},    # if available
    "dowhy_validation": {...},          # if available
    "heterogeneous_effect": {...},      # if available
    "bace_depth": int,                  # NEW — which depth was used
    "bace_metadata": {                  # NEW — depth-specific metadata
        "agents_spawned": int,          # 0 for depth 1
        "hypotheses_proposed": int,     # 0 for depth 1
        "debate_rounds": int,           # 0 for depth 1-2
        "domain_evidence_items": int,   # 0 for depth 1
        "elapsed_seconds": float,
    },
    "timestamp": str,
}
```

Compatible with existing `attributor_engine.extract_attributor()`.

---

## What NOT to Do in This Merge

- Do not optimize prompts. Merge first, optimize later.
- Do not add new agents. The 7+2 core + conditional roster is set.
- Do not change statistical validation logic. Port as-is.
- Do not build a new comparison harness. Depth comparison is a future task.
- Do not touch the frontend. Backend-only change.
- Do not delete `causal_v2.py` until slice 4 is tested in production.
  Keep the re-export stubs so any missed callers still work.

---

## Success Criteria

1. `PYTHIA_BACE_DEPTH=1` produces identical output to current PCE on same spike
2. `PYTHIA_BACE_DEPTH=3` produces identical output to current RCE on same spike
3. `PYTHIA_BACE_DEPTH=2` runs successfully (new behavior — no regression test)
4. All existing tests pass
5. `causal_v2.py` and `rce_engine.py` can be deleted with zero import errors
6. One config knob (`PYTHIA_BACE_DEPTH`) controls attribution depth
