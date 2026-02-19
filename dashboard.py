"""
Pythia Live Web Dashboard
Real-time trading interface
"""

import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path

# Page config
st.set_page_config(
    page_title="Pythia Live | Prediction Market Intelligence",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling
st.markdown("""
<style>
    .main { background-color: #0f1419; }
    .stMetric { background: linear-gradient(135deg, #1a2332 0%, #0f1419 100%); 
                border: 1px solid #2a3441; border-radius: 8px; padding: 15px; }
    div[data-testid="stMetricLabel"] { color: #8b9dc3 !important; font-size: 0.85em; }
    div[data-testid="stMetricValue"] { color: #00d4aa !important; font-size: 1.5em; font-weight: 600; }
    div[data-testid="stMetricDelta"] { color: #ff6b6b !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 32px; background-color: #1a2332; padding: 0 20px; }
    .stTabs [data-baseweb="tab"] { color: #8b9dc3; font-weight: 500; }
    .stTabs [aria-selected="true"] { color: #00d4aa !important; }
    .signal-card { background: #1a2332; border-left: 4px solid #00d4aa; 
                   padding: 15px; margin: 10px 0; border-radius: 0 8px 8px 0; }
    .signal-critical { border-left-color: #ff4757; }
    .signal-high { border-left-color: #ffa502; }
    .signal-medium { border-left-color: #eccc68; }
</style>
""", unsafe_allow_html=True)

# Database connection
@st.cache_resource
def get_db():
    db_path = Path("/Users/xj.ai/.openclaw/workspace/Pythia.live/data/pythia_live.db")
    if db_path.exists():
        return sqlite3.connect(db_path, check_same_thread=False)
    return None

# Load data functions
def load_signals(hours=24, severity=None):
    conn = get_db()
    if not conn:
        return pd.DataFrame()
    
    query = """
        SELECT s.*, m.title, m.source, m.liquidity, m.category
        FROM signals s
        JOIN markets m ON s.market_id = m.id
        WHERE s.timestamp > datetime('now', '-{} hours')
        {}
        ORDER BY s.timestamp DESC
    """.format(hours, f"AND s.severity = '{severity}'" if severity else "")
    
    return pd.read_sql_query(query, conn)

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
        WHERE market_id = ? AND timestamp > datetime('now', '-{} hours')
        ORDER BY timestamp
    """.format(hours), conn, params=(market_id,))

# Header
st.title("🎯 PYTHIA LIVE")
st.caption("Real-time Prediction Market Intelligence | Alpha Detection System")

# Sidebar controls
with st.sidebar:
    st.header("⚙️ Controls")
    
    # Time range
    time_range = st.selectbox(
        "Time Range",
        ["1 Hour", "6 Hours", "24 Hours", "7 Days"],
        index=2
    )
    hours = {"1 Hour": 1, "6 Hours": 6, "24 Hours": 24, "7 Days": 168}[time_range]
    
    # Filters
    st.subheader("Filters")
    severity_filter = st.multiselect(
        "Severity",
        ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        default=["CRITICAL", "HIGH", "MEDIUM"]
    )
    
    signal_types = st.multiselect(
        "Signal Types",
        ["PROBABILITY_SPIKE", "VOLUME_ANOMALY", "MAKER_EDGE", "MOMENTUM_BREAKOUT", "MOMENTUM_BREAKDOWN"],
        default=["PROBABILITY_SPIKE", "MAKER_EDGE", "MOMENTUM_BREAKOUT"]
    )
    
    min_liquidity = st.slider("Min Liquidity ($)", 1000, 100000, 10000, 1000)
    
    st.divider()
    
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_resource.clear()
        st.rerun()
    
    # System status
    st.divider()
    st.subheader("📡 System Status")
    
    db_path = Path("/Users/xj.ai/.openclaw/workspace/Pythia.live/data/pythia_live.db")
    if db_path.exists():
        mod_time = datetime.fromtimestamp(db_path.stat().st_mtime)
        st.success(f"🟢 Database Live\nLast update: {mod_time.strftime('%H:%M:%S')}")
    else:
        st.error("🔴 Database Offline")
        st.info("Start Pythia Live:\n`python run.py`")

# Main content tabs
tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "🚨 Signals", "📈 Markets", "🔬 Analysis"])

# Tab 1: Dashboard
with tab1:
    # Load data
    signals_df = load_signals(hours)
    markets_df = load_markets(min_liquidity)
    
    # KPI Cards
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_signals = len(signals_df)
        st.metric("Total Signals", total_signals, 
                 delta=f"{len(signals_df[signals_df['severity'] == 'CRITICAL'])} Critical" if total_signals > 0 else None)
    
    with col2:
        avg_return = signals_df['expected_return'].mean() if not signals_df.empty else 0
        st.metric("Avg Expected Return", f"{avg_return:.2%}")
    
    with col3:
        active_markets = len(markets_df)
        st.metric("Active Markets", active_markets)
    
    with col4:
        total_liquidity = markets_df['liquidity'].sum() if not markets_df.empty else 0
        st.metric("Total Liquidity", f"${total_liquidity:,.0f}")
    
    st.divider()
    
    # Charts row
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 Signals by Severity")
        if not signals_df.empty:
            severity_counts = signals_df['severity'].value_counts()
            colors = {'CRITICAL': '#ff4757', 'HIGH': '#ffa502', 'MEDIUM': '#eccc68', 'LOW': '#2ed573'}
            fig = px.pie(
                values=severity_counts.values,
                names=severity_counts.index,
                color=severity_counts.index,
                color_discrete_map=colors,
                hole=0.4
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#8b9dc3'
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No signals in selected time range")
    
    with col2:
        st.subheader("📈 Signals Over Time")
        if not signals_df.empty:
            signals_df['timestamp'] = pd.to_datetime(signals_df['timestamp'])
            hourly_signals = signals_df.set_index('timestamp').resample('H').size()
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hourly_signals.index,
                y=hourly_signals.values,
                fill='tozeroy',
                line=dict(color='#00d4aa'),
                name='Signals'
            ))
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#8b9dc3',
                xaxis_gridcolor='#2a3441',
                yaxis_gridcolor='#2a3441'
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data to display")
    
    # Recent high-priority signals
    st.divider()
    st.subheader("🚨 Recent High-Priority Signals")
    
    if not signals_df.empty:
        high_priority = signals_df[signals_df['severity'].isin(['CRITICAL', 'HIGH'])].head(5)
        
        for _, signal in high_priority.iterrows():
            severity_class = f"signal-{signal['severity'].lower()}"
            emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(signal['severity'], "⚪")
            
            with st.container():
                st.markdown(f"""
                <div class="signal-card {severity_class}">
                    <h4>{emoji} {signal['signal_type']} | {signal['title'][:60]}...</h4>
                    <p><b>Severity:</b> {signal['severity']} | 
                       <b>Expected Return:</b> {signal['expected_return']:.2%} | 
                       <b>Time:</b> {signal['timestamp']}</p>
                    <p>{signal['description'][:150]}...</p>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("No high-priority signals detected")

# Tab 2: Signals Feed
with tab2:
    st.header("🚨 Complete Signals Feed")
    
    if not signals_df.empty:
        # Apply filters
        if severity_filter:
            signals_df = signals_df[signals_df['severity'].isin(severity_filter)]
        if signal_types:
            signals_df = signals_df[signals_df['signal_type'].isin(signal_types)]
        
        # Display as table
        display_cols = ['timestamp', 'severity', 'signal_type', 'title', 'expected_return', 'alert_sent']
        st.dataframe(
            signals_df[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                'expected_return': st.column_config.NumberColumn(format="%.2%"),
                'alert_sent': st.column_config.CheckboxColumn()
            }
        )
        
        # Export option
        csv = signals_df.to_csv(index=False)
        st.download_button(
            "📥 Export Signals to CSV",
            csv,
            f"pythia_signals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv"
        )
    else:
        st.warning("No signals found. Is Pythia Live running?")

# Tab 3: Markets
with tab3:
    st.header("📈 Market Overview")
    
    if not markets_df.empty:
        # Category breakdown
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Markets by Category")
            cat_counts = markets_df['category'].value_counts().head(10)
            fig = px.bar(
                x=cat_counts.values,
                y=cat_counts.index,
                orientation='h',
                color=cat_counts.values,
                color_continuous_scale='viridis'
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#8b9dc3'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("Liquidity Distribution")
            fig = px.scatter(
                markets_df,
                x='liquidity',
                y='volume_24h',
                color='source',
                size='liquidity',
                hover_data=['title'],
                log_x=True,
                log_y=True
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#8b9dc3'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Market list
        st.divider()
        st.subheader("Top Markets by Liquidity")
        st.dataframe(
            markets_df[['title', 'source', 'category', 'liquidity', 'volume_24h']].head(20),
            use_container_width=True,
            hide_index=True,
            column_config={
                'liquidity': st.column_config.NumberColumn(format="$%d"),
                'volume_24h': st.column_config.NumberColumn(format="$%d")
            }
        )
    else:
        st.warning("No market data available")

# Tab 4: Analysis
with tab4:
    st.header("🔬 Signal Analysis")
    
    if not signals_df.empty:
        # Performance by signal type
        st.subheader("Expected Returns by Signal Type")
        
        returns_by_type = signals_df.groupby('signal_type')['expected_return'].agg(['mean', 'count'])
        returns_by_type = returns_by_type[returns_by_type['count'] >= 3]  # Min 3 samples
        
        if not returns_by_type.empty:
            fig = px.bar(
                returns_by_type,
                x=returns_by_type.index,
                y='mean',
                error_y=signals_df.groupby('signal_type')['expected_return'].std(),
                labels={'mean': 'Avg Expected Return', 'signal_type': 'Signal Type'}
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#8b9dc3'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Source comparison
        st.divider()
        st.subheader("Signals by Source")
        
        source_stats = signals_df.groupby('source').agg({
            'id': 'count',
            'expected_return': 'mean'
        }).rename(columns={'id': 'signal_count'})
        
        st.dataframe(source_stats, use_container_width=True)
        
        # Alert success rate
        st.divider()
        st.subheader("Alert Delivery Success")
        
        if 'alert_sent' in signals_df.columns:
            alert_stats = signals_df['alert_sent'].value_counts()
            sent_pct = alert_stats.get(1, 0) / len(signals_df) * 100
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Alerts Sent Successfully", f"{sent_pct:.1f}%")
            with col2:
                st.metric("Pending/Dropped", f"{100-sent_pct:.1f}%")
    else:
        st.info("Insufficient data for analysis")

# Footer
st.divider()
st.caption("Pythia Live Dashboard v0.1 | Real-time Prediction Market Intelligence")
