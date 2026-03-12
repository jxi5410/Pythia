"""Spike context builder extracted from causal_v2."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List

from .market_classifier import classify_market, extract_entities_llm


def _parse_naive(ts) -> datetime:
    """Parse a timestamp string to a naive (UTC) datetime.

    Handles: ISO with Z, ISO with +00:00, naive ISO, already-datetime.
    Always returns a naive datetime to avoid tz-aware vs tz-naive comparison errors.
    """
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    if isinstance(ts, str):
        ts = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        return dt.replace(tzinfo=None)
    return ts


def find_concurrent_spikes(target_spike, all_spikes, window_hours: float = 2.0) -> List[Dict]:
    """Find other spikes that occurred within the time window."""
    concurrent = []
    target_ts = _parse_naive(target_spike.timestamp)

    for spike in all_spikes:
        if spike.market_id == target_spike.market_id:
            continue
        spike_ts = _parse_naive(spike.timestamp)
        diff = abs((spike_ts - target_ts).total_seconds())
        if diff <= window_hours * 3600:
            concurrent.append({
                "market_title": spike.market_title[:60],
                "direction": spike.direction,
                "magnitude": spike.magnitude,
                "time_diff_min": int(diff / 60),
            })
    return concurrent


def build_spike_context(spike, all_recent_spikes=None, entity_llm=None) -> Dict:
    """Build full context for a spike before attribution."""
    ts = _parse_naive(spike.timestamp)

    correlated = find_concurrent_spikes(spike, all_recent_spikes or [], window_hours=2)
    entities = extract_entities_llm(spike.market_title, llm_call=entity_llm)

    return {
        "market_title": spike.market_title,
        "category": classify_market(spike.market_title, llm_call=entity_llm),
        "entities": entities,
        "spike": {
            "direction": spike.direction,
            "magnitude": spike.magnitude,
            "timestamp": ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
            "price_before": spike.price_before,
            "price_after": spike.price_after,
            "volume": spike.volume_at_spike,
        },
        "temporal_window": {
            "start": (ts - timedelta(hours=6)).isoformat(),
            "end": (ts + timedelta(hours=1)).isoformat(),
        },
        "correlated_spikes": correlated,
        "is_macro": len(correlated) >= 2,
    }
