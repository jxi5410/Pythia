"""
Pythia Live Web Dashboard
Modern trading intelligence interface
"""

import json
import os
import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from pathlib import Path

# Page config
st.set_page_config(
    page_title="Pythia Live | Prediction Market Intelligence",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Modern dark styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
    .main { background-color: #09090b; }
    html, body, [class*="css"] { font-family: 'Inter', -apple-system, system-ui, sans-serif !important; }
    .signal-card {
        background: #131316; border-left: 3px solid rgba(255, 255, 255, 0.06);
        padding: 16px 18px; margin: 10px 0; border-radius: 12px;
        font-size: 0.88em; border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .signal-critical { border-left-color: #f43f5e; box-shadow: inset 3px 0 12px -4px rgba(244, 63, 94, 0.15); }
    .signal-high { border-left-color: #f97316; box-shadow: inset 3px 0 12px -4px rgba(249, 115, 22, 0.15); }
    .signal-medium { border-left-color: #eab308; box-shadow: inset 3px 0 12px -4px rgba(234, 179, 8, 0.12); }
    .signal-low { border-left-color: #10b981; box-shadow: inset 3px 0 12px -4px rgba(16, 185, 129, 0.12); }
    .asset-badge {
        display: inline-block; padding: 3px 10px; border-radius: 100px;
        font-size: 0.72em; font-weight: 600; text-transform: uppercase;
        background: rgba(255, 255, 255, 0.04); color: #a1a1aa; margin-right: 6px;
        border: 1px solid rgba(255, 255, 255, 0.06); letter-spacing: 0.04em;
    }
    .asset-rates { background: rgba(59, 130, 246, 0.08); color: #60a5fa; border-color: rgba(59, 130, 246, 0.15); }
    .asset-fx { background: rgba(168, 85, 247, 0.08); color: #c084fc; border-color: rgba(168, 85, 247, 0.15); }
    .asset-equities { background: rgba(16, 185, 129, 0.08); color: #34d399; border-color: rgba(16, 185, 129, 0.15); }
    .asset-commodities { background: rgba(245, 158, 11, 0.08); color: #fbbf24; border-color: rgba(245, 158, 11, 0.15); }
    .asset-crypto { background: rgba(236, 72, 153, 0.08); color: #f472b6; border-color: rgba(236, 72, 153, 0.15); }
    .asset-geopolitical { background: rgba(244, 63, 94, 0.08); color: #fb7185; border-color: rgba(244, 63, 94, 0.15); }
    .heatmap-up { color: #10b981; }
    .heatmap-down { color: #f43f5e; }
    .status-dot { display: inline-block; width: 7px; height: 7px;
                  border-radius: 50%; margin-right: 5px; }
    .status-live { background: #10b981; box-shadow: 0 0 8px rgba(16, 185, 129, 0.4); }
    .status-offline { background: #f43f5e; }
</style>
""", unsafe_allow_html=True)

def resolve_db_path() -> Path:
    env_path = os.getenv("PYTHIA_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path(__file__).resolve().parent / "data" / "pythia_live.db"


DB_PATH = resolve_db_path()

# Database helpers
@st.cache_resource
def get_db():
    if DB_PATH.exists():
        return sqlite3.connect(DB_PATH, check_same_thread=False)
    return None


def load_signals(hours=24):
    conn = get_db()
    if not conn:
        return pd.DataFrame()
    return pd.read_sql_query("""
        SELECT s.*, m.title, m.source, m.liquidity, m.category
        FROM signals s
        JOIN markets m ON s.market_id = m.id
        WHERE s.timestamp > datetime('now', ? || ' hours')
        ORDER BY s.timestamp DESC
    """, conn, params=(f'-{hours}',))


def load_markets(min_liquidity=10000):
    conn = get_db()
    if not conn:
        return pd.DataFrame()
    return pd.read_sql_query("""
        SELECT * FROM markets
        WHERE liquidity >= ?
        ORDER BY liquidity DESC
    """, conn, params=(min_liquidity,))


def load_price_history(market_id, hours=24):
    conn = get_db()
    if not conn:
        return pd.DataFrame()
    return pd.read_sql_query("""
        SELECT * FROM prices
        WHERE market_id = ? AND timestamp > datetime('now', ? || ' hours')
        ORDER BY timestamp
    """, conn, params=(market_id, f'-{hours}'))


def load_market_with_change():
    """Load markets with 24h price change for heatmap."""
    conn = get_db()
    if not conn:
        return pd.DataFrame()
    return pd.read_sql_query("""
        SELECT m.id, m.title, m.category, m.liquidity, m.volume_24h, m.source,
               p_latest.yes_price AS current_price,
               p_old.yes_price AS old_price
        FROM markets m
        LEFT JOIN (
            SELECT market_id, yes_price,
                   ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY timestamp DESC) AS rn
            FROM prices
        ) p_latest ON p_latest.market_id = m.id AND p_latest.rn = 1
        LEFT JOIN (
            SELECT market_id, yes_price,
                   ROW_NUMBER() OVER (
                       PARTITION BY market_id
                       ORDER BY ABS(julianday(timestamp) - julianday('now', '-24 hours'))
                   ) AS rn
            FROM prices
            WHERE timestamp > datetime('now', '-48 hours')
        ) p_old ON p_old.market_id = m.id AND p_old.rn = 1
        WHERE m.liquidity >= 10000
        ORDER BY m.liquidity DESC
        LIMIT 200
    """, conn)


def classify_title(title):
    """Classify a market title into asset class (mirrors asset_map.py logic)."""
    from src.pythia_live.asset_map import classify_market
    return classify_market(title, "")


# Header — compact
col_h1, col_h2 = st.columns([4, 1])
with col_h1:
    st.title("🎯 PYTHIA LIVE")
with col_h2:
    if DB_PATH.exists():
        mod_time = datetime.fromtimestamp(DB_PATH.stat().st_mtime)
        age_sec = (datetime.now() - mod_time).total_seconds()
        status = "🟢" if age_sec < 120 else "🟡"
        st.caption(f"{status} Last update: {mod_time.strftime('%H:%M:%S')}")
    else:
        st.caption("🔴 Offline")

# Sidebar — filters only
with st.sidebar:
    st.header("Filters")
    time_range = st.selectbox("Time Range", ["1 Hour", "6 Hours", "24 Hours", "7 Days"], index=2)
    hours = {"1 Hour": 1, "6 Hours": 6, "24 Hours": 24, "7 Days": 168}[time_range]

    severity_filter = st.multiselect(
        "Severity", ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        default=["CRITICAL", "HIGH", "MEDIUM"]
    )
    min_liquidity = st.slider("Min Liquidity ($)", 1000, 100000, 10000, 1000)

    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_resource.clear()
        st.rerun()

# Tabs
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Intelligence Feed", "Market Map", "Signals", "Analysis", "Spike Explorer", "Live Events"
])

# ─────────────────────────────────────────────
# Tab 1: Intelligence Feed
# ─────────────────────────────────────────────
with tab1:
    signals_df = load_signals(hours)

    # KPI row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        n = len(signals_df)
        crit = len(signals_df[signals_df['severity'] == 'CRITICAL']) if n else 0
        st.metric("Signals", n, delta=f"{crit} critical" if crit else None)
    with col2:
        avg_ret = signals_df['expected_return'].mean() if not signals_df.empty else 0
        st.metric("Avg Edge", f"{avg_ret:.2%}")
    with col3:
        markets_df = load_markets(min_liquidity)
        st.metric("Active Markets", len(markets_df))
    with col4:
        liq = markets_df['liquidity'].sum() if not markets_df.empty else 0
        st.metric("Total Liquidity", f"${liq:,.0f}")

    st.divider()

    # Live signal cards
    if not signals_df.empty:
        # Filter
        display_df = signals_df
        if severity_filter:
            display_df = display_df[display_df['severity'].isin(severity_filter)]

        for _, sig in display_df.head(20).iterrows():
            sev = sig['severity']
            sev_class = f"signal-{sev.lower()}"
            emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(sev, "⚪")

            title = sig.get('title', 'Unknown') or 'Unknown'
            # Classify for asset badge
            cls = classify_title(title)
            asset_class = cls['asset_class']
            badge_class = f"asset-{asset_class}" if asset_class != "general" else ""

            # Price change
            price_line = ""
            if pd.notna(sig.get('old_price')) and pd.notna(sig.get('new_price')):
                old_p = sig['old_price'] * 100
                new_p = sig['new_price'] * 100
                change = new_p - old_p
                sign = "+" if change >= 0 else ""
                price_line = f"<br>{old_p:.0f}% → {new_p:.0f}% ({sign}{change:.0f}pp)"

            ts = sig['timestamp']
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts).strftime('%H:%M:%S')
                except (ValueError, TypeError):
                    pass

            st.markdown(f"""
            <div class="signal-card {sev_class}">
                <span class="asset-badge {badge_class}">{asset_class}</span>
                <b>{emoji} {sig['signal_type']}</b> · {ts}
                <br><b>{title[:80]}</b>{price_line}
                <br><span style="color:#a1a1aa">Edge: {sig['expected_return']:.2%} · {cls['instruments'][:60]}</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No signals in selected time range. Is Pythia Live running?")

# ─────────────────────────────────────────────
# Tab 2: Market Map
# ─────────────────────────────────────────────
with tab2:
    st.subheader("Markets by Asset Class")

    mkt_df = load_market_with_change()

    if not mkt_df.empty:
        # Classify each market
        mkt_df['asset_class'] = mkt_df['title'].apply(
            lambda t: classify_title(t or '')['asset_class']
        )
        mkt_df['price_change_24h'] = mkt_df['current_price'] - mkt_df['old_price']

        # Group by asset class
        for ac in ["rates", "fx", "equities", "commodities", "crypto", "geopolitical", "general"]:
            group = mkt_df[mkt_df['asset_class'] == ac]
            if group.empty:
                continue

            with st.expander(f"{ac.upper()} ({len(group)} markets)", expanded=(ac != "general")):
                # Heatmap-style table
                display = group[['title', 'current_price', 'price_change_24h', 'liquidity', 'source']].copy()
                display.columns = ['Market', 'Price', '24h Change', 'Liquidity', 'Source']
                display['Price'] = display['Price'].apply(lambda x: f"{x:.0%}" if pd.notna(x) else "—")
                display['24h Change'] = display['24h Change'].apply(
                    lambda x: f"{x:+.1%}" if pd.notna(x) else "—"
                )
                display['Liquidity'] = display['Liquidity'].apply(
                    lambda x: f"${x:,.0f}" if pd.notna(x) else "—"
                )
                st.dataframe(
                    display.head(15),
                    use_container_width=True,
                    hide_index=True,
                )

        # Heatmap visualization
        st.divider()
        st.subheader("24h Probability Change Heatmap")

        heatmap_df = mkt_df.dropna(subset=['price_change_24h']).head(40)
        if not heatmap_df.empty:
            heatmap_df['short_title'] = heatmap_df['title'].str[:50]
            fig = px.bar(
                heatmap_df.sort_values('price_change_24h'),
                x='price_change_24h',
                y='short_title',
                orientation='h',
                color='price_change_24h',
                color_continuous_scale=['#f43f5e', '#1c1c22', '#10b981'],
                color_continuous_midpoint=0,
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#a1a1aa',
                yaxis_title='',
                xaxis_title='24h Change',
                height=max(400, len(heatmap_df) * 22),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Not enough price history for heatmap")
    else:
        st.warning("No market data available")

# ─────────────────────────────────────────────
# Tab 3: Signals Table
# ─────────────────────────────────────────────
with tab3:
    st.subheader("Signal Feed")

    signals_all = load_signals(hours)

    if not signals_all.empty:
        # Apply filters
        if severity_filter:
            signals_all = signals_all[signals_all['severity'].isin(severity_filter)]

        # Add asset class column
        signals_all['asset_class'] = signals_all['title'].apply(
            lambda t: classify_title(t or '')['asset_class']
        )
        signals_all['why_it_matters'] = signals_all['title'].apply(
            lambda t: classify_title(t or '')['how_it_matters']
        )

        display_cols = ['timestamp', 'severity', 'signal_type', 'asset_class', 'title',
                        'why_it_matters', 'expected_return', 'alert_sent']
        available = [c for c in display_cols if c in signals_all.columns]

        st.dataframe(
            signals_all[available],
            use_container_width=True,
            hide_index=True,
            column_config={
                'expected_return': st.column_config.NumberColumn("Edge", format="%.2%%"),
                'alert_sent': st.column_config.CheckboxColumn("Alerted"),
                'title': st.column_config.TextColumn("Market", width="large"),
                'why_it_matters': st.column_config.TextColumn("Why It Matters", width="large"),
            }
        )

        csv = signals_all.to_csv(index=False)
        st.download_button(
            "📥 Export CSV", csv,
            f"pythia_signals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv"
        )
    else:
        st.warning("No signals found. Is Pythia Live running?")

# ─────────────────────────────────────────────
# Tab 4: Forward Testing Performance
# ─────────────────────────────────────────────
with tab4:
    st.markdown("### Forward Testing")
    st.info("This dashboard tab is deprecated for performance analytics. Use `terminal.py` for live forward-testing metrics based on resolved outcomes.")

    signals_df = load_signals(hours)
    if signals_df.empty:
        st.warning("No signals available in the selected window.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Signals Observed", len(signals_df))
        c2.metric("Avg Expected Edge", f"{signals_df['expected_return'].mean():.2%}")
        c3.metric("Critical Signals", int((signals_df["severity"] == "CRITICAL").sum()))
        st.caption("Only descriptive feed statistics are shown here. Realized P&L/win-rate requires outcome tracking and is reported in terminal workflows.")

# ─────────────────────────────────────────────
# Tab 5: Spike Explorer
# ─────────────────────────────────────────────
with tab5:
    st.subheader("Spike Archive & Causal Patterns")

    conn = get_db()
    if conn:
        # Check if spike_events table exists
        try:
            spike_df = pd.read_sql_query("""
                SELECT * FROM spike_events
                ORDER BY timestamp DESC
                LIMIT 200
            """, conn)
        except Exception:
            spike_df = pd.DataFrame()

        if not spike_df.empty:
            # --- Spike Timeline Scatter ---
            st.markdown("#### Spike Timeline")

            spike_df['timestamp'] = pd.to_datetime(spike_df['timestamp'], format='mixed')
            spike_df['magnitude_pct'] = spike_df['magnitude'] * 100

            fig = px.scatter(
                spike_df,
                x='timestamp',
                y='magnitude_pct',
                color='asset_class',
                size='volume_at_spike',
                size_max=20,
                hover_data=['market_title', 'direction', 'manual_tag'],
                labels={
                    'timestamp': 'Time',
                    'magnitude_pct': 'Magnitude (%)',
                    'asset_class': 'Asset Class',
                },
                color_discrete_map={
                    'rates': '#60a5fa', 'fx': '#c084fc', 'equities': '#34d399',
                    'commodities': '#fbbf24', 'crypto': '#f472b6',
                    'geopolitical': '#fb7185', 'general': '#a1a1aa',
                },
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#a1a1aa',
                xaxis_gridcolor='#2a3441',
                yaxis_gridcolor='#2a3441',
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)

            # --- Filters ---
            st.divider()
            st.markdown("#### Spike Detail Table")

            col_f1, col_f2, col_f3, col_f4 = st.columns(4)
            with col_f1:
                asset_options = ['All'] + sorted(spike_df['asset_class'].dropna().unique().tolist())
                sel_asset = st.selectbox("Asset Class", asset_options, key="spike_asset")
            with col_f2:
                dir_options = ['All', 'up', 'down']
                sel_dir = st.selectbox("Direction", dir_options, key="spike_dir")
            with col_f3:
                min_mag = st.slider("Min Magnitude (%)", 0.0, 30.0, 3.0, 0.5, key="spike_mag")
            with col_f4:
                date_range = st.selectbox("Date Range", ["All Time", "7 Days", "30 Days", "90 Days"], key="spike_date")

            filtered = spike_df.copy()
            if sel_asset != 'All':
                filtered = filtered[filtered['asset_class'] == sel_asset]
            if sel_dir != 'All':
                filtered = filtered[filtered['direction'] == sel_dir]
            filtered = filtered[filtered['magnitude'] >= min_mag / 100]
            if date_range != "All Time":
                days = {"7 Days": 7, "30 Days": 30, "90 Days": 90}[date_range]
                cutoff = datetime.now() - timedelta(days=days)
                filtered = filtered[filtered['timestamp'] >= cutoff]

            # Parse attributed events for display
            def get_cause(row):
                events = row.get('attributed_events', '[]')
                if isinstance(events, str):
                    try:
                        events = json.loads(events)
                    except (json.JSONDecodeError, TypeError):
                        return ''
                if events and isinstance(events, list) and len(events) > 0:
                    return events[0].get('headline', '')[:80]
                return ''

            def get_reaction(row):
                reaction = row.get('asset_reaction', '')
                if isinstance(reaction, str):
                    try:
                        reaction = json.loads(reaction)
                    except (json.JSONDecodeError, TypeError):
                        return ''
                if isinstance(reaction, dict) and reaction:
                    mag = reaction.get('magnitude', 0)
                    return f"{mag:+.1%}" if mag else ''
                return ''

            display = filtered[['id', 'timestamp', 'market_title', 'direction', 'magnitude',
                                'asset_class', 'manual_tag']].copy()
            display['attributed_cause'] = filtered.apply(get_cause, axis=1)
            display['asset_reaction'] = filtered.apply(get_reaction, axis=1)
            display['magnitude'] = display['magnitude'].apply(lambda x: f"{x:.1%}")
            display.columns = ['ID', 'Timestamp', 'Market', 'Dir', 'Magnitude',
                               'Asset Class', 'Manual Tag', 'Attributed Cause', 'Reaction']

            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    'Market': st.column_config.TextColumn("Market", width="large"),
                    'Attributed Cause': st.column_config.TextColumn("Attributed Cause", width="large"),
                }
            )

            # --- Manual Tagging ---
            st.divider()
            st.markdown("#### Manual Spike Tagging")
            st.caption("Tag a spike with its real-world cause for pattern building")

            with st.form("spike_tag_form"):
                col_t1, col_t2 = st.columns([1, 3])
                with col_t1:
                    tag_spike_id = st.number_input("Spike ID", min_value=1, step=1, key="tag_id")
                with col_t2:
                    tag_text = st.text_input("Cause / Tag", placeholder="e.g. weak jobs report, FOMC hawkish hold")
                submitted = st.form_submit_button("Save Tag")
                if submitted and tag_text:
                    try:
                        conn.execute(
                            "UPDATE spike_events SET manual_tag = ? WHERE id = ?",
                            (tag_text, int(tag_spike_id))
                        )
                        conn.commit()
                        st.success(f"Tagged spike #{int(tag_spike_id)}: {tag_text}")
                    except Exception as e:
                        st.error(f"Failed to tag: {e}")

            # --- Pattern Cards ---
            st.divider()
            st.markdown("#### Discovered Causal Patterns")
            st.caption("Patterns emerge as more spikes are recorded and tagged")

            try:
                from src.pythia_live.patterns import build_patterns
                from src.pythia_live.database import PythiaDB

                pattern_db = PythiaDB(str(DB_PATH))
                patterns = build_patterns(pattern_db)

                if patterns:
                    for p in patterns[:10]:
                        conf_color = '#10b981' if p.confidence >= 0.7 else '#eab308' if p.confidence >= 0.5 else '#f43f5e'
                        reaction_str = ''
                        if p.avg_asset_reaction:
                            sign = '+' if p.avg_asset_reaction > 0 else ''
                            reaction_str = f" | Avg reaction: {sign}{p.avg_asset_reaction:.1%}"

                        st.markdown(f"""
                        <div class="signal-card" style="border-left-color: {conf_color}; border-radius: 12px;">
                            <b>{p.market_category.upper()}</b> · {p.asset_class} · {p.direction}
                            <br>Avg magnitude: {p.avg_magnitude:.1%} · Samples: {p.sample_size}{reaction_str}
                            <br><span style="color:#a1a1aa">Typical cause: {p.typical_cause or 'untagged'}
                            · Confidence: {p.confidence:.0%}</span>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("No patterns yet — spikes need to accumulate before patterns emerge.")
            except Exception as e:
                st.info(f"Pattern library not available: {e}")

        else:
            st.info("No spike events recorded yet. Start Pythia Live to begin detecting spikes.")
    else:
        st.warning("Database not available")

# ─────────────────────────────────────────────
# Tab 6: Live Events
# ─────────────────────────────────────────────
with tab6:
    st.subheader("Live Market Events")
    st.caption("Real-time view of market events and spikes. Adjust thresholds to filter noise.")

    # Customizable spike threshold
    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        spike_threshold = st.slider("Spike Threshold (%)", 1.0, 20.0, 5.0, 0.5, key="live_spike_threshold",
                                    help="Minimum percentage change to consider an event a spike.")
    with col_t2:
        refresh_rate = st.selectbox("Refresh Rate", ["Every 5s", "Every 10s", "Every 30s", "Every 60s"], index=1,
                                    help="How often to refresh the live data.")
    with col_t3:
        if st.button("🔄 Force Refresh", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()

    # Placeholder for live data - in production, this would connect to a live feed
    st.markdown("#### Recent Events (Last 1 Hour)")
    conn = get_db()
    if conn:
        try:
            # Fetch recent price changes above threshold
            recent_events = pd.read_sql_query("""
                SELECT p.market_id, m.title, m.asset_class, p.yes_price, p.timestamp
                FROM prices p
                JOIN markets m ON p.market_id = m.id
                WHERE p.timestamp > datetime('now', '-1 hour')
                ORDER BY p.timestamp DESC
                LIMIT 100
            """, conn)

            if not recent_events.empty:
                # Calculate price changes
                recent_events = recent_events.sort_values(['market_id', 'timestamp'])
                recent_events['prev_price'] = recent_events.groupby('market_id')['yes_price'].shift(1)
                recent_events['change'] = (recent_events['yes_price'] - recent_events['prev_price']).abs()
                recent_events['change_pct'] = recent_events['change'] / recent_events['prev_price'] * 100
                recent_events = recent_events.dropna(subset=['change'])
                
                # Filter by threshold
                spikes = recent_events[recent_events['change_pct'] >= spike_threshold]
                
                if not spikes.empty:
                    for _, event in spikes.head(10).iterrows():
                        cls = classify_title(event['title'])
                        asset_class = cls['asset_class']
                        badge_class = f"asset-{asset_class}" if asset_class != "general" else ""
                        direction = 'up' if event['change'] > 0 else 'down'
                        color = '#10b981' if direction == 'up' else '#f43f5e'
                        ts = pd.to_datetime(event['timestamp']).strftime('%H:%M:%S')
                        
                        st.markdown(f"""
                        <div class="signal-card signal-medium">
                            <span class="asset-badge {badge_class}">{asset_class}</span>
                            <b>⚡ Spike {direction}</b> · {ts}
                            <br><b>{event['title'][:80]}</b>
                            <br><span style="color:{color}">Change: {event['change_pct']:.1f}%</span>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info(f"No spikes detected above {spike_threshold}% threshold in the last hour.")
            else:
                st.info("No recent events data available.")
        except Exception as e:
            st.error(f"Error fetching live events: {e}")
    else:
        st.warning("Database not available. Is Pythia Live running?")

    st.divider()
    st.markdown("#### Live Data Status")
    st.caption("Status of the live data feed. When Pythia is running, this updates continuously.")
    if DB_PATH.exists():
        mod_time = datetime.fromtimestamp(DB_PATH.stat().st_mtime)
        age_sec = (datetime.now() - mod_time).total_seconds()
        status = "🟢 Live" if age_sec < 120 else "🟡 Stale"
        st.markdown(f"- **Database Status:** {status}")
        st.markdown(f"- **Last Update:** {mod_time.strftime('%H:%M:%S')} ({int(age_sec)}s ago)")
    else:
        st.markdown("- **Database Status:** 🔴 Offline")
        st.markdown("- **Last Update:** Not available")

# Footer
st.divider()
st.caption("Pythia Live v0.5 | Causal Analysis Engine")
