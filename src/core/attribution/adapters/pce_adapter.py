from typing import Any, Callable, Dict, List

from ...causal_v2 import attribute_spike_v2
from ..interfaces import AttributionResult


class PCEEngineAdapter:
    name = "pce_v2"
    version = "2"

    def __init__(
        self,
        entity_llm: Callable[[str], str] | None = None,
        filter_llm: Callable[[str], str] | None = None,
        reasoning_llm: Callable[[str], str] | None = None,
    ):
        self._entity_llm = entity_llm
        self._filter_llm = filter_llm
        self._reasoning_llm = reasoning_llm

    def attribute_spike(self, spike: Any, all_recent_spikes: List[Any], db: Any) -> AttributionResult:
        raw: Dict[str, Any] = attribute_spike_v2(
            spike=spike,
            all_recent_spikes=all_recent_spikes,
            entity_llm=self._entity_llm,
            filter_llm=self._filter_llm,
            reasoning_llm=self._reasoning_llm,
            db=db,
        )
        return AttributionResult(
            spike_id=int(raw.get("spike_id", getattr(spike, "id", 0) or 0)),
            engine=self.name,
            engine_version=self.version,
            attribution=raw.get("attribution", {}),
            context=raw.get("context", {}),
            candidates_retrieved=int(raw.get("candidates_retrieved", 0) or 0),
            candidates_filtered=int(raw.get("candidates_filtered", 0) or 0),
            top_candidates=raw.get("top_candidates", []) or [],
            diagnostics={
                "statistical_validation": raw.get("statistical_validation"),
                "dowhy_validation": raw.get("dowhy_validation"),
                "heterogeneous_effect": raw.get("heterogeneous_effect"),
            },
            raw=raw,
        )
