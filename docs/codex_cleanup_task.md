# Codex Task: Codebase cleanup — remove stale PCE/RCE/orchestrator references

## Prerequisites

Start from `main` branch. Run `git checkout main && git pull origin main`.
Create branch `codex/codebase-cleanup`.

## Goal

Clean codebase. Remove all dead code, stale references, deprecated modules,
and obsolete docs. After this task, the codebase should have one clear
attribution path (`bace.py`) with no references to "PCE", "RCE", orchestrator,
or adapters in production code.

---

## 1. Delete the `src/core/attribution/` directory entirely

This directory contains the deprecated orchestrator and adapters. Nothing in
production imports from it anymore.

Delete:
```
src/core/attribution/__init__.py
src/core/attribution/interfaces.py
src/core/attribution/orchestrator.py
src/core/attribution/adapters/__init__.py
src/core/attribution/adapters/pce_adapter.py
src/core/attribution/adapters/rce_adapter.py
```

Remove the directories too (`src/core/attribution/adapters/`, `src/core/attribution/`).

## 2. Delete the re-export stub files

These are 3-line files that just re-export from bace_*. No production code
imports from them anymore (bace.py imports from rce_engine.py directly,
not from rce_agents.py).

Delete:
```
src/core/rce_agents.py
src/core/rce_ontology.py
src/core/rce_evidence_provider.py
```

## 3. Delete stale tests

These test the orchestrator and adapters which no longer exist:
```
tests/test_attribution_orchestrator.py
tests/test_pce_adapter.py
```

Also delete `tests/test_rce_bace_compat_reexports.py` — it tests the re-export
stubs which are being deleted above.

## 4. Delete superseded docs

These planning docs are historical artifacts — the work is complete:
```
docs/attribution_refactor_plan.md
docs/codex_implementation_plan_slice2_7.md
docs/codex_bace_slices_3_5.md
```

Keep `docs/bace_merge_plan.md` but add at the very top:
```
> **Status: COMPLETE.** All 5 slices merged as of 2026-03-12.
> This document is retained for historical reference only.
```

## 5. Clean up `src/core/config.py`

Remove the stale `ATTRIBUTION_MODE` config and its comment:

```python
# REMOVE these lines:
    # Attribution engine mode: fast (PCE), deep (RCE), shadow (PCE + RCE eval)
    ATTRIBUTION_MODE = os.getenv("PYTHIA_ATTRIBUTION_MODE", "fast").strip().lower()
```

Keep the `BACE_DEPTH` line.

## 6. Clean up `src/core/bace.py` docstring

Replace the PCE/RCE reference in the module docstring:

```python
# BEFORE:
"""BACE — Backward Attribution Causal Engine.

Unified, depth-configurable attribution entrypoint.
Depth 1 maps to the current PCE path; depth 2/3 map to the current RCE path
with different debate intensity.
"""

# AFTER:
"""BACE — Backward Attribution Causal Engine.

Unified, depth-configurable attribution for prediction market spikes.

Depth 1 (FAST):     Single-shot LLM reasoning, ~3 calls, ~$0.03/spike
Depth 2 (STANDARD): Multi-agent proposals with domain evidence, ~15 calls, ~$0.15/spike
Depth 3 (DEEP):     Full adversarial debate + counterfactual testing, ~95 calls, ~$0.47/spike

Config: PYTHIA_BACE_DEPTH=1|2|3 (default: 2)
"""
```

## 7. Rename `src/core/rce_engine.py` → `src/core/bace_debate.py`

This file contains the multi-agent debate logic used by BACE depths 2 and 3.
"rce_engine" is a stale name. Rename it to `bace_debate.py`.

Steps:
1. Copy `src/core/rce_engine.py` to `src/core/bace_debate.py`
2. In `bace_debate.py`, update the module docstring:
   ```python
   # BEFORE:
   """Reverse Causal Engine (RCE) — Multi-agent adversarial attribution pipeline. ..."""

   # AFTER:
   """BACE Debate Engine — Multi-agent adversarial attribution.

   Used by bace.py at depth 2 (proposals only) and depth 3 (proposals + debate).
   ..."""
   ```
3. In `bace_debate.py`, update internal imports if any reference `rce_engine`
   (there shouldn't be self-references, but check).
4. Update the comment in `bace_debate.py` at line ~164 that says
   "from rce_evidence_provider" → "from bace_evidence_provider" (should already
   be correct from the rename, but verify).
5. In `src/core/bace.py`, update the import:
   ```python
   # BEFORE:
   from .rce_engine import attribute_spike_rce

   # AFTER:
   from .bace_debate import attribute_spike_rce
   ```
6. Delete `src/core/rce_engine.py`.

## 8. Clean up `src/core/causal_v2.py` references

`causal_v2.py` is still used internally by `bace.py` (depth 1) and
`bace_debate.py` (for `retrieve_candidate_news`). These are legitimate
internal dependencies. But clean up comments and docstrings inside `causal_v2.py`
that reference the old architecture.

In `causal_v2.py`, update the module docstring at the top:
```python
# BEFORE:
"""Pythia Causal Analysis v2 — 5-layer attribution pipeline with governance. ..."""

# AFTER:
"""BACE Fast Attribution — Single-shot causal attribution pipeline.

Used internally by bace.py at depth=1 (FAST mode).
Not called directly — use bace.attribute_spike(depth=1) instead.

Layers:
  1. Context Builder (entity extraction)
  1.5. Counterfactual Validation (CausalImpact / z-score)
  2. News Retrieval (multi-source, temporal filtered)
  3. Candidate Filter (LLM relevance scoring)
  4. Causal Reasoning (LLM deep analysis)
  4.5. DAG Refutation (DoWhy)
  4.6. Heterogeneous Effects (EconML)
  5. Store & Learn
"""
```

Also in `causal_v2.py`, remove or update any comments that say "PCE" or
reference the old architecture. Just make them say "BACE depth 1" or
"fast attribution" instead.

Do NOT change any function signatures, logic, or behavior in `causal_v2.py`.
Only update comments and docstrings.

## 9. Clean up `src/core/bace_debate.py` (formerly rce_engine.py)

Update any internal comments or docstrings that say "RCE" or "Reverse Causal Engine":
- Replace "RCE" with "BACE debate engine" or just "debate engine"
- Replace "Reverse Causal Engine" with "BACE multi-agent debate"
- Leave function names unchanged (`attribute_spike_rce` stays — it's called by bace.py)

Do NOT change any function signatures, logic, or behavior. Only comments/docstrings.

## 10. Clean up `src/core/bace_agents.py`

Update the module docstring at the top:
```python
# BEFORE (first line):
"""RCE Agents — Multi-agent adversarial causal debate system. ..."""

# AFTER:
"""BACE Agents — Multi-agent adversarial causal debate system. ..."""
```

Replace any remaining "RCE" references in comments with "BACE".
Do NOT change any code, agent definitions, or function signatures.

## 11. Verify no stale references remain

Run this command and ensure ZERO results from `src/` (docs are OK):
```bash
grep -rn "PCE\|RCE\|rce_engine\|rce_agents\|rce_ontology\|rce_evidence_provider\|forward_simulation\|attribution.orchestrator\|attribution.adapters\|ATTRIBUTION_MODE" src/ --include="*.py" | grep -v __pycache__ | grep -v "causal_v2.py" | grep -v "EVT_"
```

The only allowed references to `causal_v2` are in `bace.py` and `bace_debate.py`
(they call it internally). Everything else should be zero.

If `attribute_spike_rce` appears in `bace.py`, that's fine — it's a function name
being imported from `bace_debate.py`.

## 12. Run all remaining tests

```bash
python3 -m pytest tests/ -v
```

Tests that should still exist and pass:
- `tests/test_bace_depths.py`
- `tests/test_news_retrieval.py`
- `tests/test_attribution_compare_persistence.py`
- `tests/test_extracted_modules.py`

Tests that should NOT exist (deleted in step 3):
- `tests/test_attribution_orchestrator.py`
- `tests/test_pce_adapter.py`
- `tests/test_rce_bace_compat_reexports.py`

All remaining tests must pass.

---

## Commit

Single commit:
```
refactor: codebase cleanup — remove stale PCE/RCE/orchestrator references

- Delete src/core/attribution/ directory (deprecated orchestrator + adapters)
- Delete re-export stubs (rce_agents.py, rce_ontology.py, rce_evidence_provider.py)
- Rename rce_engine.py → bace_debate.py, update bace.py import
- Remove ATTRIBUTION_MODE from config (replaced by BACE_DEPTH)
- Update all docstrings: PCE → "BACE depth 1", RCE → "BACE debate engine"
- Delete stale tests (orchestrator, pce_adapter, reexport compat)
- Delete superseded planning docs
- Mark bace_merge_plan.md as complete
```

Push as PR from `codex/codebase-cleanup` branch.

---

## Critical constraints

- Do NOT change any function signatures or behavior. This is a naming/cleanup task.
- Do NOT delete `causal_v2.py` — it's still used internally by bace.py depth 1.
- Do NOT delete `bace_debate.py` (the renamed rce_engine.py) — used by bace.py depth 2/3.
- Do NOT modify `bace_agents.py`, `bace_ontology.py`, or `bace_evidence_provider.py`
  beyond docstring/comment updates.
- `attribute_spike_rce` function name in bace_debate.py stays unchanged —
  renaming function signatures is a separate task.
