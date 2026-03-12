from typing import Any, Callable, List

from ...rce_engine import attribute_spike_rce
from ..interfaces import AttributionResult


class RCEEngineAdapter:
    name = "rce_v1"
    version = "1"

    def __init__(
        self,
        llm_call: Callable[[str], str] | None = None,
        ontology_llm: Callable[[str], str] | None = None,
        debate_rounds: int | None = None,
    ):
        self._llm_call = llm_call
        self._ontology_llm = ontology_llm
        self._debate_rounds = debate_rounds

    def attribute_spike(self, spike: Any, all_recent_spikes: List[Any], db: Any) -> AttributionResult:
        kwargs = {
            "spike": spike,
            "all_recent_spikes": all_recent_spikes,
            "llm_call": self._llm_call,
            "ontology_llm": self._ontology_llm,
            "db": db,
        }
        if self._debate_rounds is not None:
            kwargs["debate_rounds"] = self._debate_rounds

        raw = attribute_spike_rce(**kwargs)
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
                "debate_rounds": raw.get("debate_rounds"),
                "agents_spawned": raw.get("agents_spawned"),
                "elapsed_seconds": raw.get("elapsed_seconds"),
                "total_hypotheses": raw.get("total_hypotheses"),
            },
            raw=raw,
        )
