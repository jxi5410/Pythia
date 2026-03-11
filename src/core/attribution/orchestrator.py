import logging
from typing import Any, Dict, List, Literal

from .interfaces import AttributionEngine, AttributionResult

logger = logging.getLogger(__name__)

AttributionMode = Literal["fast", "deep", "shadow"]


class AttributionOrchestrator:
    def __init__(self, mode: str, engines: Dict[str, AttributionEngine]):
        self.mode: AttributionMode = self._normalize_mode(mode)
        self.engines = engines

    def _normalize_mode(self, mode: str) -> AttributionMode:
        if mode in ("fast", "deep", "shadow"):
            return mode
        logger.warning("Unknown attribution mode '%s'; defaulting to fast", mode)
        return "fast"

    def attribute_spike(self, spike: Any, all_recent_spikes: List[Any], db: Any) -> AttributionResult:
        if self.mode == "deep":
            return self._run_required("rce_v1", spike, all_recent_spikes, db)

        if self.mode == "shadow":
            primary = self._run_required("pce_v2", spike, all_recent_spikes, db)
            try:
                shadow = self._run_required("rce_v1", spike, all_recent_spikes, db)
                primary.diagnostics["shadow_engine"] = shadow.engine
                primary.diagnostics["shadow_confidence"] = shadow.attribution.get("confidence")
                primary.diagnostics["shadow_cause"] = shadow.attribution.get("most_likely_cause", "")
            except Exception as exc:
                logger.warning("Shadow attribution failed (non-fatal): %s", exc)
                primary.diagnostics["shadow_error"] = str(exc)
            return primary

        return self._run_required("pce_v2", spike, all_recent_spikes, db)

    def _run_required(self, engine_name: str, spike: Any, all_recent_spikes: List[Any], db: Any) -> AttributionResult:
        engine = self.engines.get(engine_name)
        if engine is None:
            raise RuntimeError(f"Attribution engine not configured: {engine_name}")
        return engine.attribute_spike(spike=spike, all_recent_spikes=all_recent_spikes, db=db)
