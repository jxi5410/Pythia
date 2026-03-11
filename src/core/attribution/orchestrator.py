import logging
from typing import Any, Dict, List, Literal

from .interfaces import AttributionEngine, AttributionResult
from ..evaluation.attribution_compare import persist_attribution_run, persist_shadow_comparison

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
            deep = self._run_required("rce_v1", spike, all_recent_spikes, db)
            self._persist_run(db, mode="deep", result=deep)
            return deep

        if self.mode == "shadow":
            primary = self._run_required("pce_v2", spike, all_recent_spikes, db)
            self._persist_run(db, mode="shadow_primary", result=primary)
            try:
                shadow = self._run_required("rce_v1", spike, all_recent_spikes, db)
                self._persist_run(db, mode="shadow_secondary", result=shadow)
                primary.diagnostics["shadow_engine"] = shadow.engine
                primary.diagnostics["shadow_confidence"] = shadow.attribution.get("confidence")
                primary.diagnostics["shadow_cause"] = shadow.attribution.get("most_likely_cause", "")
                self._persist_comparison(db, spike_id=primary.spike_id, primary=primary, shadow=shadow)
            except Exception as exc:
                logger.warning("Shadow attribution failed (non-fatal): %s", exc)
                primary.diagnostics["shadow_error"] = str(exc)
            return primary

        fast = self._run_required("pce_v2", spike, all_recent_spikes, db)
        self._persist_run(db, mode="fast", result=fast)
        return fast

    def _persist_run(self, db: Any, mode: str, result: AttributionResult) -> None:
        if not db:
            return
        persist_attribution_run(db=db, mode=mode, result=result.to_legacy_result())

    def _persist_comparison(self, db: Any, spike_id: int, primary: AttributionResult, shadow: AttributionResult) -> None:
        if not db:
            return
        persist_shadow_comparison(
            db=db,
            spike_id=spike_id,
            primary=primary.to_legacy_result(),
            shadow=shadow.to_legacy_result(),
        )

    def _run_required(self, engine_name: str, spike: Any, all_recent_spikes: List[Any], db: Any) -> AttributionResult:
        engine = self.engines.get(engine_name)
        if engine is None:
            raise RuntimeError(f"Attribution engine not configured: {engine_name}")
        return engine.attribute_spike(spike=spike, all_recent_spikes=all_recent_spikes, db=db)
