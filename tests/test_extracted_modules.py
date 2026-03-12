import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.feedback import get_feedback_summary, load_feedback_corrections, log_feedback
from core.market_classifier import classify_market, extract_entities_llm, extract_entities_simple
from core.spike_context import build_spike_context, find_concurrent_spikes


class _Spike:
    def __init__(self, market_id="m1", title="Will Fed cut rates?", ts="2026-01-01T00:00:00"):
        self.market_id = market_id
        self.market_title = title
        self.timestamp = ts
        self.direction = "up"
        self.magnitude = 0.1
        self.price_before = 0.4
        self.price_after = 0.5
        self.volume_at_spike = 1000


def test_market_classifier_and_context_builder():
    cat = classify_market("Will the Fed cut rates by June?")
    assert cat in ("fed_rate", "general")

    ents = extract_entities_simple("Will the Fed cut rates by June?")
    assert isinstance(ents, list)
    assert ents

    ents_llm = extract_entities_llm("Will the Fed cut rates by June?", llm_call=None)
    assert isinstance(ents_llm, list)

    s1 = _Spike()
    s2 = _Spike(market_id="m2", title="Bitcoin above 100k?", ts="2026-01-01T00:30:00")
    conc = find_concurrent_spikes(s1, [s2], window_hours=2)
    assert len(conc) == 1

    ctx = build_spike_context(s1, [s2], entity_llm=None)
    assert ctx["category"]
    assert "temporal_window" in ctx


def test_feedback_module_smoke(tmp_path, monkeypatch):
    target = tmp_path / "causal_feedback.jsonl"
    monkeypatch.setattr("core.feedback.FEEDBACK_FILE", str(target))

    log_feedback(1, "wrong", "bad cause")
    rows = load_feedback_corrections()
    assert len(rows) == 1
    summary = get_feedback_summary()
    assert "Spike #1" in summary
