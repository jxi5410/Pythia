#!/usr/bin/env python3
"""
Test the full causal v2 pipeline with LLM integration.
"""
import sys
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from pythia_live.causal_v2 import attribute_spike_v2
from pythia_live.llm_integration import sonnet_call, opus_call


@dataclass
class MockSpike:
    id: int = 1
    market_id: str = "test"
    market_title: str = ""
    timestamp: str = ""
    direction: str = "up"
    magnitude: float = 0.12
    price_before: float = 0.45
    price_after: float = 0.57
    volume_at_spike: float = 50000
    asset_class: str = ""
    attributed_events: list = field(default_factory=list)
    manual_tag: str = ""
    asset_reaction: dict = field(default_factory=dict)


def test_full_pipeline(market_title: str, direction: str = "up", magnitude: float = 0.12):
    spike = MockSpike(
        market_title=market_title,
        timestamp=datetime.utcnow().isoformat(),
        direction=direction,
        magnitude=magnitude,
        price_before=0.45,
        price_after=0.45 + magnitude if direction == "up" else 0.45 - magnitude,
    )

    print(f"{'='*60}")
    print(f"MARKET: {market_title}")
    print(f"SPIKE: {direction.upper()} {magnitude:.1%}")
    print(f"{'='*60}")

    result = attribute_spike_v2(
        spike,
        all_recent_spikes=[],
        filter_llm=sonnet_call,
        reasoning_llm=opus_call,
    )

    print(f"\nCandidates retrieved: {result['candidates_retrieved']}")
    print(f"Candidates after filter: {result['candidates_filtered']}")

    if result["top_candidates"]:
        print(f"\nTop candidates (filtered by Sonnet):")
        for c in result["top_candidates"][:3]:
            score = c.get("relevance_score", "?")
            reason = c.get("relevance_reason", "")
            print(f"  [{score}/10] {c['headline'][:70]}")
            if reason:
                print(f"          {reason}")

    attr = result["attribution"]
    print(f"\n{'='*60}")
    print(f"ATTRIBUTION (by Opus):")
    print(f"{'='*60}")
    print(f"Cause: {attr.get('most_likely_cause', 'N/A')}")
    print(f"Chain: {attr.get('causal_chain', 'N/A')}")
    print(f"Confidence: {attr.get('confidence', 'N/A')}")
    print(f"  Reasoning: {attr.get('confidence_reasoning', 'N/A')}")
    print(f"Macro/Idio: {attr.get('macro_or_idiosyncratic', 'N/A')}")
    print(f"Duration: {attr.get('expected_duration', 'N/A')}")
    print(f"Trading: {attr.get('trading_implication', 'N/A')}")

    alts = attr.get("alternative_explanations", [])
    if alts:
        print(f"Alternatives: {', '.join(alts[:3])}")

    return result


if __name__ == "__main__":
    market = sys.argv[1] if len(sys.argv) > 1 else "Will the Fed cut rates by June 2025?"
    test_full_pipeline(market)
