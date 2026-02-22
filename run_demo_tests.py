#!/usr/bin/env python3
"""Run causal v2 tests for demo deck."""

import json
import subprocess
import sys
import os
import logging
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from pythia_live.causal_v2 import attribute_spike_v2

logging.basicConfig(level=logging.INFO)

@dataclass
class MockSpike:
    id: int = 1
    market_id: str = "test"
    market_title: str = ""
    timestamp: str = ""
    direction: str = "up"
    magnitude: float = 0.15
    price_before: float = 0.40
    price_after: float = 0.55
    volume_at_spike: float = 75000
    asset_class: str = ""
    attributed_events: list = field(default_factory=list)
    manual_tag: str = ""
    asset_reaction: dict = field(default_factory=dict)

def llm_call(prompt, model="sonnet"):
    """Call Claude via CLI."""
    result = subprocess.run(
        ["claude", "--print", "--model", model, "-p", prompt],
        capture_output=True, text=True, timeout=120
    )
    return result.stdout.strip()

def sonnet_call(prompt):
    return llm_call(prompt, "sonnet")

def opus_call(prompt):
    return llm_call(prompt, "sonnet")  # Use sonnet for speed in demo

TESTS = [
    {
        "title": "Will the Supreme Court block Trump tariffs?",
        "timestamp": "2026-02-21T11:00:00",
        "direction": "up",
        "magnitude": 0.18,
        "price_before": 0.25,
        "price_after": 0.43,
        "volume": 120000,
    },
    {
        "title": "Will the Fed cut rates in March 2025?",
        "timestamp": "2025-01-29T19:00:00",
        "direction": "down",
        "magnitude": 0.12,
        "price_before": 0.35,
        "price_after": 0.23,
        "volume": 85000,
    },
    {
        "title": "Will Bitcoin exceed $100,000 by March 2025?",
        "timestamp": "2025-01-20T14:00:00",
        "direction": "up",
        "magnitude": 0.20,
        "price_before": 0.55,
        "price_after": 0.75,
        "volume": 200000,
    },
    {
        "title": "Will there be a Ukraine ceasefire agreement by June 2025?",
        "timestamp": "2025-02-15T10:00:00",
        "direction": "up",
        "magnitude": 0.10,
        "price_before": 0.15,
        "price_after": 0.25,
        "volume": 45000,
    },
]

results = {}
for i, t in enumerate(TESTS):
    print(f"\n{'='*60}")
    print(f"TEST {i+1}: {t['title']}")
    print(f"{'='*60}")
    
    spike = MockSpike(
        id=i+1,
        market_title=t["title"],
        timestamp=t["timestamp"],
        direction=t["direction"],
        magnitude=t["magnitude"],
        price_before=t["price_before"],
        price_after=t["price_after"],
        volume_at_spike=t["volume"],
    )
    
    result = attribute_spike_v2(
        spike,
        entity_llm=sonnet_call,
        filter_llm=sonnet_call,
        reasoning_llm=opus_call,
    )
    
    # Remove raw_reasoning to keep output manageable
    if "raw_reasoning" in result.get("attribution", {}):
        del result["attribution"]["raw_reasoning"]
    
    results[t["title"]] = result
    
    print(f"\nCandidates: {result['candidates_retrieved']} retrieved → {result['candidates_filtered']} filtered")
    print(f"Attribution: {result['attribution'].get('most_likely_cause', 'N/A')}")
    print(f"Confidence: {result['attribution'].get('confidence', 'N/A')}")
    print(f"Causal chain: {result['attribution'].get('causal_chain', 'N/A')}")

# Save all results
output_path = os.path.join(os.path.dirname(__file__), "demo_test_results.json")
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n\nAll results saved to {output_path}")
