#!/usr/bin/env python3
"""
Pythia Live - Unified Launcher

Usage:
  python run.py           # Start monitoring only
  python run.py --auto    # Start with automation (paper trading)
  python run.py --dash    # Start dashboard only
"""

import argparse
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def main():
    parser = argparse.ArgumentParser(description='Pythia Live - Prediction Market Intelligence')
    parser.add_argument('--auto', action='store_true', help='Enable automation (paper trading)')
    parser.add_argument('--dash', action='store_true', help='Start dashboard only')
    parser.add_argument('--config', default='config.json', help='Config file path')
    
    args = parser.parse_args()
    
    if args.dash:
        # Start dashboard
        print("🎯 Starting Pythia Dashboard...")
        import subprocess
        subprocess.run([
            sys.executable, '-m', 'streamlit', 'run', 'dashboard.py',
            '--server.port=8504', '--server.headless=true'
        ])
    elif args.auto:
        # Start with automation
        print("🤖 Starting Pythia Live with Automation...")
        from pythia_live.main import PythiaLive
        from pythia_live.automation import AutomationController
        
        # Load config
        import json
        config = {
            'initial_capital': 10000,
            'max_daily_trades': 10,
            'daily_loss_limit': 0.10,
            'max_drawdown': 0.20,
        }
        
        if os.path.exists(args.config):
            with open(args.config) as f:
                config.update(json.load(f))
        
        # Start automation
        controller = AutomationController('data/pythia_live.db', config)
        controller.start_automation()
    else:
        # Start monitoring only
        print("🎯 Starting Pythia Live (Monitoring Mode)...")
        from pythia_live.main import PythiaLive
        
        pythia = PythiaLive()
        pythia.run()

if __name__ == "__main__":
    main()
