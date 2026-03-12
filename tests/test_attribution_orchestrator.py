import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dataclasses import dataclass

from core.attribution.interfaces import AttributionResult
from core.attribution.orchestrator import AttributionOrchestrator


@dataclass
class DummyEngine:
    name: str
    version: str = "x"
    calls: int = 0

    def attribute_spike(self, spike, all_recent_spikes, db):
        self.calls += 1
        return AttributionResult(
            spike_id=1,
            engine=self.name,
            engine_version=self.version,
            attribution={"most_likely_cause": self.name, "confidence": "LOW"},
            context={"spike": {"market_id": "m1"}},
        )


def test_orchestrator_fast_mode_runs_pce_only():
    pce = DummyEngine(name="pce_v2")
    rce = DummyEngine(name="rce_v1")
    o = AttributionOrchestrator(mode="fast", engines={"pce_v2": pce, "rce_v1": rce})

    result = o.attribute_spike(spike=object(), all_recent_spikes=[], db=None)

    assert result.engine == "pce_v2"
    assert pce.calls == 1
    assert rce.calls == 0


def test_orchestrator_shadow_mode_runs_both_and_returns_pce():
    pce = DummyEngine(name="pce_v2")
    rce = DummyEngine(name="rce_v1")
    o = AttributionOrchestrator(mode="shadow", engines={"pce_v2": pce, "rce_v1": rce})

    result = o.attribute_spike(spike=object(), all_recent_spikes=[], db=None)

    assert result.engine == "pce_v2"
    assert pce.calls == 1
    assert rce.calls == 1
    assert result.diagnostics["shadow_engine"] == "rce_v1"
