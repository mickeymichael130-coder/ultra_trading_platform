"""
ULTRA Trading Dashboard
Streamlit-based real-time monitoring and control interface.
The dashboard never makes trading decisions. It only displays information.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import sys
import os

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(
    page_title="ULTRA Trading Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header { font-size: 2.5rem; font-weight: bold; color: #1a1a2e; }
    .metric-card { background-color: #f0f2f6; padding: 1rem; border-radius: 0.5rem; }
    .status-running { color: #27ae60; font-weight: bold; }
    .status-stopped { color: #e74c3c; font-weight: bold; }
    .status-warning { color: #f39c12; font-weight: bold; }
    .kill-switch-active { background-color: #ffebee; color: #c62828; padding: 1rem; border-radius: 0.5rem; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


def get_db_connection(db_path="data/trading_bot.db"):
    """Get database connection"""
    if not os.path.exists(db_path):
        return None
    return sqlite3.connect(db_path, check_same_thread=False)


def load_data(conn, query, params=None):
    """Load data from database"""
    if conn is None:
        return pd.DataFrame()
    try:
        return pd.read_sql_query(query, conn, params=params or [])
    except Exception as e:
        st.error(f"Database error: {e}")
        return pd.DataFrame()


# ===== SIDEBAR =====
st.sidebar.markdown("<div class='main-header'>🚀 ULTRA</div>", unsafe_allow_html=True)
st.sidebar.markdown("*Algorithmic Trading Platform*")
st.sidebar.markdown("---")

# Navigation
page = st.sidebar.radio(
    "Navigation",
    ["🏠 Home", "📊 Live Market", "💰 Open Trades", "📈 Performance", 
     "🔔 Signals", "⚙️ Settings", "📋 Logs"]
)

db_path = st.sidebar.text_input("Database Path", value="data/ultra.db")
conn = get_db_connection(db_path)

st.sidebar.markdown("---")
st.sidebar.markdown("**System Status**")

# Check if bot is running (simple file-based check)
pid_file = Path("data/bot.pid")
if pid_file.exists():
    st.sidebar.markdown("<span class='status-running'>● RUNNING</span>", unsafe_allow_html=True)
else:
    st.sidebar.markdown("<span class='status-stopped'>● STOPPED</span>", unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.markdown("v1.0.0 | ULTRA Trading Bot")


# ===== HOME PAGE =====
if page == "🏠 Home":
    st.markdown("<div class='main-header'>🏠 ULTRA Dashboard</div>", unsafe_allow_html=True)
    st.markdown("*Professional Algorithmic Trading Platform*")
    st.markdown("---")

    # Key metrics row
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        balance = load_data(conn, "SELECT balance FROM balance ORDER BY timestamp DESC LIMIT 1")
        bal_val = balance.iloc[0, 0] if not balance.empty else 2000.0
        st.metric("Balance", f"${bal_val:,.2f}")

    with col2:
        trades_today = load_data(conn, 
            "SELECT COUNT(*) as count FROM trades WHERE date(opened_at) = date('now')")
        st.metric("Trades Today", trades_today.iloc[0, 0] if not trades_today.empty else 0)

    with col3:
        open_trades = load_data(conn, 
            "SELECT COUNT(*) as count FROM trades WHERE status = 'filled' AND exit_price IS NULL")
        st.metric("Open Positions", open_trades.iloc[0, 0] if not open_trades.empty else 0)

    with col4:
        pnl_today = load_data(conn, 
            "SELECT COALESCE(SUM(realized_pnl), 0) as pnl FROM trades WHERE date(closed_at) = date('now')")
        pnl_val = pnl_today.iloc[0, 0] if not pnl_today.empty else 0
        st.metric("Today's P&L", f"${pnl_val:,.2f}", delta=f"{pnl_val/20:.1f}%")

    with col5:
        win_rate = load_data(conn, """
            SELECT 
                CASE WHEN COUNT(*) > 0 
                THEN ROUND(100.0 * SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) / COUNT(*), 1)
                ELSE 0 END as win_rate
            FROM trades WHERE realized_pnl IS NOT NULL
        """)
        st.metric("Win Rate", f"{win_rate.iloc[0, 0] if not win_rate.empty else 0:.1f}%")

    st.markdown("---")

    # Risk Status
    st.subheader("🛡️ Risk Status")
    risk_state = load_data(conn, "SELECT * FROM risk_state WHERE id = 1")

    if not risk_state.empty:
        row = risk_state.iloc[0]

        if row['kill_switch_active']:
            st.markdown("<div class='kill-switch-active'>🚨 KILL SWITCH ACTIVE - Trading Halted</div>", 
                       unsafe_allow_html=True)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            drawdown = row['peak_balance'] - row['current_balance']
            drawdown_pct = (drawdown / row['peak_balance'] * 100) if row['peak_balance'] > 0 else 0
            st.metric("Drawdown", f"${drawdown:,.2f}", f"{drawdown_pct:.1f}%")
        with col2:
            st.metric("Daily P&L", f"${row['daily_pnl']:,.2f}")
        with col3:
            st.metric("Daily Trades", int(row['daily_trades']))
        with col4:
            st.metric("Peak Balance", f"${row['peak_balance']:,.2f}")

    # Recent Activity
    st.markdown("---")
    st.subheader("📋 Recent Activity")

    recent = load_data(conn, """
        SELECT symbol, direction, status, realized_pnl, opened_at, reason
        FROM trades ORDER BY opened_at DESC LIMIT 10
    """)
    if not recent.empty:
        st.dataframe(recent, use_container_width=True)
    else:
        st.info("No trades yet. Start the bot to see activity.")


# ===== LIVE MARKET =====
elif page == "📊 Live Market":
    st.markdown("<div class='main-header'>📊 Live Market</div>", unsafe_allow_html=True)

    symbol = st.selectbox("Symbol", ["frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD"])
    timeframe = st.selectbox("Timeframe", ["1m", "5m", "15m", "30m", "1h"], index=2)

    candles = load_data(conn, """
        SELECT epoch, open, high, low, close, volume
        FROM candles WHERE symbol = ? AND timeframe = ?
        ORDER BY epoch DESC LIMIT 200
    """, [symbol, timeframe])

    if not candles.empty:
        candles['datetime'] = pd.to_datetime(candles['epoch'], unit='s')
        candles = candles.sort_values('datetime')

        # Candlestick chart
        fig = go.Figure(data=[go.Candlestick(
            x=candles['datetime'],
            open=candles['open'],
            high=candles['high'],
            low=candles['low'],
            close=candles['close'],
            name=symbol
        )])

        fig.update_layout(
            title=f"{symbol} ({timeframe})",
            yaxis_title="Price",
            xaxis_title="Time",
            height=500
        )

        st.plotly_chart(fig, use_container_width=True)

        # Volume
        fig_vol = go.Figure(data=[go.Bar(
            x=candles['datetime'],
            y=candles['volume'],
            name='Volume',
            marker_color='rgba(100, 100, 255, 0.5)'
        )])
        fig_vol.update_layout(height=200, title="Volume")
        st.plotly_chart(fig_vol, use_container_width=True)
    else:
        st.info("No candle data available. Start the bot to collect data.")


# ===== OPEN TRADES =====
elif page == "💰 Open Trades":
    st.markdown("<div class='main-header'>💰 Open Trades</div>", unsafe_allow_html=True)

    open_trades = load_data(conn, """
        SELECT exec_id, symbol, direction, entry_price, stop_loss, take_profit,
               position_size, risk_amount, opened_at, confidence
        FROM trades WHERE status = 'filled' AND exit_price IS NULL
        ORDER BY opened_at DESC
    """)

    if not open_trades.empty:
        for _, trade in open_trades.iterrows():
            with st.expander(f"{trade['symbol']} {trade['direction']} | Entry: {trade['entry_price']}"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**Stop Loss:** {trade['stop_loss']}")
                    st.write(f"**Take Profit:** {trade['take_profit']}")
                with col2:
                    st.write(f"**Size:** {trade['position_size']}")
                    st.write(f"**Risk:** ${trade['risk_amount']:.2f}")
                with col3:
                    st.write(f"**Confidence:** {trade['confidence']:.2f}")
                    st.write(f"**Opened:** {trade['opened_at']}")
    else:
        st.info("No open positions")


# ===== PERFORMANCE =====
elif page == "📈 Performance":
    st.markdown("<div class='main-header'>📈 Performance Analytics</div>", unsafe_allow_html=True)

    # Performance table
    perf = load_data(conn, "SELECT * FROM performance ORDER BY date DESC LIMIT 30")
    if not perf.empty:
        st.dataframe(perf, use_container_width=True)

        # Equity curve
        trades = load_data(conn, """
            SELECT opened_at, realized_pnl 
            FROM trades WHERE realized_pnl IS NOT NULL
            ORDER BY opened_at
        """)
        if not trades.empty:
            trades['opened_at'] = pd.to_datetime(trades['opened_at'])
            trades['cumulative_pnl'] = trades['realized_pnl'].cumsum()

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=trades['opened_at'],
                y=trades['cumulative_pnl'],
                mode='lines',
                name='Equity Curve',
                line=dict(color='#27ae60', width=2)
            ))
            fig.update_layout(
                title="Equity Curve",
                yaxis_title="Cumulative P&L ($)",
                xaxis_title="Date",
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No performance data yet. Trades need to close first.")


# ===== SIGNALS =====
elif page == "🔔 Signals":
    st.markdown("<div class='main-header'>🔔 Signal History</div>", unsafe_allow_html=True)

    signals = load_data(conn, """
        SELECT symbol, direction, strength, confidence, timestamp, 
               strategy, timeframe, reason, risk_decision, risk_reason
        FROM signals ORDER BY timestamp DESC LIMIT 100
    """)

    if not signals.empty:
        # AI Research Lab notes are stored in signals.reason with an "AI:" prefix.
        signals['has_ai_note'] = signals['reason'].fillna('').astype(str).str.startswith('AI:')

        # Filter
        col1, col2, col3 = st.columns(3)
        with col1:
            direction_filter = st.multiselect("Direction", signals['direction'].unique())
        with col2:
            decision_filter = st.multiselect("Risk Decision", signals['risk_decision'].unique())
        with col3:
            ai_only = st.checkbox("AI-enhanced only", value=False)

        filtered = signals
        if direction_filter:
            filtered = filtered[filtered['direction'].isin(direction_filter)]
        if decision_filter:
            filtered = filtered[filtered['risk_decision'].isin(decision_filter)]
        if ai_only:
            filtered = filtered[filtered['has_ai_note']]

        # AI Research Notes
        st.markdown("---")
        st.subheader("🤖 AI Research Notes")
        ai_notes = filtered[filtered['has_ai_note']]
        if not ai_notes.empty:
            for _, sig in ai_notes.iterrows():
                with st.expander(
                    f"{sig['timestamp']} | {sig['symbol']} {sig['direction']} "
                    f"| {sig['risk_decision']} | conf {sig['confidence']:.2f}"
                ):
                    st.write(sig['reason'])
        else:
            st.info("No AI research notes for the selected signals.")

        # Full history
        st.markdown("---")
        st.subheader("Full Signal History")
        st.dataframe(filtered.drop(columns=['has_ai_note']), use_container_width=True)

        # Signal distribution
        col1, col2 = st.columns(2)
        with col1:
            decision_counts = signals['risk_decision'].value_counts()
            fig = go.Figure(data=[go.Pie(labels=decision_counts.index, values=decision_counts.values)])
            fig.update_layout(title="Risk Decisions")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No signals generated yet.")


# ===== SETTINGS =====
elif page == "⚙️ Settings":
    st.markdown("<div class='main-header'>⚙️ Settings</div>", unsafe_allow_html=True)

    st.subheader("Risk Parameters")
    st.write("These are read-only in dashboard. Edit `config/settings.py` to change.")

    risk_params = {
        "Initial Capital": "$2,000",
        "Max Risk/Trade": "1.5% ($30)",
        "Max Daily Loss": "3% ($60)",
        "Max Drawdown": "10% ($200) → Kill Switch",
        "Max Open Trades": "2",
        "Cooldown After Loss": "15 minutes",
        "Trading Sessions": "London (08-17 UTC) + NY (13-22 UTC)",
        "Symbols": "EUR/USD, GBP/USD, USD/JPY, AUD/USD"
    }

    for param, value in risk_params.items():
        st.text_input(param, value=value, disabled=True)

    st.markdown("---")
    st.subheader("Database")
    db_stats = load_data(conn, """
        SELECT 'candles' as table_name, COUNT(*) as count FROM candles
        UNION ALL SELECT 'trades', COUNT(*) FROM trades
        UNION ALL SELECT 'signals', COUNT(*) FROM signals
        UNION ALL SELECT 'balance', COUNT(*) FROM balance
        UNION ALL SELECT 'performance', COUNT(*) FROM performance
        UNION ALL SELECT 'system_logs', COUNT(*) FROM system_logs
    """)
    if not db_stats.empty:
        st.dataframe(db_stats, use_container_width=True)


# ===== LOGS =====
elif page == "📋 Logs":
    st.markdown("<div class='main-header'>📋 System Logs</div>", unsafe_allow_html=True)

    level_filter = st.selectbox("Log Level", ["ALL", "INFO", "WARNING", "ERROR", "DEBUG"])

    query = """
        SELECT timestamp, level, logger, message
        FROM system_logs
    """
    params = []
    if level_filter != "ALL":
        query += " WHERE level = ?"
        params.append(level_filter)
    query += " ORDER BY timestamp DESC LIMIT 200"

    logs = load_data(conn, query, params)
    if not logs.empty:
        st.dataframe(logs, use_container_width=True)
    else:
        st.info("No logs in database. Check `logs/bot.log` file.")
