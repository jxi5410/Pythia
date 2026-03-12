"""BACE — Backward Attribution Causal Engine.

Unified, depth-configurable attribution for prediction market spikes.

Depth 1 (FAST):     Single-shot LLM reasoning, ~3 calls, ~$0.03/spike
Depth 2 (STANDARD): Multi-agent proposals with domain evidence, ~15 calls, ~$0.15/spike
Depth 3 (DEEP):     Full adversarial debate + counterfactual testing, ~95 calls, ~$0.47/spike

Config: PYTHIA_BACE_DEPTH=1|2|3 (default: 2)
"""

from enum import IntEnum
from typing import Dict, List, Optional


class BACEDepth(IntEnum):
    FAST = 1
    STANDARD = 2
    DEEP = 3


def _confidence_score(confidence: str) -> float:
    return {"HIGH": 0.9, "MEDIUM": 0.65, "LOW": 0.35}.get((confidence or "").upper(), 0.0)


def _with_bace_metadata(result: Dict, depth: int, elapsed_seconds: Optional[float] = None) -> Dict:
    out = dict(result)
    out["bace_depth"] = int(depth)

    md = dict(out.get("bace_metadata", {}))
    md.setdefault("agents_spawned", out.get("agents_spawned", 0))
    md.setdefault("hypotheses_proposed", out.get("total_hypotheses", 0))
    md.setdefault("debate_rounds", out.get("debate_rounds", 0))
    md.setdefault("domain_evidence_items", 0)
    if elapsed_seconds is not None:
        md.setdefault("elapsed_seconds", elapsed_seconds)
    else:
        md.setdefault("elapsed_seconds", out.get("elapsed_seconds", 0.0))
    out["bace_metadata"] = md
    return out


def attribute_spike(
    spike,
    all_recent_spikes: Optional[List] = None,
    db=None,
    depth: int = BACEDepth.STANDARD,
    llm_fast=None,
    llm_strong=None,
) -> Dict:
    """Unified attribution pipeline.

    Returns dict compatible with attributor_engine.extract_attributor().
    """
    all_recent_spikes = all_recent_spikes or []
    depth = int(depth)

    if depth <= int(BACEDepth.FAST):
        from .causal_v2 import attribute_spike_v2

        result = attribute_spike_v2(
            spike,
            all_recent_spikes=all_recent_spikes,
            entity_llm=llm_fast,
            filter_llm=llm_fast,
            reasoning_llm=llm_strong or llm_fast,
            db=db,
        )
        return _with_bace_metadata(result, BACEDepth.FAST)

    from .bace_debate import attribute_spike_rce

    debate_rounds = 0 if depth == int(BACEDepth.STANDARD) else 2
    result = attribute_spike_rce(
        spike=spike,
        all_recent_spikes=all_recent_spikes,
        llm_call=llm_fast,
        ontology_llm=llm_strong or llm_fast,
        db=db,
        debate_rounds=debate_rounds,
    )
    return _with_bace_metadata(result, BACEDepth.STANDARD if debate_rounds == 0 else BACEDepth.DEEP)


def attribute_spike_with_governance(spike, all_recent_spikes=None, db=None, depth: int = BACEDepth.STANDARD,
                                    llm_fast=None, llm_strong=None):
    """Governance-compatible wrapper returning (result, trail).

    Maintains the tuple signature used by main.py, while delegating attribution
    to unified BACE.
    """
    result = attribute_spike(
        spike=spike,
        all_recent_spikes=all_recent_spikes,
        db=db,
        depth=depth,
        llm_fast=llm_fast,
        llm_strong=llm_strong,
    )

    conf = result.get("attribution", {}).get("confidence", "LOW")
    final_confidence = _confidence_score(conf)
    decision = "AUTO_RELAY" if final_confidence >= 0.65 else "FLAG_REVIEW" if final_confidence >= 0.35 else "REJECT"

    result["final_confidence"] = final_confidence
    result["decision"] = decision
    return result, None
