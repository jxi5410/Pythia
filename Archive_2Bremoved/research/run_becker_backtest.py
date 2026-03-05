#!/usr/bin/env python3
"""
Full Backtest: Validate Pythia's signal detection against Becker's historical data
Scans 50GB of prediction market trades to find price spikes and validate detection logic.
"""

import sys
sys.path.insert(0, '/Users/xj.ai/.openclaw/workspace/Pythia.sim/src')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import json
from collections import defaultdict

# Configuration
DATA_PATH = "/Volumes/PythiaData/becker_prediction_markets/data"
SPIKE_THRESHOLD = 0.10  # 10% price move
MIN_VOLUME = 1000  # Minimum trades to consider
OUTPUT_FILE = "/Users/xj.ai/.openclaw/workspace/pythia_backtest_results.json"
PROGRESS_FILE = "/Users/xj.ai/.openclaw/workspace/pythia_backtest_progress.txt"

class PythiaBacktester:
    def __init__(self):
        self.spikes_found = []
        self.markets_analyzed = 0
        self.total_trades = 0
        self.start_time = datetime.now()
        
    def log_progress(self, message):
        """Log progress to file for monitoring."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(PROGRESS_FILE, 'a') as f:
            f.write(f"[{timestamp}] {message}\n")
        print(f"[{timestamp}] {message}")
        
    def load_market_metadata(self, platform="kalshi"):
        """Load market info to enrich spike data."""
        markets_dir = Path(DATA_PATH) / platform / "markets"
        parquet_files = sorted(markets_dir.glob("*.parquet"))
        
        if not parquet_files:
            return {}
            
        # Load first file as sample
        df = pd.read_parquet(parquet_files[0])
        
        # Build lookup dict
        if 'ticker' in df.columns:
            return dict(zip(df['ticker'], df['question'] if 'question' in df.columns else df.get('title', df['ticker'])))
        return {}
        
    def analyze_market(self, market_df, market_id, platform):
        """Analyze single market for spikes."""
        if len(market_df) < 10:
            return []
            
        # Sort by time
        if platform == "kalshi":
            time_col = 'created_time'
            price_col = 'yes_price'
        else:  # polymarket
            time_col = 'timestamp' if 'timestamp' in market_df.columns else '_fetched_at'
            price_col = 'price' if 'price' in market_df.columns else 'maker_amount'
            
        if time_col not in market_df.columns or price_col not in market_df.columns:
            return []
            
        market_df = market_df.sort_values(time_col)
        prices = market_df[price_col].values
        times = market_df[time_col].values
        
        spikes = []
        
        # Normalize prices to 0-1 range if needed
        if prices.max() > 1:
            prices = prices / prices.max()
            
        # Find spikes
        for i in range(1, len(prices)):
            prev_price = prices[i-1]
            curr_price = prices[i]
            
            if prev_price == 0:
                continue
                
            change = abs(curr_price - prev_price)
            change_pct = change / prev_price if prev_price > 0 else 0
            
            if change_pct >= SPIKE_THRESHOLD:
                # Determine direction
                direction = 'up' if curr_price > prev_price else 'down'
                
                # Calculate spike characteristics
                spike = {
                    'market_id': str(market_id),
                    'platform': platform,
                    'timestamp': str(times[i]),
                    'old_price': float(prev_price),
                    'new_price': float(curr_price),
                    'change_pct': float(change_pct),
                    'direction': direction,
                    'volume': len(market_df),
                    'spike_velocity': float(change_pct * 100),  # % per trade
                }
                
                spikes.append(spike)
                
        return spikes
        
    def run_full_backtest(self):
        """Main backtest loop."""
        self.log_progress("Starting full backtest...")
        self.log_progress(f"Data path: {DATA_PATH}")
        self.log_progress(f"Spike threshold: {SPIKE_THRESHOLD*100}%")
        
        all_spikes = []
        
        # Process both platforms
        for platform in ["kalshi", "polymarket"]:
            self.log_progress(f"\n=== Processing {platform.upper()} ===")
            
            trades_dir = Path(DATA_PATH) / platform / "trades"
            parquet_files = list(trades_dir.glob("*.parquet"))
            
            self.log_progress(f"Found {len(parquet_files)} trade files")
            
            # Load market metadata for enrichment
            market_lookup = self.load_market_metadata(platform)
            
            # Process files with progress tracking
            for i, file_path in enumerate(parquet_files):
                if i % 100 == 0:
                    progress = (i / len(parquet_files)) * 100
                    self.log_progress(f"  Progress: {i}/{len(parquet_files)} files ({progress:.1f}%)")
                    
                try:
                    df = pd.read_parquet(file_path)
                    self.total_trades += len(df)
                    
                    # Get market column
                    if platform == "kalshi":
                        market_col = 'ticker'
                    else:
                        market_col = 'market_id' if 'market_id' in df.columns else 'condition_id' if 'condition_id' in df.columns else None
                        
                    if not market_col or market_col not in df.columns:
                        continue
                        
                    # Group by market and analyze
                    for market_id, market_df in df.groupby(market_col):
                        spikes = self.analyze_market(market_df, market_id, platform)
                        
                        # Enrich with market title
                        for spike in spikes:
                            spike['market_title'] = market_lookup.get(market_id, 'Unknown')
                            
                        all_spikes.extend(spikes)
                        
                    self.markets_analyzed += df[market_col].nunique()
                    
                except Exception as e:
                    self.log_progress(f"  Error processing {file_path}: {e}")
                    continue
                    
        # Generate report
        self.generate_report(all_spikes)
        
    def generate_report(self, spikes):
        """Generate final backtest report."""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        self.log_progress(f"\n=== BACKTEST COMPLETE ===")
        self.log_progress(f"Duration: {duration/60:.1f} minutes")
        self.log_progress(f"Markets analyzed: {self.markets_analyzed}")
        self.log_progress(f"Total trades processed: {self.total_trades:,}")
        self.log_progress(f"Spikes detected: {len(spikes)}")
        
        if not spikes:
            self.log_progress("No spikes found!")
            return
            
        # Analysis
        df = pd.DataFrame(spikes)
        
        # By platform
        platform_stats = df.groupby('platform').agg({
            'change_pct': ['count', 'mean', 'max'],
            'spike_velocity': 'mean'
        }).round(3)
        
        self.log_progress(f"\n=== SPIKE STATISTICS ===")
        self.log_progress(f"By platform:\n{platform_stats}")
        
        # Top 10 largest spikes
        top_spikes = df.nlargest(10, 'change_pct')
        self.log_progress(f"\n=== TOP 10 SPIKES ===")
        for _, spike in top_spikes.iterrows():
            self.log_progress(f"  {spike['change_pct']*100:.1f}% | {spike['platform']} | {spike['market_title'][:50]}...")
            
        # Direction breakdown
        direction_counts = df['direction'].value_counts()
        self.log_progress(f"\n=== DIRECTION BREAKDOWN ===")
        self.log_progress(f"Up: {direction_counts.get('up', 0)}")
        self.log_progress(f"Down: {direction_counts.get('down', 0)}")
        
        # Time distribution (if timestamp parsing works)
        try:
            df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
            hour_dist = df['hour'].value_counts().sort_index()
            peak_hours = hour_dist.nlargest(3)
            self.log_progress(f"\n=== PEAK ACTIVITY HOURS ===")
            for hour, count in peak_hours.items():
                self.log_progress(f"  {hour}:00 - {count} spikes")
        except:
            pass
            
        # Save full results
        results = {
            'run_date': datetime.now().isoformat(),
            'duration_seconds': duration,
            'config': {
                'spike_threshold': SPIKE_THRESHOLD,
                'min_volume': MIN_VOLUME
            },
            'summary': {
                'markets_analyzed': self.markets_analyzed,
                'total_trades': self.total_trades,
                'spikes_detected': len(spikes)
            },
            'statistics': {
                'by_platform': platform_stats.to_dict(),
                'by_direction': direction_counts.to_dict()
            },
            'top_spikes': top_spikes.to_dict('records'),
            'all_spikes': spikes  # Full data
        }
        
        # Convert pandas objects to JSON-serializable format
        import pandas as pd
        
        def convert_to_serializable(obj):
            if isinstance(obj, pd.DataFrame):
                return obj.to_dict('records')
            elif isinstance(obj, pd.Series):
                return obj.to_dict()
            elif isinstance(obj, dict):
                return {str(k): convert_to_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            return obj
        
        results_serializable = convert_to_serializable(results)
        
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(results_serializable, f, indent=2, default=str)
            
        self.log_progress(f"\n✅ Results saved to: {OUTPUT_FILE}")
        
if __name__ == "__main__":
    backtester = PythiaBacktester()
    backtester.run_full_backtest()
