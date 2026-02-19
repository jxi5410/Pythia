"""
Pythia Live - Real-time Prediction Market Intelligence

Run with: python run.py
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from pythia_live.main import main

if __name__ == "__main__":
    main()
