from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Protocol


EngineName = Literal["pce_v2", "rce_v1"]


@dataclass
class AttributionResult:
    spike_id: int
    engine: EngineName
    engine_version: str
    attribution: Dict[str, Any]
    context: Dict[str, Any]
    candidates_retrieved: int = 0
    candidates_filtered: int = 0
    top_candidates: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_legacy_result(self) -> Dict[str, Any]:
        """Compatibility payload for existing call sites expecting engine dict output."""
        result = {
            "spike_id": self.spike_id,
            "context": self.context,
            "attribution": self.attribution,
            "candidates_retrieved": self.candidates_retrieved,
            "candidates_filtered": self.candidates_filtered,
            "top_candidates": self.top_candidates,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "diagnostics": self.diagnostics,
        }
        if self.raw:
            result["raw"] = self.raw
        return result


class AttributionEngine(Protocol):
    name: EngineName
    version: str

    def attribute_spike(self, spike: Any, all_recent_spikes: List[Any], db: Any) -> AttributionResult:
        ...
