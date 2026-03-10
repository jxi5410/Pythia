#!/usr/bin/env python3
"""
Pythia Query Interface — CLI tool for institutional traders.

Query historical spikes by category, magnitude, asset class.
Find similar events and their attributed causes.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from pythia_live.database import PythiaDB
from pythia_live.spike_archive import get_spike_history, SpikeEvent
from pythia_live.patterns import build_patterns, find_matching_pattern, _categorize_market


def format_spike(spike: SpikeEvent, detailed: bool = False) -> str:
    """Format a spike for display."""
    lines = []
    lines.append(f"  ID: {spike.id}")
    lines.append(f"  Market: {spike.market_title[:60]}...")
    lines.append(f"  Time: {spike.timestamp.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"  Move: {spike.direction.upper()} {spike.magnitude:.1%}")
    lines.append(f"  Price: {spike.price_before:.2f} → {spike.price_after:.2f}")
    lines.append(f"  Volume: {spike.volume_at_spike:,.0f}")
    
    if spike.asset_class:
        lines.append(f"  Asset Class: {spike.asset_class}")
    
    if detailed and spike.attributed_events:
        lines.append("  Attributed Causes:")
        for i, evt in enumerate(spike.attributed_events[:3], 1):
            headline = evt.get('headline', 'Unknown')[:70]
            source = evt.get('source', 'unknown')
            lines.append(f"    {i}. {headline}... ({source})")
    
    if spike.manual_tag:
        lines.append(f"  Manual Tag: {spike.manual_tag}")
    
    return '\n'.join(lines)


def query_fed_rate(db: PythiaDB, min_magnitude: float = 0.05):
    """Query Fed rate related spikes."""
    print(f"\n{'='*60}")
    print(f"FED RATE SPIKES (≥{min_magnitude:.0%} magnitude)")
    print('='*60)
    
    # Get all spikes and filter by category
    spikes = get_spike_history(db, min_magnitude=min_magnitude, limit=200)
    fed_spikes = [s for s in spikes if _categorize_market(s.market_title) == 'fed_rate']
    
    if not fed_spikes:
        print("No Fed rate spikes found.")
        return
    
    print(f"\nFound {len(fed_spikes)} Fed-related spike(s):\n")
    
    for spike in fed_spikes:
        print(format_spike(spike, detailed=True))
        print()
    
    # Summary stats
    avg_magnitude = sum(s.magnitude for s in fed_spikes) / len(fed_spikes)
    up_count = sum(1 for s in fed_spikes if s.direction == 'up')
    down_count = len(fed_spikes) - up_count
    
    print(f"Summary:")
    print(f"  Total spikes: {len(fed_spikes)}")
    print(f"  Avg magnitude: {avg_magnitude:.1%}")
    print(f"  Direction: {up_count} UP, {down_count} DOWN")


def query_similar(db: PythiaDB, market_title: str, direction: str = None, limit: int = 10):
    """Find spikes similar to a given market title."""
    print(f"\n{'='*60}")
    print(f"SPIKES SIMILAR TO: {market_title}")
    print('='*60)
    
    category = _categorize_market(market_title)
    print(f"Category detected: {category}\n")
    
    # Get all spikes in this category
    spikes = get_spike_history(db, min_magnitude=0.03, limit=300)
    similar = [s for s in spikes if _categorize_market(s.market_title) == category]
    
    if direction:
        similar = [s for s in similar if s.direction == direction]
    
    if not similar:
        print(f"No similar spikes found in category '{category}'.")
        return
    
    print(f"Found {len(similar)} similar spike(s):\n")
    
    for spike in similar[:limit]:
        print(format_spike(spike, detailed=True))
        print()


def query_what_caused(db: PythiaDB, spike_id: int = None, market_id: str = None):
    """Show what caused a specific spike."""
    print(f"\n{'='*60}")
    print("WHAT CAUSED THIS SPIKE?")
    print('='*60)
    
    spikes = get_spike_history(db, market_id=market_id, min_magnitude=0.01, limit=50)
    
    if spike_id:
        spike = next((s for s in spikes if s.id == spike_id), None)
    else:
        # Get most recent spike for this market
        spike = spikes[0] if spikes else None
    
    if not spike:
        print("Spike not found.")
        return
    
    print(format_spike(spike, detailed=True))
    print()
    
    if spike.attributed_events:
        print("Attribution Results:")
        for i, evt in enumerate(spike.attributed_events, 1):
            print(f"\n  {i}. {evt.get('headline', 'Unknown')}")
            print(f"     Source: {evt.get('source', 'unknown')}")
            url = evt.get('url', '')
            if url:
                print(f"     URL: {url[:80]}...")
    else:
        print("No attribution data available.")
        print("(Attribution requires active news search at time of spike)")


def query_patterns(db: PythiaDB):
    """Show all discovered causal patterns."""
    print(f"\n{'='*60}")
    print("CAUSAL PATTERNS DISCOVERED")
    print('='*60)
    
    patterns = build_patterns(db)
    
    if not patterns:
        print("No patterns found. Need more spike data.")
        return
    
    print(f"\nFound {len(patterns)} pattern(s):\n")
    
    for p in patterns[:15]:  # Top 15
        confidence_label = 'HIGH' if p.confidence >= 0.7 else 'MED' if p.confidence >= 0.5 else 'LOW'
        
        print(f"Pattern: {p.market_category} / {p.direction.upper()}")
        print(f"  Asset Class: {p.asset_class or 'Any'}")
        print(f"  Sample Size: {p.sample_size}")
        print(f"  Avg Magnitude: {p.avg_magnitude:.1%}")
        print(f"  Typical Cause: {p.typical_cause or 'Unknown'}")
        print(f"  Confidence: {confidence_label} ({p.confidence:.0%})")
        if p.avg_asset_reaction:
            sign = '+' if p.avg_asset_reaction > 0 else ''
            print(f"  Avg Asset Reaction: {sign}{p.avg_asset_reaction:.1%}")
        print()


def query_correlations(db: PythiaDB, market_id: str):
    """Show correlated market movements for a given spike."""
    print(f"\n{'='*60}")
    print(f"CORRELATED MOVEMENTS: {market_id}")
    print('='*60)
    
    # Get the spike
    spikes = get_spike_history(db, market_id=market_id, min_magnitude=0.03, limit=1)
    if not spikes:
        print("No spike found for this market.")
        return
    
    spike = spikes[0]
    print(f"\nReference Spike:")
    print(format_spike(spike))
    print()
    
    # Find other spikes around the same time
    spike_time = spike.timestamp
    all_spikes = get_spike_history(db, min_magnitude=0.03, limit=100)
    
    # Spikes within 2 hours
    from datetime import timedelta
    correlated = []
    for s in all_spikes:
        if s.id == spike.id:
            continue
        time_diff = abs((s.timestamp - spike_time).total_seconds())
        if time_diff <= 7200:  # 2 hours
            correlated.append((s, time_diff))
    
    if correlated:
        print(f"Correlated Spikes (within 2 hours):\n")
        for s, diff in sorted(correlated, key=lambda x: x[1]):
            mins = int(diff / 60)
            print(f"  [{mins:+d} min] {s.market_title[:50]}...")
            print(f"           {s.direction.upper()} {s.magnitude:.1%}")
            print()
    else:
        print("No correlated spikes found within 2-hour window.")


def main():
    parser = argparse.ArgumentParser(
        description='Pythia Query Interface — Query historical prediction market spikes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pythia_query.py --fed                          # Show all Fed rate spikes
  python pythia_query.py --similar "Bitcoin"            # Find similar BTC spikes
  python pythia_query.py --what-caused --id 42          # Show what caused spike #42
  python pythia_query.py --patterns                     # Show all discovered patterns
  python pythia_query.py --correlations 0xabc...        # Show correlated movements
        """
    )
    
    parser.add_argument('--fed', action='store_true', help='Query Fed rate related spikes')
    parser.add_argument('--similar', type=str, metavar='MARKET', help='Find spikes similar to this market')
    parser.add_argument('--direction', choices=['up', 'down'], help='Filter by direction')
    parser.add_argument('--what-caused', action='store_true', help='Show what caused a spike')
    parser.add_argument('--id', type=int, help='Spike ID for --what-caused')
    parser.add_argument('--market-id', type=str, help='Market ID for --what-caused or --correlations')
    parser.add_argument('--patterns', action='store_true', help='Show all causal patterns')
    parser.add_argument('--correlations', type=str, metavar='MARKET_ID', help='Show correlated movements')
    parser.add_argument('--min-magnitude', type=float, default=0.05, help='Minimum spike magnitude (default: 0.05)')
    parser.add_argument('--limit', type=int, default=10, help='Result limit for --similar (default: 10)')
    parser.add_argument('--db', default='data/pythia_live.db', help='Database path')
    
    args = parser.parse_args()
    
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        print("Run Pythia Live first to collect data.")
        sys.exit(1)
    
    db = PythiaDB(str(db_path))
    
    if args.fed:
        query_fed_rate(db, args.min_magnitude)
    elif args.similar:
        query_similar(db, args.similar, args.direction, args.limit)
    elif args.what_caused:
        query_what_caused(db, args.id, args.market_id)
    elif args.patterns:
        query_patterns(db)
    elif args.correlations:
        query_correlations(db, args.correlations)
    else:
        parser.print_help()
        print("\nRun with --patterns to see what Pythia has discovered so far.")


if __name__ == "__main__":
    main()
