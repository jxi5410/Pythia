import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.bace import BACEDepth, attribute_spike


class _Spike:
    id = 1


def test_bace_fast_uses_causal_v2(monkeypatch):
    monkeypatch.setattr(
        "core.causal_v2.attribute_spike_v2",
        lambda *a, **k: {"spike_id": 1, "attribution": {"confidence": "HIGH"}},
    )

    out = attribute_spike(_Spike(), depth=BACEDepth.FAST)
    assert out["bace_depth"] == 1
    assert out["attribution"]["confidence"] == "HIGH"


def test_bace_standard_uses_rce_with_zero_debate(monkeypatch):
    def _fake_rce(*args, **kwargs):
        assert kwargs["debate_rounds"] == 0
        return {"spike_id": 1, "attribution": {"confidence": "MEDIUM"}, "debate_rounds": 0}

    monkeypatch.setattr("core.bace_debate.attribute_spike_rce", _fake_rce)
    out = attribute_spike(_Spike(), depth=BACEDepth.STANDARD)
    assert out["bace_depth"] == 2
    assert out["bace_metadata"]["debate_rounds"] == 0
