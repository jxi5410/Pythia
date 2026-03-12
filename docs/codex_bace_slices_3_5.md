# Codex Task: BACE Slices 3-5 — Build unified engine + update callers + cleanup

## Prerequisites

Start from `main` branch. Run `git checkout main && git pull origin main`.

Verify these files exist before starting:
```
src/core/bace_agents.py
src/core/bace_ontology.py
src/core/bace_evidence_provider.py
src/core/market_classifier.py
src/core/spike_context.py
src/core/feedback.py
src/core/evidence/news_retrieval.py
src/core/evaluation/attribution_compare.py
```

Read the full plan at `docs/bace_merge_plan.md`. Slices 1-2 are complete.
This task implements slices 3, 4, and 5.

---

## Slice 3: Create `src/core/bace.py`

This is the core deliverable. One file, one public function, three depth levels.

### Public API

```python
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

class BACEDepth(IntEnum):
    FAST = 1      # ~3 LLM calls
    STANDARD = 2  # ~15 LLM calls
    DEEP = 3      # ~95 LLM calls

def attribute_spike(
    spike: Any,
    all_recent_spikes: List[Any] = None,
    db: Any = None,
    depth: int = BACEDepth.STANDARD,
    llm_fast: callable = None,
    llm_strong: callable = None,
) -> Dict:
    """Unified backward attribution. Returns dict compatible with
    attributor_engine.extract_attributor()."""

def attribute_spike_with_governance(
    spike: Any,
    all_recent_spikes: List[Any] = None,
    db: Any = None,
    depth: int = BACEDepth.STANDARD,
    llm_fast: callable = None,
    llm_strong: callable = None,
) -> Tuple[Dict, Any]:
    """Governance-wrapped BACE. Returns (result_dict, audit_trail).
    Used by main.py live polling loop."""
```

### Internal structure

```python
def attribute_spike(spike, ..., depth=BACEDepth.STANDARD):
    # Default LLM callables if not provided
    if llm_fast is None:
        from .llm_integration import sonnet_call
        llm_fast = sonnet_call
    if llm_strong is None:
        from .llm_integration import opus_call
        llm_strong = opus_call

    # --- Shared: context building (free, all depths) ---
    from .spike_context import build_spike_context
    context = build_spike_context(spike, all_recent_spikes or [], entity_llm=llm_fast)

    # --- Shared: statistical validation (free, gates LLM spend) ---
    stat = _run_statistical_validation(db, spike, context)
    if stat and not stat.get("is_significant", True):
        return _insignificant_result(spike, context, stat)

    # --- Depth 1 (FAST): single-shot attribution ---
    if depth <= BACEDepth.FAST:
        return _run_fast(spike, context, db, llm_fast, llm_strong)

    # --- Depth 2+: ontology + domain evidence + multi-agent ---
    from .bace_ontology import extract_causal_ontology
    from .bace_agents import spawn_agents
    from .bace_evidence_provider import gather_all_agent_evidence
    from .evidence.news_retrieval import retrieve_candidate_news

    ontology = extract_causal_ontology(context, llm_call=llm_strong)
    news_evidence = _gather_news(ontology, context)
    agents = spawn_agents(context.get("category", "general"))
    agent_evidence = gather_all_agent_evidence(agents, context, news_evidence)

    if depth == BACEDepth.STANDARD:
        return _run_standard(spike, context, ontology, news_evidence,
                            agents, agent_evidence, db, llm_fast, llm_strong)

    # --- Depth 3 (DEEP): full adversarial debate ---
    return _run_deep(spike, context, ontology, news_evidence,
                     agents, agent_evidence, db, llm_fast, llm_strong)
```

### `_run_fast()` — port from causal_v2.attribute_spike_v2

Port these steps from `causal_v2.py`:
1. `retrieve_candidate_news(context)` — import from `evidence.news_retrieval`
2. `filter_candidates(context, candidates, llm_call=llm_fast)` — port the function
   from `causal_v2.py` into `bace.py` as a private function `_filter_candidates()`
3. `reason_about_cause(context, filtered, llm_call=llm_strong)` — port from
   `causal_v2.py` as `_reason_about_cause()`
4. `_run_dag_refutation(context, result, db)` — port the DoWhy call
5. `_run_heterogeneous_effects(context, result, db)` — port the EconML call
6. Format and return the result dict

The prompt templates (`FILTER_PROMPT`, `CAUSAL_PROMPT`) should be copied from
`causal_v2.py` into `bace.py`.

The `feedback.get_feedback_summary()` hint should be injected into the reasoning
prompt, same as causal_v2 does.

### `_run_standard()` — NEW (does not exist today)

1. Run proposal round: each agent proposes 1-3 hypotheses (same as rce_engine's
   `run_proposal_round`). Import from `bace_agents.build_proposal_prompt`.
   Each agent gets their domain evidence via `agent_evidence[agent.id]`.
   This is 7-9 LLM calls (one per non-adversarial agent).

2. Rank and select: ONE LLM call (llm_strong) to pick the best hypothesis.
   Prompt format:
   ```
   You are the final judge in the Pythia attribution engine.

   {N} agents have proposed causal hypotheses for this spike:

   {for each hypothesis: agent_name, cause_description, causal_chain,
    confidence, temporal_plausibility, magnitude_plausibility, impact_speed,
    evidence list}

   Select the single most likely cause. Consider:
   - Evidence strength and diversity
   - Temporal plausibility (cause must precede effect)
   - Magnitude plausibility (cause must be proportional to spike)
   - Consensus across agents (multiple agents supporting = stronger)

   Return ONLY valid JSON:
   {
     "selected_hypothesis_index": 0,
     "most_likely_cause": "...",
     "confidence": "HIGH|MEDIUM|LOW",
     "causal_chain": "...",
     "temporal_plausibility": "...",
     "magnitude_plausibility": "...",
     "impact_speed": "...",
     "time_to_peak_impact": "...",
     "reasoning": "Why this hypothesis was selected over others"
   }
   ```

3. Run DAG refutation and heterogeneous effects (same as fast).

4. Return result dict.

### `_run_deep()` — port from rce_engine.attribute_spike_rce

Port these steps from `rce_engine.py`:
1. Proposal round (same as standard, already done above)
2. `run_critique_round()` × 2 rounds — import from `bace_agents.build_critique_prompt`
3. `run_counterfactual_round()` — import from `bace_agents.build_counterfactual_prompt`
4. Extract surviving hypotheses
5. Run DAG refutation and heterogeneous effects
6. Return result dict

The debate functions (`run_proposal_round`, `run_critique_round`,
`run_counterfactual_round`) currently live in `rce_engine.py`. You have two options:
- **Option A (simpler):** Import them from `rce_engine.py` for now. Add
  `# TODO: move debate functions into bace.py` comment.
- **Option B (cleaner):** Copy them into `bace.py` as private functions.

Choose Option A for this slice — moving debate functions is cleanup work.

### `_run_statistical_validation()` — port from causal_v2

Port the counterfactual/DoWhy/EconML validation blocks from `causal_v2.py`
(lines ~858-960). These call:
```python
from .counterfactual import validate_spike
from .causal_dag import estimate_causal_effect
from .heterogeneous_effects import predict_effect
```
Wrap each in try/except ImportError (these are optional dependencies).

### `attribute_spike_with_governance()` — wrapper

```python
def attribute_spike_with_governance(spike, all_recent_spikes=None,
                                    db=None, depth=BACEDepth.STANDARD,
                                    llm_fast=None, llm_strong=None):
    """Governance-wrapped BACE. Used by main.py."""
    try:
        from .governance import (
            AuditTrail, AgentAction, AgentRole,
            init_governance, get_governance, GOVERNANCE_AVAILABLE,
        )
    except ImportError:
        GOVERNANCE_AVAILABLE = False

    if not GOVERNANCE_AVAILABLE:
        result = attribute_spike(spike, all_recent_spikes, db, depth, llm_fast, llm_strong)
        return result, None

    # Initialize governance
    try:
        config, breaker, validator, exporter = get_governance()
    except RuntimeError:
        init_governance()
        config, breaker, validator, exporter = get_governance()

    # Create audit trail
    import uuid
    from datetime import datetime
    trail = AuditTrail(
        run_id=str(uuid.uuid4()),
        market_id=spike.market_id,
        market_title=spike.market_title,
        start_time=datetime.now().isoformat(),
    )

    try:
        result = attribute_spike(spike, all_recent_spikes, db, depth, llm_fast, llm_strong)

        # Decision gate based on confidence
        confidence_str = result.get("attribution", {}).get("confidence", "LOW")
        confidence_val = {"HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.2}.get(confidence_str, 0.0)
        result["final_confidence"] = confidence_val

        if confidence_val >= 0.6:
            result["decision"] = "AUTO_RELAY"
        elif confidence_val >= 0.3:
            result["decision"] = "FLAG_REVIEW"
        else:
            result["decision"] = "REJECT"

        trail.end_time = datetime.now().isoformat()
        return result, trail

    except Exception as e:
        trail.error = str(e)
        trail.end_time = datetime.now().isoformat()
        raise
```

NOTE: The governance wrapper in `causal_v2.py` (lines 993-1290) is more elaborate
with per-layer audit actions. The version above is a simplified port. If you want
to match exactly, copy the full governance logic from causal_v2. But the simplified
version preserves the key behavior: decision gate + audit trail.

### Output format (ALL depths)

All depths MUST return this dict structure:

```python
{
    "spike_id": int,
    "context": dict,       # from build_spike_context
    "attribution": {
        "most_likely_cause": str,
        "confidence": "HIGH|MEDIUM|LOW",
        "causal_chain": str,
        "confidence_reasoning": str,
        "temporal_plausibility": str,
        "magnitude_plausibility": str,
        "impact_speed": str,           # depth 2+ only, "" for depth 1
        "time_to_peak_impact": str,    # depth 2+ only, "" for depth 1
        "expected_duration": str,
        "trading_implication": str,
    },
    "candidates_retrieved": int,
    "candidates_filtered": int,
    "top_candidates": list,
    "statistical_validation": dict or None,
    "dowhy_validation": dict or None,
    "heterogeneous_effect": dict or None,
    "bace_depth": int,     # 1, 2, or 3
    "bace_metadata": {
        "agents_spawned": int,          # 0 for depth 1
        "hypotheses_proposed": int,     # 0 for depth 1
        "debate_rounds": int,           # 0 for depth 1-2
        "domain_evidence_items": int,   # 0 for depth 1
        "elapsed_seconds": float,
    },
    "timestamp": str,      # ISO format
}
```

This is compatible with `attributor_engine.extract_attributor()`.

### Tests for Slice 3

Create `tests/test_bace.py`:

```python
def test_bace_fast_makes_expected_llm_calls():
    """Depth 1 should make exactly 3 LLM calls: entity, filter, reason."""
    call_count = 0
    def mock_llm(prompt):
        nonlocal call_count
        call_count += 1
        # Return valid JSON for each call type
        if "entity" in prompt.lower() or "extract" in prompt.lower():
            return '["entity1", "entity2"]'
        if "filter" in prompt.lower() or "relevance" in prompt.lower():
            return '[{"headline": "test", "relevance": 0.8}]'
        return '{"most_likely_cause": "Test cause", "confidence": "MEDIUM", ...}'
    # ... create mock spike, call attribute_spike(depth=1), assert call_count <= 4

def test_bace_standard_spawns_agents():
    """Depth 2 should spawn agents and produce hypotheses."""
    # Mock LLM, mock spike, call attribute_spike(depth=2)
    # Assert result["bace_metadata"]["agents_spawned"] > 0
    # Assert result["bace_depth"] == 2

def test_bace_deep_includes_debate():
    """Depth 3 should include debate rounds."""
    # Assert result["bace_metadata"]["debate_rounds"] > 0

def test_bace_output_compat_with_attributor_engine():
    """Output dict should be accepted by attributor_engine.extract_attributor()."""
    # Create result from attribute_spike, pass to extract_attributor
    # Should not raise

def test_bace_statistical_gate_skips_llm():
    """If spike fails statistical validation, 0 LLM calls."""
    # Monkeypatch validate_spike to return {"is_significant": False, "p_value": 0.8}
    # Assert call_count == 0

def test_bace_governance_wrapper():
    """attribute_spike_with_governance returns (result, trail) tuple."""
    # Test that decision gate works: HIGH confidence → AUTO_RELAY
```

Use monkeypatching for LLM calls. Do NOT make real API calls in tests.

---

## Slice 4: Update all callers

### `src/core/config.py`

Replace `ATTRIBUTION_MODE` with `BACE_DEPTH`:

```python
# BEFORE:
ATTRIBUTION_MODE = os.getenv("PYTHIA_ATTRIBUTION_MODE", "fast").strip().lower()

# AFTER:
BACE_DEPTH = int(os.getenv("PYTHIA_BACE_DEPTH", "2"))  # 1=fast, 2=standard, 3=deep
```

Keep `ATTRIBUTION_MODE` as a deprecated alias that maps to BACE_DEPTH:
```python
# Backward compat
_legacy_mode = os.getenv("PYTHIA_ATTRIBUTION_MODE", "").strip().lower()
if _legacy_mode == "fast":
    BACE_DEPTH = 1
elif _legacy_mode == "deep":
    BACE_DEPTH = 3
elif _legacy_mode:
    BACE_DEPTH = 2
else:
    BACE_DEPTH = int(os.getenv("PYTHIA_BACE_DEPTH", "2"))
```

### `src/core/pipeline.py`

Replace orchestrator with direct BACE call:

```python
# REMOVE these imports:
from .attribution.adapters import PCEEngineAdapter, RCEEngineAdapter
from .attribution.orchestrator import AttributionOrchestrator

# ADD:
from .bace import attribute_spike as bace_attribute_spike, BACEDepth
```

In `PipelineRunner.__init__()`, REMOVE the orchestrator setup (lines 79-92).
Add: `self._bace_depth = getattr(self.config, "BACE_DEPTH", 2)`

In the attribution call site (around line 172), replace:
```python
# BEFORE:
attribution_result = self._attribution_orchestrator.attribute_spike(
    spike=spike, all_recent_spikes=self._recent_spike_proxies, db=self.db,
)
result = attribution_result.to_legacy_result()

# AFTER:
result = bace_attribute_spike(
    spike=spike,
    all_recent_spikes=self._recent_spike_proxies,
    db=self.db,
    depth=self._bace_depth,
    llm_fast=llm_call,
    llm_strong=llm_call,
)
```

### `src/core/main.py`

```python
# BEFORE (line 29):
from .causal_v2 import attribute_spike_with_governance

# AFTER:
from .bace import attribute_spike_with_governance
```

The governance wrapper signature is identical, so the decision gate logic
at lines 631-660 does NOT need to change. The `result` dict and `audit_trail`
have the same structure.

### `src/core/spike_archive.py`

```python
# BEFORE (inside attribute_spike_v2_wrapper, line 259):
from .causal_v2 import attribute_spike_v2
result = attribute_spike_v2(spike, all_recent_spikes=..., entity_llm=..., ...)

# AFTER:
from .bace import attribute_spike as bace_attribute_spike, BACEDepth
result = bace_attribute_spike(
    spike,
    all_recent_spikes=all_recent_spikes or [],
    db=db,
    depth=BACEDepth.FAST,
)
```

### Files that are ALREADY updated (no changes needed):

- `src/core/backtest.py` — already imports from `market_classifier`
- `src/core/intelligence_api.py` — already imports from `feedback`

### Tests

Run ALL existing tests plus `test_bace.py` to verify nothing breaks:
```bash
python3 -m pytest tests/ -v
```

---

## Slice 5: Delete deprecated code

**ONLY do this after slices 3-4 tests pass.**

### Delete these files:
```
src/core/causal_v2.py
src/core/rce_engine.py
src/core/rce_agents.py              # re-export stub
src/core/rce_ontology.py            # re-export stub
src/core/rce_evidence_provider.py   # re-export stub
src/core/forward_simulation.py
src/core/attribution/__init__.py
src/core/attribution/adapters/__init__.py
src/core/attribution/adapters/pce_adapter.py
src/core/attribution/adapters/rce_adapter.py
src/core/attribution/interfaces.py
src/core/attribution/orchestrator.py
```

Also delete the `src/core/attribution/` and `src/core/attribution/adapters/`
directories.

### Verify no remaining imports:

```bash
grep -rn "causal_v2\|rce_engine\|rce_agents\|rce_ontology\|rce_evidence\|forward_simulation\|attribution.orchestrator\|attribution.adapters" src/ --include="*.py" | grep -v __pycache__
```

This should return ZERO results. If any remain, fix them.

### Delete stale tests:

```
tests/test_pce_adapter.py          # tests adapter that no longer exists
tests/test_attribution_orchestrator.py  # tests orchestrator that no longer exists
```

### Update `docs/bace_merge_plan.md`:

Add at the top:
```
## Status: COMPLETE (all 5 slices merged)
```

### Run full test suite:

```bash
python3 -m pytest tests/ -v
```

All tests must pass.

---

## Commit strategy

Make ONE commit per slice:

1. `feat: BACE engine with depth=1|2|3 (slice 3)`
2. `refactor: update all callers to use BACE (slice 4)`
3. `chore: delete deprecated causal_v2, rce_engine, orchestrator (slice 5)`

Push as a single PR from a branch named `codex/bace-slices-3-5`.

---

## Critical constraints

- Do NOT make real LLM API calls in tests. Use monkeypatching/mocking.
- Do NOT change `bace_agents.py`, `bace_ontology.py`, or `bace_evidence_provider.py`.
  These are already complete and tested.
- Do NOT change the governance module (`governance.py`). Just import and wrap.
- The `_run_standard()` depth level is NEW code. The `_run_fast()` and `_run_deep()`
  levels are ports of existing code. Port accurately, don't redesign.
- Output dict format must be compatible with `attributor_engine.extract_attributor()`.
  Check that function's signature to understand what fields it reads.
