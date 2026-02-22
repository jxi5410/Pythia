#!/usr/bin/env python3
"""
Pythia Terminal — Bloomberg-style prediction market intelligence interface.

A web-based terminal for institutional traders to query, analyze, and monitor
prediction market signals. Designed to feel like a professional trading terminal.

Features:
- Real-time signal feed
- Historical spike inquiry with attribution
- Pattern discovery dashboard
- Correlated market movements
- News impact scoring

Competitor awareness: Verso (YC-backed) and Sharpe Terminal exist.
Pythia's differentiation: causal attribution + multi-agent signal analysis.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from pythia_live.database import PythiaDB
from pythia_live.spike_archive import get_spike_history
from pythia_live.patterns import build_patterns, _categorize_market

# --- Page Config ---
st.set_page_config(
    page_title="PYTHIA TERMINAL",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Dark Terminal Styling ---
st.markdown("""
<style>
    .stApp { background-color: #0a0a0a; color: #00ff88; }
    .stMarkdown { color: #c0c0c0; }
    h1, h2, h3 { color: #00ff88 !important; }
    .stMetric { background-color: #111; border: 1px solid #333; border-radius: 4px; padding: 10px; }
    .stMetricValue { color: #00ff88 !important; font-family: 'Courier New', monospace; }
    .stMetricLabel { color: #888 !important; }
    .stDataFrame { font-family: 'Courier New', monospace; }
    div[data-testid="stSidebar"] { background-color: #111; }
    .signal-critical { color: #ff4444; font-weight: bold; }
    .signal-high { color: #ff8800; }
    .signal-medium { color: #ffcc00; }
    .signal-low { color: #44aa44; }
    input, textarea, select { background-color: #1a1a1a !important; color: #00ff88 !important; border: 1px solid #333 !important; }
    .stButton>button { background-color: #1a3a1a; color: #00ff88; border: 1px solid #00ff88; }
    .stButton>button:hover { background-color: #00ff88; color: #000; }
    .terminal-header { font-family: 'Courier New', monospace; color: #00ff88; font-size: 14px; border-bottom: 1px solid #333; padding-bottom: 5px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# --- Load Data ---
DB_PATH = "data/pythia_live.db"

@st.cache_resource
def get_db():
    return PythiaDB(DB_PATH)

@st.cache_data(ttl=60)
def load_spikes(_db, min_mag=0.03, limit=200):
    return get_spike_history(_db, min_magnitude=min_mag, limit=limit)

@st.cache_data(ttl=300)
def load_patterns(_db):
    return build_patterns(_db)

db = get_db()

# --- Header ---
col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    st.markdown("# 🎯 PYTHIA TERMINAL")
    st.markdown('<div class="terminal-header">PREDICTION MARKET INTELLIGENCE · INSTITUTIONAL GRADE</div>', unsafe_allow_html=True)
with col2:
    st.metric("STATUS", "LIVE")
with col3:
    st.metric("TIME", datetime.now().strftime("%H:%M:%S"))

# --- Navigation ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 SIGNAL FEED",
    "🔍 INQUIRY",
    "📈 PATTERNS",
    "🔗 CORRELATIONS",
    "📰 NEWS IMPACT"
])

# === TAB 1: SIGNAL FEED ===
with tab1:
    st.markdown("### RECENT SIGNALS")
    
    spikes = load_spikes(db)
    
    if spikes:
        # Convert to DataFrame for display
        rows = []
        for s in spikes[:50]:
            ts = s.timestamp
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            
            category = _categorize_market(s.market_title)
            cause = ""
            if s.attributed_events:
                cause = s.attributed_events[0].get("headline", "")[:50]
            
            rows.append({
                "ID": s.id,
                "TIME": ts.strftime("%m/%d %H:%M") if hasattr(ts, 'strftime') else str(ts)[:16],
                "MARKET": s.market_title[:50],
                "CATEGORY": category.upper(),
                "DIR": "↑" if s.direction == "up" else "↓",
                "MOVE": f"{s.magnitude:.1%}",
                "VOLUME": f"${s.volume_at_spike:,.0f}",
                "CAUSE": cause,
            })
        
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True, height=500)
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("TOTAL SIGNALS", len(spikes))
        with col2:
            up_count = sum(1 for s in spikes if s.direction == "up")
            st.metric("UP / DOWN", f"{up_count} / {len(spikes) - up_count}")
        with col3:
            avg_mag = sum(s.magnitude for s in spikes) / len(spikes) if spikes else 0
            st.metric("AVG MAGNITUDE", f"{avg_mag:.1%}")
        with col4:
            categories = set(_categorize_market(s.market_title) for s in spikes)
            st.metric("CATEGORIES", len(categories))
    else:
        st.info("No signals detected yet. Start Pythia monitoring to collect data.")

# === TAB 2: INQUIRY ===
with tab2:
    st.markdown("### SPIKE INQUIRY")
    st.markdown("*Ask: Has this happened before? What caused it?*")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        query = st.text_input("🔍 Search markets", placeholder="e.g., Fed rate, Bitcoin, election...")
    
    with col2:
        min_magnitude = st.slider("Min magnitude", 0.03, 0.50, 0.05, 0.01, format="%.0f%%")
    
    if query:
        category = _categorize_market(query)
        spikes = load_spikes(db, min_mag=min_magnitude)
        results = [s for s in spikes if _categorize_market(s.market_title) == category]
        
        if results:
            st.markdown(f"**Found {len(results)} spikes in category: `{category.upper()}`**")
            
            for s in results[:10]:
                ts = s.timestamp
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                
                with st.expander(f"{'↑' if s.direction == 'up' else '↓'} {s.magnitude:.1%} — {s.market_title[:60]}"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Direction", s.direction.upper())
                    with col2:
                        st.metric("Price Move", f"{s.price_before:.2f} → {s.price_after:.2f}")
                    with col3:
                        st.metric("Volume", f"${s.volume_at_spike:,.0f}")
                    
                    if s.attributed_events:
                        st.markdown("**ATTRIBUTED CAUSES:**")
                        for i, evt in enumerate(s.attributed_events[:3], 1):
                            headline = evt.get("headline", "Unknown")
                            source = evt.get("source", "unknown")
                            st.markdown(f"{i}. **{headline}** ({source})")
                    
                    if s.asset_reaction:
                        mag = s.asset_reaction.get("magnitude", 0)
                        tf = s.asset_reaction.get("timeframe", "?")
                        sign = "+" if mag > 0 else ""
                        st.markdown(f"**Asset Reaction:** {sign}{mag:.1%} within {tf}h")
        else:
            st.warning(f"No spikes found for '{query}' with ≥{min_magnitude:.0%} magnitude")

# === TAB 3: PATTERNS ===
with tab3:
    st.markdown("### CAUSAL PATTERNS")
    st.markdown("*Recurring patterns discovered from historical spike analysis*")
    
    patterns = load_patterns(db)
    
    if patterns:
        # Pattern summary
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("PATTERNS FOUND", len(patterns))
        with col2:
            high_conf = sum(1 for p in patterns if p.confidence >= 0.7)
            st.metric("HIGH CONFIDENCE", high_conf)
        with col3:
            total_samples = sum(p.sample_size for p in patterns)
            st.metric("TOTAL SAMPLES", total_samples)
        
        # Pattern cards
        for p in patterns[:15]:
            conf_color = "🟢" if p.confidence >= 0.7 else "🟡" if p.confidence >= 0.5 else "🔴"
            
            with st.expander(f"{conf_color} {p.market_category.upper()} / {p.direction.upper()} — {p.sample_size} samples"):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Avg Move", f"{p.avg_magnitude:.1%}")
                with col2:
                    st.metric("Samples", p.sample_size)
                with col3:
                    st.metric("Confidence", f"{p.confidence:.0%}")
                with col4:
                    if p.avg_asset_reaction:
                        sign = "+" if p.avg_asset_reaction > 0 else ""
                        st.metric("Avg Reaction", f"{sign}{p.avg_asset_reaction:.1%}")
                    else:
                        st.metric("Avg Reaction", "N/A")
                
                if p.typical_cause:
                    st.markdown(f"**Typical cause:** {p.typical_cause}")
    else:
        st.info("No patterns discovered yet. Need more spike data.")

# === TAB 4: CORRELATIONS ===
with tab4:
    st.markdown("### CORRELATED MOVEMENTS")
    st.markdown("*Markets that move together within 2-hour windows*")
    
    spikes = load_spikes(db, min_mag=0.05)
    
    if spikes:
        selected_id = st.selectbox(
            "Select a spike to find correlations",
            options=[s.id for s in spikes[:20]],
            format_func=lambda x: next(
                (f"#{s.id} — {s.market_title[:40]}... ({s.direction} {s.magnitude:.1%})" 
                 for s in spikes if s.id == x),
                str(x)
            )
        )
        
        if selected_id:
            ref_spike = next(s for s in spikes if s.id == selected_id)
            
            st.markdown(f"**Reference:** {ref_spike.market_title[:60]}")
            st.markdown(f"**Move:** {ref_spike.direction.upper()} {ref_spike.magnitude:.1%}")
            
            # Find correlated
            from datetime import timedelta
            correlated = []
            for s in spikes:
                if s.id == ref_spike.id:
                    continue
                try:
                    ref_time = ref_spike.timestamp
                    s_time = s.timestamp
                    if isinstance(ref_time, str):
                        ref_time = datetime.fromisoformat(ref_time)
                    if isinstance(s_time, str):
                        s_time = datetime.fromisoformat(s_time)
                    diff = abs((s_time - ref_time).total_seconds())
                    if diff <= 7200:
                        correlated.append((s, diff))
                except:
                    continue
            
            if correlated:
                st.markdown(f"**Found {len(correlated)} correlated movements:**")
                for s, diff in sorted(correlated, key=lambda x: x[1]):
                    mins = int(diff / 60)
                    st.markdown(f"• **[{mins:+d} min]** {s.market_title[:50]}... — {s.direction.upper()} {s.magnitude:.1%}")
            else:
                st.info("No correlated spikes found within 2-hour window.")
    else:
        st.info("Need spike data to find correlations.")

# === TAB 5: NEWS IMPACT ===
with tab5:
    st.markdown("### NEWS IMPACT ANALYSIS")
    st.markdown("*Which news sources consistently move markets?*")
    
    spikes = load_spikes(db, min_mag=0.03)
    
    if spikes:
        # Aggregate news sources
        source_stats = {}
        for s in spikes:
            for evt in s.attributed_events:
                source = evt.get("source", "unknown")
                if source and source != "unknown":
                    if source not in source_stats:
                        source_stats[source] = {"count": 0, "total_magnitude": 0, "headlines": []}
                    source_stats[source]["count"] += 1
                    source_stats[source]["total_magnitude"] += s.magnitude
                    source_stats[source]["headlines"].append(evt.get("headline", "")[:60])
        
        if source_stats:
            # Sort by count
            sorted_sources = sorted(source_stats.items(), key=lambda x: -x[1]["count"])
            
            rows = []
            for source, stats in sorted_sources[:15]:
                avg_mag = stats["total_magnitude"] / stats["count"]
                rows.append({
                    "SOURCE": source,
                    "ATTRIBUTIONS": stats["count"],
                    "AVG IMPACT": f"{avg_mag:.1%}",
                    "SAMPLE HEADLINE": stats["headlines"][0] if stats["headlines"] else ""
                })
            
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No news attribution data available.")
    else:
        st.info("Need spike data for news analysis.")

# --- Footer ---
st.markdown("---")
st.markdown(
    '<div class="terminal-header">PYTHIA v0.5 · DATA: POLYMARKET + KALSHI · '
    'PATTERNS: BECKER 9.15M SPIKES · BUILT FOR INSTITUTIONAL TRADERS</div>',
    unsafe_allow_html=True
)
