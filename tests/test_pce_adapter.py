import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dataclasses import dataclass

from core.attribution.adapters.pce_adapter import PCEEngineAdapter


@dataclass
class MockSpike:
    id: int = 42


def test_pce_adapter_normalizes_legacy_result(monkeypatch):
    def fake_attribute_spike_v2(spike, all_recent_spikes=None, entity_llm=None, filter_llm=None, reasoning_llm=None, db=None):
        return {
            "spike_id": spike.id,
            "context": {"category": "macro", "spike": {"market_id": "abc"}},
            "attribution": {"most_likely_cause": "Fed", "confidence": "MEDIUM"},
            "candidates_retrieved": 7,
            "candidates_filtered": 2,
            "top_candidates": [{"headline": "Fed minutes"}],
            "statistical_validation": {"is_significant": True},
        }

    monkeypatch.setattr("core.attribution.adapters.pce_adapter.attribute_spike_v2", fake_attribute_spike_v2)

    adapter = PCEEngineAdapter()
    result = adapter.attribute_spike(spike=MockSpike(), all_recent_spikes=[], db=None)

    assert result.engine == "pce_v2"
    assert result.spike_id == 42
    assert result.attribution["most_likely_cause"] == "Fed"
    assert result.candidates_retrieved == 7
    assert result.diagnostics["statistical_validation"] == {"is_significant": True}

    legacy = result.to_legacy_result()
    assert legacy["engine"] == "pce_v2"
    assert legacy["attribution"]["confidence"] == "MEDIUM"
