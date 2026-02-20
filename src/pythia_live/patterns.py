"""
Pattern Library — Builds and queries causal patterns from historical spikes.
Groups spike events by category and direction to discover recurring patterns.
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .database import PythiaDB
from .detector import Signal
from .spike_archive import get_spike_history, SpikeEvent

logger = logging.getLogger(__name__)


@dataclass
class CausalPattern:
    pattern_id: str  # hash of key fields
    market_category: str  # e.g., "fed_rate", "election", "trade_war"
    asset_class: str
    direction: str
    avg_magnitude: float
    sample_size: int
    typical_cause: str  # most common attributed event type
    historical_spikes: List[int] = field(default_factory=list)  # spike IDs
    # What happened after
    avg_asset_reaction: float = 0.0  # average subsequent asset move
    avg_reaction_timeframe_hours: float = 0.0
    confidence: float = 0.0  # based on sample_size and consistency


def _categorize_market(title: str) -> str:
    """Categorize a market title into a broad category for pattern grouping."""
    title_lower = title.lower()

    categories = {
        'fed_rate': ['fed', 'fomc', 'rate cut', 'rate hike', 'interest rate', 'monetary policy'],
        'inflation': ['inflation', 'cpi', 'pce', 'core inflation'],
        'election': ['election', 'president', 'vote', 'ballot', 'primary', 'nominee'],
        'trade_war': ['tariff', 'trade war', 'sanctions', 'import duty'],
        'recession': ['recession', 'gdp', 'unemployment', 'jobs report', 'nonfarm'],
        'crypto': ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto'],
        'geopolitical': ['war', 'conflict', 'invasion', 'military', 'nuclear', 'nato'],
        'tech': ['ai', 'tech', 'regulation', 'antitrust', 'big tech'],
        'energy': ['oil', 'opec', 'gas', 'energy', 'crude'],
    }

    for category, keywords in categories.items():
        if any(kw in title_lower for kw in keywords):
            return category

    return 'general'


def _compute_pattern_id(market_category: str, asset_class: str, direction: str) -> str:
    """Generate a deterministic hash ID for a pattern."""
    key = f"{market_category}|{asset_class}|{direction}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def build_patterns(db: PythiaDB) -> List[CausalPattern]:
    """
    Build causal patterns by grouping spikes by market category + direction.

    Calculates average magnitude, common causes, and asset reactions.
    Returns patterns sorted by confidence (descending).
    """
    spikes = get_spike_history(db, min_magnitude=0.03, limit=500)

    if not spikes:
        return []

    # Group spikes by (market_category, asset_class, direction)
    groups: Dict[str, List[SpikeEvent]] = {}
    for spike in spikes:
        category = _categorize_market(spike.market_title)
        key = f"{category}|{spike.asset_class}|{spike.direction}"
        groups.setdefault(key, []).append(spike)

    patterns = []
    for key, group_spikes in groups.items():
        parts = key.split('|')
        market_category = parts[0]
        asset_class = parts[1] if len(parts) > 1 else ''
        direction = parts[2] if len(parts) > 2 else ''

        sample_size = len(group_spikes)
        avg_magnitude = sum(s.magnitude for s in group_spikes) / sample_size

        # Find most common attributed cause
        cause_counts: Dict[str, int] = {}
        for s in group_spikes:
            for evt in s.attributed_events:
                headline = evt.get('headline', '')[:80]
                if headline:
                    # Group by source domain as a proxy for cause type
                    source = evt.get('source', 'unknown')
                    cause_counts[source] = cause_counts.get(source, 0) + 1
            if s.manual_tag:
                cause_counts[s.manual_tag] = cause_counts.get(s.manual_tag, 0) + 1

        typical_cause = max(cause_counts, key=cause_counts.get) if cause_counts else ''

        # Average asset reaction (from spikes that have reaction data)
        reactions = [s.asset_reaction for s in group_spikes if s.asset_reaction]
        avg_reaction = 0.0
        avg_timeframe = 0.0
        if reactions:
            magnitudes = [r.get('magnitude', 0) for r in reactions]
            timeframes = [r.get('timeframe', 0) for r in reactions]
            avg_reaction = sum(magnitudes) / len(magnitudes)
            avg_timeframe = sum(timeframes) / len(timeframes) if timeframes else 0

        # Confidence: based on sample size and consistency of magnitudes
        if sample_size >= 10:
            confidence = 0.9
        elif sample_size >= 5:
            confidence = 0.7
        elif sample_size >= 3:
            confidence = 0.5
        else:
            confidence = 0.3

        # Reduce confidence if magnitudes are very inconsistent
        if sample_size >= 2:
            magnitudes = [s.magnitude for s in group_spikes]
            mean_mag = sum(magnitudes) / len(magnitudes)
            variance = sum((m - mean_mag) ** 2 for m in magnitudes) / len(magnitudes)
            cv = (variance ** 0.5) / mean_mag if mean_mag > 0 else 1
            if cv > 0.5:
                confidence *= 0.8  # High variance reduces confidence

        pattern_id = _compute_pattern_id(market_category, asset_class, direction)

        patterns.append(CausalPattern(
            pattern_id=pattern_id,
            market_category=market_category,
            asset_class=asset_class,
            direction=direction,
            avg_magnitude=avg_magnitude,
            sample_size=sample_size,
            typical_cause=typical_cause,
            historical_spikes=[s.id for s in group_spikes],
            avg_asset_reaction=avg_reaction,
            avg_reaction_timeframe_hours=avg_timeframe,
            confidence=confidence,
        ))

    # Sort by confidence descending
    patterns.sort(key=lambda p: p.confidence, reverse=True)
    return patterns


def find_matching_pattern(patterns: List[CausalPattern], signal: Signal) -> Optional[CausalPattern]:
    """
    Given a live signal, find the best matching historical pattern.

    Match on: asset_class + direction + similar magnitude range.
    """
    if not patterns:
        return None

    signal_direction = ''
    if signal.old_price is not None and signal.new_price is not None:
        signal_direction = 'up' if signal.new_price > signal.old_price else 'down'

    signal_magnitude = abs((signal.new_price or 0) - (signal.old_price or 0))
    signal_asset = getattr(signal, 'asset_class', '')

    best_match = None
    best_score = 0.0

    for pattern in patterns:
        score = 0.0

        # Asset class match
        if pattern.asset_class and pattern.asset_class == signal_asset:
            score += 3.0

        # Direction match
        if pattern.direction and pattern.direction == signal_direction:
            score += 2.0

        # Magnitude similarity (within 2x range)
        if pattern.avg_magnitude > 0 and signal_magnitude > 0:
            ratio = signal_magnitude / pattern.avg_magnitude
            if 0.5 <= ratio <= 2.0:
                score += 1.0
                # Bonus for closer match
                score += 1.0 - abs(1.0 - ratio)

        # Confidence boost
        score *= pattern.confidence

        if score > best_score:
            best_score = score
            best_match = pattern

    # Minimum score threshold
    if best_score < 1.0:
        return None

    return best_match


def format_pattern_insight(pattern: CausalPattern, signal: Signal) -> str:
    """
    Format a human-readable insight for an alert.

    Example: "Similar spike seen 7 times (fed_rate/up). Avg move: 8.2%.
    Typical cause: reuters.com. Avg asset reaction: +2.1% within 24h."
    """
    parts = []

    parts.append(
        f"Similar {pattern.direction} spike seen {pattern.sample_size}x "
        f"in {pattern.market_category} markets"
    )

    parts.append(f"Avg move: {pattern.avg_magnitude:.1%}")

    if pattern.typical_cause:
        parts.append(f"Typical cause: {pattern.typical_cause}")

    if pattern.avg_asset_reaction:
        sign = '+' if pattern.avg_asset_reaction > 0 else ''
        timeframe = f"{pattern.avg_reaction_timeframe_hours:.0f}h" if pattern.avg_reaction_timeframe_hours else '?'
        parts.append(
            f"Avg reaction: {sign}{pattern.avg_asset_reaction:.1%} within {timeframe}"
        )

    confidence_label = 'high' if pattern.confidence >= 0.7 else 'moderate' if pattern.confidence >= 0.5 else 'low'
    parts.append(f"Confidence: {confidence_label} ({pattern.sample_size} samples)")

    return '. '.join(parts) + '.'
