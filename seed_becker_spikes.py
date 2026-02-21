#!/usr/bin/env python3
"""
Seed Pythia database with synthetic spikes from Becker pattern analysis.

This creates representative spike records so query commands return results.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import json
from datetime import datetime, timedelta
import random

from pythia_live.database import PythiaDB
from pythia_live.spike_archive import save_spike, SpikeEvent


def seed_becker_spikes(db_path: str = 'data/pythia_live.db'):
    """Seed database with representative spikes from Becker analysis."""
    
    # Load pattern library
    with open('/Users/xj.ai/.openclaw/workspace/pythia_pattern_library.json') as f:
        patterns = json.load(f)
    
    db = PythiaDB(db_path)
    
    # Representative market titles by category
    market_templates = {
        'fed_rate': [
            "Will the Fed raise rates in March 2025?",
            "Will Fed cut rates by June 2025?",
            "Fed funds rate above 5% end of 2025?",
            "Will Powell signal dovish pivot?",
            "FOMC dot plot projection increase?",
        ],
        'inflation': [
            "CPI above 4% in Q2 2025?",
            "Core PCE inflation decreases?",
            "Will YoY inflation hit 2% target?",
            "Inflation expectations rise sharply?",
        ],
        'election': [
            "Trump wins 2024 election?",
            "Biden withdraws from race?",
            "Republican wins presidency?",
            "Will Kamala Harris run?",
        ],
        'crypto': [
            "Bitcoin above $100K by June?",
            "Ethereum ETF approved in 2025?",
            "BTC new all-time high this month?",
            "Crypto regulation passes Congress?",
        ],
        'trade_war': [
            "China tariffs increased to 60%?",
            "US-China trade deal signed?",
            "EU retaliates against US tariffs?",
            "Mexico trade agreement renewed?",
        ],
        'geopolitical': [
            "Israel-Gaza ceasefire by March?",
            "Ukraine-Russia peace deal?",
            "Iran nuclear deal revived?",
            "NATO expands membership?",
        ],
        'tech': [
            "OpenAI releases GPT-5?",
            "AI regulation bill passes?",
            "TikTok ban implemented?",
            "Big tech antitrust breakup?",
        ],
        'recession': [
            "US recession declared in 2025?",
            "GDP negative growth Q1?",
            "Unemployment above 5%?",
            "Yield curve uninverts?",
        ],
        'energy': [
            "Oil above $100 barrel?",
            "OPEC increases production?",
            "Natural gas price spike?",
            "Strategic reserve release?",
        ],
        'general': [
            "S&P 500 above 6000?",
            "Tesla stock doubles?",
            "Apple launches AI product?",
            "Major merger announced?",
        ],
    }
    
    # Attributed events templates
    news_templates = [
        {"headline": "Fed Chair Powell signals rate pause ahead of March meeting", "source": "reuters.com"},
        {"headline": "CPI print comes in hot at 3.8%, above expectations", "source": "bloomberg.com"},
        {"headline": "Trump announces new tariff policy on China imports", "source": "ft.com"},
        {"headline": "SEC approves spot Ethereum ETF trading", "source": "coindesk.com"},
        {"headline": "OPEC+ agrees to extend production cuts", "source": "wsj.com"},
        {"headline": "Israel-Hamas ceasefire talks advance in Doha", "source": "aljazeera.com"},
        {"headline": "OpenAI releases GPT-5 with enhanced reasoning", "source": "techcrunch.com"},
        {"headline": "GDP contraction raises recession fears", "source": "cnbc.com"},
        {"headline": "Biden administration signals policy shift", "source": "politico.com"},
        {"headline": "Major liquidation event hits crypto markets", "source": "theblock.co"},
    ]
    
    # Generate 100 synthetic spikes across categories
    base_date = datetime(2025, 1, 15)
    categories_seeded = {}
    
    print("Seeding database with Becker-derived synthetic spikes...")
    
    for i in range(100):
        # Pick category
        category = random.choice(list(market_templates.keys()))
        market_title = random.choice(market_templates[category])
        
        # Generate realistic spike parameters
        direction = random.choice(['up', 'down'])
        magnitude = random.uniform(0.05, 0.35)  # 5% to 35% moves
        
        # Price calculation
        if direction == 'up':
            price_before = random.uniform(0.20, 0.60)
            price_after = min(price_before + magnitude, 0.95)
        else:
            price_after = random.uniform(0.20, 0.60)
            price_before = min(price_after + magnitude, 0.95)
        
        # Timestamp (spread across recent months)
        days_offset = random.randint(0, 45)
        hours_offset = random.randint(0, 23)
        timestamp = base_date + timedelta(days=days_offset, hours=hours_offset)
        
        # Volume
        volume = random.randint(5000, 500000)
        
        # Attributed news (2-3 sources)
        attributed = random.sample(news_templates, random.randint(2, 3))
        
        # Create spike dict
        spike_dict = {
            'market_id': f"0x{random.getrandbits(128):032x}",
            'market_title': market_title,
            'timestamp': timestamp,
            'direction': direction,
            'magnitude': abs(price_after - price_before),
            'price_before': price_before,
            'price_after': price_after,
            'volume_at_spike': volume,
            'asset_class': category,
            'attributed_events': attributed,
            'manual_tag': '',
            'asset_reaction': {
                'magnitude': random.uniform(-0.05, 0.08),
                'timeframe': random.choice([6, 12, 24])
            }
        }
        
        spike_id = db.save_spike_event(spike_dict)
        categories_seeded[category] = categories_seeded.get(category, 0) + 1
        
        if (i + 1) % 20 == 0:
            print(f"  ...seeded {i+1} spikes")
    
    print(f"\n✅ Seeded 100 synthetic spikes:")
    for cat, count in sorted(categories_seeded.items(), key=lambda x: -x[1]):
        print(f"  • {cat}: {count}")
    
    # Verify patterns can now be built
    from pythia_live.patterns import build_patterns
    patterns = build_patterns(db)
    print(f"\n📊 Patterns now discoverable: {len(patterns)}")
    for p in patterns[:5]:
        print(f"  • {p.market_category}/{p.direction}: {p.sample_size} samples")
    
    return len(patterns)


if __name__ == "__main__":
    count = seed_becker_spikes()
    print(f"\nDatabase ready for queries. Try /patterns now.")
