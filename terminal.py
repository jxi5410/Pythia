#!/usr/bin/env python3
"""
Pythia Terminal v2 — Bloomberg-style prediction market intelligence dashboard.

Phase 1 UX overhaul:
  - Sidebar: watchlists, alert config, system status
  - Tab 1: "What is Moving Now" homepage (confluence events, watchlist feed, divergences)
  - Tab 2-5: Inquiry, Patterns, Correlations, News Impact (carried forward)
  - Tab 6: Track Record (new)
  - Dark theme, dense layout, monospace numbers
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pythia_live.database import PythiaDB
from pythia_live.spike_archive import get_spike_history
from pythia_live.patterns import build_patterns, _categorize_market
from pythia_live.watchlists import WatchlistManager
from pythia_live.track_record import get_track_record
from pythia_live.confluence import get_confluence_history
from pythia_live.alert_engine import AlertEngine, AlertRule, TriggerType

# ================================================================== #
# Page config
# ================================================================== #

st.set_page_config(
    page_title="PYTHIA TERMINAL",
    page_icon="P",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ================================================================== #
# Dark terminal CSS
# ================================================================== #

st.markdown("""
<style>
    /* Base */
    .stApp { background-color: #0e1117; color: #c0c0c0; }

    /* Typography */
    h1, h2, h3, h4 { color: #00ff41 !important; font-family: 'SF Mono', 'Fira Code', 'Courier New', monospace !important; }
    .stMarkdown { color: #c0c0c0; }
    code { color: #00ff41; background-color: #1a1a2e; }

    /* Metrics */
    [data-testid="stMetric"] {
        background-color: #111827;
        border: 1px solid #1f2937;
        border-radius: 4px;
        padding: 12px 16px;
    }
    [data-testid="stMetricValue"] {
        color: #00ff41 !important;
        font-family: 'SF Mono', 'Fira Code', 'Courier New', monospace !important;
        font-size: 1.4rem !important;
    }
    [data-testid="stMetricLabel"] { color: #888 !important; font-size: 0.75rem !important; text-transform: uppercase; }
    [data-testid="stMetricDelta"] > div { font-family: 'Courier New', monospace; }

    /* Positive / negative deltas */
    [data-testid="stMetricDelta"] svg[data-testid="stMetricDeltaIcon-Up"] + div { color: #00ff41 !important; }
    [data-testid="stMetricDelta"] svg[data-testid="stMetricDeltaIcon-Down"] + div { color: #ff073a !important; }

    /* Sidebar */
    [data-testid="stSidebar"] { background-color: #0a0e14; border-right: 1px solid #1f2937; }
    [data-testid="stSidebar"] .stMarkdown { color: #9ca3af; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        color: #00ff41 !important;
    }

    /* Tables / DataFrames */
    .stDataFrame { font-family: 'SF Mono', 'Courier New', monospace !important; font-size: 0.8rem; }
    .stDataFrame td, .stDataFrame th { border-color: #1f2937 !important; }

    /* Inputs */
    input, textarea, select, [data-baseweb="select"] {
        background-color: #111827 !important;
        color: #e5e7eb !important;
        border-color: #374151 !important;
    }

    /* Buttons */
    .stButton > button {
        background-color: #0d2818;
        color: #00ff41;
        border: 1px solid #00ff41;
        font-family: 'Courier New', monospace;
        font-weight: bold;
    }
    .stButton > button:hover { background-color: #00ff41; color: #0e1117; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { border-bottom: 1px solid #1f2937; }
    .stTabs [data-baseweb="tab"] { color: #9ca3af; font-family: 'Courier New', monospace; font-size: 0.85rem; }
    .stTabs [aria-selected="true"] { color: #00ff41 !important; border-bottom-color: #00ff41 !important; }

    /* Expanders */
    .streamlit-expanderHeader { color: #d1d5db !important; font-family: 'Courier New', monospace; }
    .streamlit-expanderContent { background-color: #111827; border: 1px solid #1f2937; border-top: none; }

    /* Dividers */
    hr { border-color: #1f2937; }

    /* Custom classes */
    .pythia-header { font-family: 'SF Mono', 'Courier New', monospace; color: #00ff41; font-size: 13px; border-bottom: 1px solid #1f2937; padding-bottom: 6px; margin-bottom: 12px; letter-spacing: 1px; }
    .card-red { background-color: #1a0a0a; border: 1px solid #ff073a; border-radius: 4px; padding: 12px 16px; margin-bottom: 8px; }
    .card-amber { background-color: #1a1400; border: 1px solid #ffa500; border-radius: 4px; padding: 12px 16px; margin-bottom: 8px; }
    .card-green { background-color: #0a1a0a; border: 1px solid #00ff41; border-radius: 4px; padding: 12px 16px; margin-bottom: 8px; }
    .tag-red { color: #ff073a; font-weight: bold; }
    .tag-amber { color: #ffa500; font-weight: bold; }
    .tag-green { color: #00ff41; font-weight: bold; }
    .mono { font-family: 'SF Mono', 'Courier New', monospace; }
    .dimmed { color: #666; }
</style>
""", unsafe_allow_html=True)

# ================================================================== #
# Data loading
# ================================================================== #

DB_PATH = "data/pythia_live.db"


@st.cache_resource
def get_db():
    return PythiaDB(DB_PATH)


@st.cache_resource
def get_watchlist_manager():
    return WatchlistManager()


@st.cache_data(ttl=60)
def load_spikes(_db, min_mag=0.03, limit=200):
    return get_spike_history(_db, min_magnitude=min_mag, limit=limit)


@st.cache_data(ttl=300)
def load_patterns(_db):
    return build_patterns(_db)


@st.cache_data(ttl=120)
def load_confluence(_db, hours=24, min_score=0.0):
    return get_confluence_history(_db, hours=hours, min_score=min_score)


@st.cache_data(ttl=600)
def load_track_record(_db, days=30):
    return get_track_record(days=days, db=_db)


db = get_db()
wm = get_watchlist_manager()

# ================================================================== #
# Sidebar
# ================================================================== #

with st.sidebar:
    st.markdown("### P Y T H I A")
    st.markdown('<div class="pythia-header">PREDICTION MARKET INTELLIGENCE</div>', unsafe_allow_html=True)

    # --- Watchlist selector ---
    st.markdown("#### WATCHLISTS")
    watchlists = wm.list_watchlists()
    wl_names = ["All"] + [w.name for w in watchlists]
    active_wl = st.selectbox("Active watchlist", wl_names, index=0, label_visibility="collapsed")

    # Quick watchlist info
    if active_wl != "All":
        wl = wm.get(active_wl)
        if wl:
            st.caption(f"{len(wl.contracts)} contracts")
    else:
        st.caption("Showing all contracts")

    st.markdown("---")

    # --- Alert config ---
    with st.expander("ALERT CONFIG"):
        st.markdown("**Active rules**")
        alert_engine = AlertEngine()
        alert_engine.load_default_rules()

        for rule in alert_engine.get_rules():
            col_name, col_toggle = st.columns([3, 1])
            with col_name:
                st.markdown(f'<span class="mono" style="font-size:0.8rem;">{rule.name}</span>', unsafe_allow_html=True)
            with col_toggle:
                st.markdown(
                    f'<span class="tag-green" style="font-size:0.75rem;">ON</span>' if rule.enabled
                    else f'<span class="dimmed" style="font-size:0.75rem;">OFF</span>',
                    unsafe_allow_html=True,
                )

        st.caption("Configure via alert_engine.py or API")

    st.markdown("---")

    # --- System status ---
    st.markdown("#### SYSTEM STATUS")

    # Data freshness
    spikes_all = load_spikes(db, min_mag=0.01, limit=5)
    if spikes_all:
        latest = spikes_all[0]
        ts = latest.timestamp
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        if age_min < 60:
            freshness = f"{int(age_min)}m ago"
            color = "tag-green"
        elif age_min < 360:
            freshness = f"{int(age_min / 60)}h ago"
            color = "tag-amber"
        else:
            freshness = f"{int(age_min / 60)}h ago"
            color = "tag-red"
        st.markdown(f'Spikes: <span class="{color}">{freshness}</span>', unsafe_allow_html=True)
    else:
        st.markdown('Spikes: <span class="dimmed">no data</span>', unsafe_allow_html=True)

    confluence_recent = load_confluence(db, hours=24, min_score=0.0)
    st.markdown(
        f'Confluence: <span class="tag-green">{len(confluence_recent)} events (24h)</span>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'Watchlists: <span class="tag-green">{len(watchlists)} loaded</span>',
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown(
        '<span class="dimmed" style="font-size:0.7rem;">PYTHIA v1.0 · PHASE 1 UX</span>',
        unsafe_allow_html=True,
    )


# ================================================================== #
# Helper: filter spikes by watchlist
# ================================================================== #

def filter_by_watchlist(spikes, watchlist_name):
    """Filter spikes to only those matching contracts in the active watchlist."""
    if watchlist_name == "All":
        return spikes
    wl = wm.get(watchlist_name)
    if not wl or not wl.contracts:
        return spikes  # no filter if empty
    contracts_lower = [c.lower() for c in wl.contracts]
    filtered = []
    for s in spikes:
        title_lower = (s.market_title or "").lower()
        if any(c in title_lower for c in contracts_lower):
            filtered.append(s)
    return filtered


# ================================================================== #
# Header
# ================================================================== #

hdr1, hdr2, hdr3 = st.columns([4, 1, 1])
with hdr1:
    st.markdown("# PYTHIA TERMINAL")
    st.markdown(
        '<div class="pythia-header">CROSS-LAYER SIGNAL CONVERGENCE \u00b7 INSTITUTIONAL GRADE</div>',
        unsafe_allow_html=True,
    )
with hdr2:
    st.metric("STATUS", "LIVE")
with hdr3:
    st.metric("UTC", datetime.now(timezone.utc).strftime("%H:%M"))

# ================================================================== #
# Tabs
# ================================================================== #

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "WHAT IS MOVING NOW",
    "INQUIRY",
    "PATTERNS",
    "CORRELATIONS",
    "NEWS IMPACT",
    "TRACK RECORD",
])

# ================================================================== #
# TAB 1 — What is Moving Now (NEW homepage)
# ================================================================== #

with tab1:
    # --- Section 1: Active Confluence Events ---
    st.markdown("### ACTIVE CONFLUENCE EVENTS")

    confluence_events = load_confluence(db, hours=12, min_score=0.3)

    if confluence_events:
        # Show top events as color-coded cards
        cols = st.columns(min(len(confluence_events[:4]), 4))
        for i, evt in enumerate(confluence_events[:4]):
            score = evt.get("confluence_score", 0)
            category = evt.get("event_category", "unknown").upper()
            direction = evt.get("direction", "neutral").upper()
            layer_count = evt.get("layer_count", 0)

            layers_raw = evt.get("layers", "[]")
            if isinstance(layers_raw, str):
                try:
                    layers_list = json.loads(layers_raw)
                except (json.JSONDecodeError, TypeError):
                    layers_list = []
            else:
                layers_list = layers_raw or []

            if score >= 0.7:
                card_class = "card-red"
                tag_class = "tag-red"
            elif score >= 0.4:
                card_class = "card-amber"
                tag_class = "tag-amber"
            else:
                card_class = "card-green"
                tag_class = "tag-green"

            with cols[i % len(cols)]:
                st.markdown(
                    f'<div class="{card_class}">'
                    f'<span class="{tag_class}" style="font-size:1.1rem;">{category}</span><br>'
                    f'<span class="mono" style="color:#e5e7eb;">{direction}</span><br>'
                    f'<span class="mono">{layer_count} layers | {score:.0%}</span><br>'
                    f'<span class="dimmed" style="font-size:0.75rem;">{", ".join(layers_list[:4])}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # Expandable details for each event
        for evt in confluence_events[:6]:
            category = evt.get("event_category", "unknown")
            score = evt.get("confluence_score", 0)
            direction = evt.get("direction", "")
            alert_text = evt.get("alert_text", "")
            suggested = evt.get("suggested_assets", "[]")
            if isinstance(suggested, str):
                try:
                    suggested = json.loads(suggested)
                except (json.JSONDecodeError, TypeError):
                    suggested = []

            with st.expander(f"{category.upper()} — {score:.0%} ({direction})"):
                if alert_text:
                    st.text(alert_text)
                if suggested:
                    st.markdown(f"**Suggested assets:** {', '.join(suggested)}")
    else:
        st.info("No active confluence events in the last 12 hours.")

    st.markdown("---")

    # --- Section 2: Watchlist Feed ---
    st.markdown("### WATCHLIST FEED")

    spikes = load_spikes(db, min_mag=0.03, limit=100)
    spikes = filter_by_watchlist(spikes, active_wl)

    if spikes:
        rows = []
        for s in spikes[:30]:
            ts = s.timestamp
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            category = _categorize_market(s.market_title)

            rows.append({
                "TIME": ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[:5],
                "MARKET": s.market_title[:55],
                "CAT": category.upper()[:12],
                "DIR": "\u25b2" if s.direction == "up" else "\u25bc",
                "MOVE": f"{s.magnitude:.1%}",
                "VOL": f"${s.volume_at_spike:,.0f}" if s.volume_at_spike else "-",
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True, height=350)

        # Quick metrics
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("SIGNALS", len(spikes))
        with m2:
            up_ct = sum(1 for s in spikes if s.direction == "up")
            st.metric("UP / DOWN", f"{up_ct} / {len(spikes) - up_ct}")
        with m3:
            avg_mag = sum(s.magnitude for s in spikes) / len(spikes) if spikes else 0
            st.metric("AVG MOVE", f"{avg_mag:.1%}")
        with m4:
            cats = set(_categorize_market(s.market_title) for s in spikes)
            st.metric("CATEGORIES", len(cats))
    else:
        st.info("No recent spikes matching your watchlist.")

    st.markdown("---")

    # --- Section 3: Cross-Platform Divergence ---
    st.markdown("### CROSS-PLATFORM DIVERGENCE")

    # Build divergence data from confluence events that mention multiple platforms
    if confluence_events:
        divergence_shown = False
        for evt in confluence_events[:10]:
            layers_raw = evt.get("layers", "[]")
            if isinstance(layers_raw, str):
                try:
                    layers_list = json.loads(layers_raw)
                except (json.JSONDecodeError, TypeError):
                    layers_list = []
            else:
                layers_list = layers_raw or []

            signals_raw = evt.get("signals_json", "[]")
            if isinstance(signals_raw, str):
                try:
                    signals_list = json.loads(signals_raw)
                except (json.JSONDecodeError, TypeError):
                    signals_list = []
            else:
                signals_list = signals_raw or []

            if len(layers_list) >= 2:
                category = evt.get("event_category", "unknown")
                direction = evt.get("direction", "")
                score = evt.get("confluence_score", 0)
                layer_str = " | ".join(
                    f"{l}: active" for l in layers_list[:5]
                )
                st.markdown(
                    f'<div class="mono" style="font-size:0.85rem; color:#e5e7eb;">'
                    f'<span class="tag-amber">{category.upper()}</span> '
                    f'({direction}) — {layer_str}'
                    f"</div>",
                    unsafe_allow_html=True,
                )
                divergence_shown = True

        if not divergence_shown:
            st.caption("No significant cross-platform divergences detected.")
    else:
        st.caption("No divergence data — requires confluence events.")

    st.markdown("---")

    # --- Section 4: Causal Attributions (collapsible) ---
    with st.expander("CAUSAL ATTRIBUTIONS"):
        if spikes:
            attributed = [s for s in spikes[:20] if s.attributed_events]
            if attributed:
                for s in attributed[:5]:
                    title = s.market_title[:60]
                    cause = s.attributed_events[0].get("headline", "Unknown")[:100]
                    source = s.attributed_events[0].get("source", "")
                    st.markdown(
                        f'<span class="mono" style="font-size:0.85rem;">'
                        f'<span class="tag-green">{title}</span><br>'
                        f'&nbsp;&nbsp;{cause}'
                        f'{f" ({source})" if source else ""}'
                        f"</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown("")
            else:
                st.caption("No causal attributions available for recent spikes.")
        else:
            st.caption("No spike data for attribution.")

# ================================================================== #
# TAB 2 — Inquiry (carried forward)
# ================================================================== #

with tab2:
    st.markdown("### SPIKE INQUIRY")
    st.markdown("*Search historical spikes by market or keyword*")

    q1, q2 = st.columns([2, 1])
    with q1:
        query = st.text_input("Search markets", placeholder="e.g., Fed rate, Bitcoin, tariffs...", label_visibility="collapsed")
    with q2:
        min_magnitude = st.slider("Min magnitude", 0.03, 0.50, 0.05, 0.01, format="%.0f%%")

    if query:
        category = _categorize_market(query)
        all_spikes = load_spikes(db, min_mag=min_magnitude)
        results = [s for s in all_spikes if _categorize_market(s.market_title) == category]

        if results:
            st.markdown(f"**{len(results)} spikes** in category `{category.upper()}`")

            for s in results[:10]:
                ts = s.timestamp
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)

                arrow = "\u25b2" if s.direction == "up" else "\u25bc"
                with st.expander(f"{arrow} {s.magnitude:.1%} — {s.market_title[:60]}"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("Direction", s.direction.upper())
                    with c2:
                        st.metric("Price", f"{s.price_before:.2f} \u2192 {s.price_after:.2f}")
                    with c3:
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
                        st.markdown(f"**Asset reaction:** {sign}{mag:.1%} within {tf}h")
        else:
            st.warning(f"No spikes for '{query}' at \u2265{min_magnitude:.0%} magnitude")

# ================================================================== #
# TAB 3 — Patterns (carried forward)
# ================================================================== #

with tab3:
    st.markdown("### CAUSAL PATTERNS")
    st.markdown("*Recurring patterns from historical spike analysis*")

    patterns = load_patterns(db)

    if patterns:
        p1, p2, p3 = st.columns(3)
        with p1:
            st.metric("PATTERNS", len(patterns))
        with p2:
            high_conf = sum(1 for p in patterns if p.confidence >= 0.7)
            st.metric("HIGH CONF", high_conf)
        with p3:
            total_samples = sum(p.sample_size for p in patterns)
            st.metric("SAMPLES", f"{total_samples:,}")

        for p in patterns[:15]:
            conf_icon = "\u2588" * int(p.confidence * 10) + "\u2591" * (10 - int(p.confidence * 10))
            with st.expander(f"{p.market_category.upper()} / {p.direction.upper()} — {p.sample_size} samples"):
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("Avg Move", f"{p.avg_magnitude:.1%}")
                with c2:
                    st.metric("Samples", p.sample_size)
                with c3:
                    st.metric("Confidence", f"{p.confidence:.0%}")
                with c4:
                    if p.avg_asset_reaction:
                        sign = "+" if p.avg_asset_reaction > 0 else ""
                        st.metric("Reaction", f"{sign}{p.avg_asset_reaction:.1%}")
                    else:
                        st.metric("Reaction", "N/A")

                st.markdown(
                    f'<span class="mono dimmed">{conf_icon}</span>',
                    unsafe_allow_html=True,
                )
                if p.typical_cause:
                    st.markdown(f"**Typical cause:** {p.typical_cause}")
    else:
        st.info("No patterns discovered yet. Need more spike data.")

# ================================================================== #
# TAB 4 — Correlations (carried forward)
# ================================================================== #

with tab4:
    st.markdown("### CORRELATED MOVEMENTS")
    st.markdown("*Markets that move together within 2-hour windows*")

    corr_spikes = load_spikes(db, min_mag=0.05)

    if corr_spikes:
        selected_id = st.selectbox(
            "Select a spike",
            options=[s.id for s in corr_spikes[:20]],
            format_func=lambda x: next(
                (f"#{s.id} — {s.market_title[:40]}... ({s.direction} {s.magnitude:.1%})"
                 for s in corr_spikes if s.id == x),
                str(x),
            ),
        )

        if selected_id:
            ref = next(s for s in corr_spikes if s.id == selected_id)
            st.markdown(f"**Reference:** {ref.market_title[:60]}")
            st.markdown(f"**Move:** {ref.direction.upper()} {ref.magnitude:.1%}")

            correlated = []
            for s in corr_spikes:
                if s.id == ref.id:
                    continue
                try:
                    ref_time = ref.timestamp
                    s_time = s.timestamp
                    if isinstance(ref_time, str):
                        ref_time = datetime.fromisoformat(ref_time)
                    if isinstance(s_time, str):
                        s_time = datetime.fromisoformat(s_time)
                    diff = abs((s_time - ref_time).total_seconds())
                    if diff <= 7200:
                        correlated.append((s, diff))
                except Exception:
                    continue

            if correlated:
                st.markdown(f"**{len(correlated)} correlated movements:**")
                for s, diff in sorted(correlated, key=lambda x: x[1]):
                    mins = int(diff / 60)
                    st.markdown(
                        f"\u2022 **[{mins:+d} min]** {s.market_title[:50]}... — "
                        f"{s.direction.upper()} {s.magnitude:.1%}"
                    )
            else:
                st.info("No correlated spikes within 2-hour window.")
    else:
        st.info("Need spike data to find correlations.")

# ================================================================== #
# TAB 5 — News Impact (carried forward)
# ================================================================== #

with tab5:
    st.markdown("### NEWS IMPACT ANALYSIS")
    st.markdown("*Which news sources consistently move markets?*")

    news_spikes = load_spikes(db, min_mag=0.03)

    if news_spikes:
        source_stats = {}
        for s in news_spikes:
            for evt in s.attributed_events:
                source = evt.get("source", "unknown")
                if source and source != "unknown":
                    if source not in source_stats:
                        source_stats[source] = {"count": 0, "total_magnitude": 0, "headlines": []}
                    source_stats[source]["count"] += 1
                    source_stats[source]["total_magnitude"] += s.magnitude
                    source_stats[source]["headlines"].append(evt.get("headline", "")[:60])

        if source_stats:
            sorted_sources = sorted(source_stats.items(), key=lambda x: -x[1]["count"])
            rows = []
            for source, stats in sorted_sources[:15]:
                avg_mag = stats["total_magnitude"] / stats["count"]
                rows.append({
                    "SOURCE": source,
                    "ATTRIBUTIONS": stats["count"],
                    "AVG IMPACT": f"{avg_mag:.1%}",
                    "SAMPLE": stats["headlines"][0] if stats["headlines"] else "",
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No news attribution data available.")
    else:
        st.info("Need spike data for news analysis.")

# ================================================================== #
# TAB 6 — Track Record (NEW)
# ================================================================== #

with tab6:
    st.markdown("### PYTHIA TRACK RECORD")
    st.markdown("*Historical proof — did confluence signals predict asset moves?*")

    days_back = st.selectbox("Period", [7, 14, 30, 60, 90], index=2, format_func=lambda d: f"Last {d} days")
    record = load_track_record(db, days=days_back)

    if record.total_events > 0:
        # --- Hero metrics ---
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("EVENTS FIRED", record.total_events)
        with m2:
            st.metric("HIT RATE", f"{record.overall_hit_rate:.0%}",
                       delta=f"{record.total_hits} hits")
        with m3:
            fp = record.total_events - record.total_hits
            fpr = fp / record.total_events if record.total_events else 0
            st.metric("FALSE POSITIVE", f"{fpr:.0%}", delta=f"{fp} misses", delta_color="inverse")
        with m4:
            st.metric("AVG LEAD TIME", f"{record.avg_lead_time_hours:.1f}h")

        st.markdown("---")

        # --- Best categories ---
        if record.best_categories:
            st.markdown("#### BEST CATEGORIES")
            cat_rows = []
            for cat_name in record.best_categories[:5]:
                cs = next((c for c in record.category_stats if c.category == cat_name), None)
                if cs:
                    cat_rows.append({
                        "CATEGORY": cat_name.upper(),
                        "EVENTS": cs.event_count,
                        "HITS": cs.hit_count,
                        "HIT RATE": f"{cs.hit_rate:.0%}",
                        "AVG LEAD": f"{cs.avg_lead_time_hours:.1f}h",
                        "AVG SCORE": f"{cs.avg_confluence_score:.2f}",
                    })
            if cat_rows:
                st.dataframe(pd.DataFrame(cat_rows), use_container_width=True, hide_index=True)

        # --- Threshold breakdown ---
        with st.expander("FALSE POSITIVE RATE BY THRESHOLD"):
            if record.threshold_stats:
                th_rows = []
                for ts in record.threshold_stats:
                    if ts.total_events > 0:
                        th_rows.append({
                            "THRESHOLD": f"\u2265{ts.threshold:.0%}",
                            "EVENTS": ts.total_events,
                            "TRUE POS": ts.true_positives,
                            "FALSE POS": ts.false_positives,
                            "FPR": f"{ts.false_positive_rate:.0%}",
                            "PRECISION": f"{ts.precision:.0%}",
                        })
                if th_rows:
                    st.dataframe(pd.DataFrame(th_rows), use_container_width=True, hide_index=True)

        # --- Layer contributions ---
        with st.expander("LAYER CONTRIBUTIONS"):
            if record.layer_contributions:
                lc_rows = []
                for lc in record.layer_contributions:
                    if lc.appearances_total > 0:
                        bar = "\u2588" * int(lc.hit_rate_when_present * 10) + "\u2591" * (10 - int(lc.hit_rate_when_present * 10))
                        lc_rows.append({
                            "LAYER": lc.layer.upper(),
                            "APPEARANCES": lc.appearances_total,
                            "IN HITS": lc.appearances_in_hits,
                            "HIT RATE": f"{lc.hit_rate_when_present:.0%}",
                            "BAR": bar,
                        })
                if lc_rows:
                    st.dataframe(pd.DataFrame(lc_rows), use_container_width=True, hide_index=True)

        # --- Notable events ---
        with st.expander("NOTABLE EVENTS"):
            if record.notable_events:
                for evt in record.notable_events[:5]:
                    is_hit = evt.get("is_hit", False)
                    cat = evt.get("category", "?")
                    score = evt.get("score", 0)
                    layers = evt.get("layers", 0)
                    lead = evt.get("lead_time_hours")

                    icon = "\u2705" if is_hit else "\u274c"
                    lead_str = f" (led by {lead}h)" if lead else ""
                    st.markdown(
                        f"{icon} **{cat.upper()}** — {score:.0%} score, "
                        f"{layers} layers{lead_str}"
                    )
            else:
                st.caption("No notable events in this period.")
    else:
        st.info(f"No confluence events recorded in the last {days_back} days.")

# ================================================================== #
# Footer
# ================================================================== #

st.markdown("---")
st.markdown(
    '<div class="pythia-header">'
    "PYTHIA v1.0 \u00b7 DATA: POLYMARKET + KALSHI + 6 CROSS-ASSET LAYERS \u00b7 "
    "CONFLUENCE ENGINE \u00b7 BUILT FOR INSTITUTIONAL TRADERS"
    "</div>",
    unsafe_allow_html=True,
)
