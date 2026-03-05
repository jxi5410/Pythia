#!/usr/bin/env python3
"""
Pythia Pattern Library Builder
Extracts signal signatures from Becker backtest data
Identifies patterns that predict price movements
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json
from datetime import datetime
from collections import defaultdict

BACKTEST_RESULTS = "/Users/xj.ai/.openclaw/workspace/pythia_backtest_results.json"
PATTERN_LIBRARY = "/Users/xj.ai/.openclaw/workspace/pythia_pattern_library.json"

class PatternExtractor:
    def __init__(self):
        self.spikes = None
        self.patterns = {
            'velocity_signatures': [],
            'time_of_day': defaultdict(list),
            'platform_behavior': defaultdict(list),
            'momentum_clusters': []
        }
        
    def load_backtest_data(self):
        """Load the backtest results."""
        print("📊 Loading backtest results...")
        with open(BACKTEST_RESULTS, 'r') as f:
            data = json.load(f)
        
        self.spikes = pd.DataFrame(data['all_spikes'])
        print(f"✅ Loaded {len(self.spikes)} spikes")
        return self
    
    def extract_velocity_signatures(self):
        """Find spikes with characteristic velocity patterns."""
        print("\n🔍 Extracting velocity signatures...")
        
        # Categorize by velocity buckets
        velocity_buckets = {
            'low': (0, 25),
            'medium': (25, 75),
            'high': (75, 200),
            'extreme': (200, float('inf'))
        }
        
        for bucket, (low, high) in velocity_buckets.items():
            bucket_spikes = self.spikes[
                (self.spikes['spike_velocity'] >= low) & 
                (self.spikes['spike_velocity'] < high)
            ]
            
            if len(bucket_spikes) > 0:
                signature = {
                    'name': f'velocity_{bucket}',
                    'velocity_range': [low, high],
                    'count': len(bucket_spikes),
                    'avg_change': bucket_spikes['change_pct'].mean(),
                    'avg_volume': bucket_spikes['volume'].mean(),
                    'direction_bias': bucket_spikes['direction'].value_counts().to_dict(),
                    'peak_hours': self._get_peak_hours(bucket_spikes),
                    'example_markets': bucket_spikes['market_id'].unique()[:5].tolist()
                }
                self.patterns['velocity_signatures'].append(signature)
                print(f"  {bucket}: {len(bucket_spikes)} spikes, avg change {signature['avg_change']:.1f}%")
        
        return self
    
    def extract_time_patterns(self):
        """Analyze time-of-day effects."""
        print("\n⏰ Analyzing time patterns...")
        
        self.spikes['hour'] = pd.to_datetime(self.spikes['timestamp']).dt.hour
        
        for hour in range(24):
            hour_spikes = self.spikes[self.spikes['hour'] == hour]
            if len(hour_spikes) > 1000:  # Only significant hours
                self.patterns['time_of_day'][str(hour)] = {
                    'count': len(hour_spikes),
                    'avg_velocity': hour_spikes['spike_velocity'].mean(),
                    'avg_change': hour_spikes['change_pct'].mean(),
                    'direction': hour_spikes['direction'].value_counts().to_dict()
                }
        
        # Find peak hours
        hourly_counts = self.spikes.groupby('hour').size()
        peak_hours = hourly_counts.nlargest(5)
        print(f"  Peak hours: {', '.join([f'{h}:00 ({c})' for h, c in peak_hours.items()])}")
        
        return self
    
    def extract_platform_patterns(self):
        """Analyze platform-specific behavior."""
        print("\n📈 Analyzing platform patterns...")
        
        for platform in self.spikes['platform'].unique():
            platform_spikes = self.spikes[self.spikes['platform'] == platform]
            
            self.patterns['platform_behavior'][platform] = {
                'total_spikes': len(platform_spikes),
                'avg_velocity': platform_spikes['spike_velocity'].mean(),
                'avg_change': platform_spikes['change_pct'].mean(),
                'direction_bias': platform_spikes['direction'].value_counts().to_dict(),
                'velocity_distribution': {
                    'p50': platform_spikes['spike_velocity'].median(),
                    'p90': platform_spikes['spike_velocity'].quantile(0.9),
                    'p99': platform_spikes['spike_velocity'].quantile(0.99)
                }
            }
            
            pb = self.patterns['platform_behavior'][platform]
            print(f"  {platform}: {pb['total_spikes']} spikes, v90={pb['velocity_distribution']['p90']:.1f}")
        
        return self
    
    def find_momentum_clusters(self):
        """Find clusters of related market movements."""
        print("\n🎯 Finding momentum clusters...")
        
        # Group by time window (5 minutes)
        self.spikes['time_window'] = pd.to_datetime(self.spikes['timestamp']).dt.floor('5min')
        
        # Find windows with multiple spikes
        window_counts = self.spikes.groupby('time_window').size()
        busy_windows = window_counts[window_counts >= 5].index
        
        for window in busy_windows[:10]:  # Top 10 busy windows
            window_spikes = self.spikes[self.spikes['time_window'] == window]
            
            cluster = {
                'timestamp': str(window),
                'spike_count': len(window_spikes),
                'platforms': window_spikes['platform'].unique().tolist(),
                'avg_velocity': window_spikes['spike_velocity'].mean(),
                'direction_consensus': window_spikes['direction'].mode().iloc[0] if len(window_spikes) > 0 else None,
                'markets': window_spikes['market_id'].unique()[:5].tolist()
            }
            self.patterns['momentum_clusters'].append(cluster)
        
        print(f"  Found {len(self.patterns['momentum_clusters'])} momentum clusters")
        return self
    
    def _get_peak_hours(self, df):
        """Get peak hours for a subset of spikes."""
        if 'hour' not in df.columns:
            df = df.copy()
            df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        peak = df.groupby('hour').size().idxmax()
        return int(peak)
    
    def generate_trading_signals(self):
        """Generate actionable trading signals from patterns."""
        print("\n📋 Generating trading signals...")
        
        signals = []
        
        # Signal 1: High velocity + evening hours
        evening_high_v = self.spikes[
            (self.spikes['hour'].isin([18, 19, 20])) &
            (self.spikes['spike_velocity'] > 100)
        ]
        if len(evening_high_v) > 100:
            signals.append({
                'name': 'evening_momentum_burst',
                'condition': 'velocity > 100 AND hour in [18,19,20]',
                'count': len(evening_high_v),
                'success_rate': (evening_high_v['direction'] == 'up').mean() * 100,
                'avg_change': evening_high_v['change_pct'].mean()
            })
        
        # Signal 2: Extreme spikes (potential reversal)
        extreme = self.spikes[self.spikes['change_pct'] > 50]
        if len(extreme) > 10:
            signals.append({
                'name': 'extreme_spike_reversal',
                'condition': 'change_pct > 50%',
                'count': len(extreme),
                'note': 'Often followed by mean reversion — potential fade opportunity'
            })
        
        self.patterns['trading_signals'] = signals
        
        for sig in signals:
            print(f"  {sig['name']}: {sig['count']} occurrences")
        
        return self
    
    def save_pattern_library(self):
        """Save the pattern library to disk."""
        library = {
            'generated_at': datetime.now().isoformat(),
            'total_spikes_analyzed': len(self.spikes),
            'patterns': self.patterns
        }
        
        with open(PATTERN_LIBRARY, 'w') as f:
            json.dump(library, f, indent=2, default=str)
        
        print(f"\n✅ Pattern library saved to: {PATTERN_LIBRARY}")
        print(f"   Total patterns: {len(self.patterns['velocity_signatures'])} velocity + {len(self.patterns['momentum_clusters'])} clusters")
        
        return self
    
    def run(self):
        """Execute full pattern extraction pipeline."""
        print("=" * 60)
        print("🧠 PYTHIA PATTERN LIBRARY BUILDER")
        print("=" * 60)
        
        self.load_backtest_data()
        self.extract_velocity_signatures()
        self.extract_time_patterns()
        self.extract_platform_patterns()
        self.find_momentum_clusters()
        self.generate_trading_signals()
        self.save_pattern_library()
        
        print("\n" + "=" * 60)
        print("✅ Pattern extraction complete")
        print("=" * 60)


if __name__ == "__main__":
    extractor = PatternExtractor()
    extractor.run()
