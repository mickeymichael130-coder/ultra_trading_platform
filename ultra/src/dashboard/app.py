"""
ULTRA Terminal — professional trading dashboard.

Streamlit front-end for the ULTRA algorithmic trading platform. Dark,
terminal-style UI with a consistent sidebar across 12 pages.

Design rules:
- The dashboard NEVER makes trading decisions. It only displays information.
- Every page degrades gracefully with a missing or empty database.
- Reusable visual building blocks live in `components.py` / `theme.py`.
"""
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Make `src` (and the project root, for config) importable.
_HERE = Path(__file__).resolve().parent          # src/dashboard
_SRC = _HERE.parent                               # src
_ROOT = _SRC.parent                               # project root (ultra/)
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dashboard import charts
from dashboard.components import (
    badge, banner, db_missing, deltas, empty, kpi_row, page_header,
    section, style_figure,
)
from dashboard.db import first_row, get_db_connection, load_data, scalar
from dashboard.theme import C, apply_theme

st.set_page_config(
    page_title="ULTRA Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_theme()

# === Sidebar ===
st.sidebar.markdown(
    '<div class="terminal-brand"><span class="dot">●</span> ULTRA</div>'
    '<div class="terminal-sub">Algorithmic Trading Terminal</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown("---")

DB_DEFAULT = "data/ultra.db"
db_path = st.sidebar.text_input("Database Path", value=DB_DEFAULT)
conn = get_db_connection(db_path)

NAV_ITEMS = [
    "🏠 Dashboard", "📈 Markets", "🤖 Trading Engine", "💼 Portfolio",
    "📜 Trade History", "📊 Analytics", "🧪 Backtesting", "⚡ Strategy Lab",
    "🛡 Risk Center", "🔔 Signals", "⚙️ Settings", "📋 Logs",
]
page = st.sidebar.radio("Navigation", NAV_ITEMS, label_visibility="collapsed")

st.sidebar.markdown("---")
_running = Path("data/bot.pid").exists()
_kill = scalar(conn, "SELECT kill_switch_active FROM risk_state WHERE id = 1", default=0)
if _kill:
    _status_html = '<span class="terminal-status-dot err">●</span> KILL SWITCH ACTIVE'
elif _running:
    _status_html = '<span class="terminal-status-dot ok">●</span> ENGINE RUNNING'
else:
    _status_html = '<span class="terminal-status-dot warn">●</span> ENGINE OFFLINE'
st.sidebar.markdown(
    f'<div class="terminal-sub">System</div>'
    f'<div style="margin-top:0.35rem;">{_status_html}</div>'
    f'<div class="terminal-sub" style="margin-top:1rem;">ULTRA Terminal v1.0</div>',
    unsafe_allow_html=True,
)


# === Shared helpers ===

def _broker_label() -> str:
    b = os.getenv("BROKER", "").strip().lower()
    if b:
        return {"binance": "Binance", "deriv": "Deriv"}.get(b, b.title())
    try:
        from config.settings import config as _cfg
        return _cfg.broker.broker_type.title()
    except Exception:
        return "—"


def _mode_label() -> str:
    return os.getenv("TRADING_MODE", "paper").title()


def _known_symbols():
    df = load_data(conn, "SELECT DISTINCT symbol FROM candles")
    symbols = df["symbol"].tolist() if not df.empty else []
    defaults = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD"]
    return symbols + [s for s in defaults if s not in symbols] or ["frxEURUSD"]


def _active_symbol():
    return scalar(conn, "SELECT symbol FROM signals ORDER BY timestamp DESC LIMIT 1") \
        or scalar(conn, "SELECT symbol FROM trades ORDER BY opened_at DESC LIMIT 1") \
        or _known_symbols()[0]


def _market_status():
    running = Path("data/bot.pid").exists()
    kill = scalar(conn, "SELECT kill_switch_active FROM risk_state WHERE id = 1", default=0)
    if kill:
        return "HALTED", "err"
    if running:
        return "LIVE", "ok"
    return "OFFLINE", "warn"


def _balance():
    row = first_row(conn, "SELECT balance, equity, margin_used, free_margin "
                          "FROM balance ORDER BY timestamp DESC LIMIT 1")
    if row is not None:
        return row["balance"], row["equity"], row["margin_used"], row["free_margin"]
    bal = scalar(conn, "SELECT current_balance FROM risk_state WHERE id = 1", default=2000.0)
    return bal, None, None, None


def _open_risk():
    return scalar(conn, "SELECT COALESCE(SUM(risk_amount),0) FROM trades WHERE exit_price IS NULL", default=0.0)


def _drawdown():
    rs = first_row(conn, "SELECT current_balance, peak_balance FROM risk_state WHERE id = 1")
    if rs is None or not rs["peak_balance"]:
        return 0.0, 0.0
    peak = float(rs["peak_balance"])
    cur = float(rs["current_balance"])
    dd = peak - cur
    return dd, (dd / peak * 100.0 if peak > 0 else 0.0)


# === Page: Dashboard ===

def page_dashboard():
    page_header("Dashboard", "Live overview of the trading engine")

    bal, equity, margin, free = _balance()
    if conn is None:
        db_missing(db_path)

    pnl_today = scalar(conn, "SELECT COALESCE(SUM(realized_pnl),0) FROM trades "
                             "WHERE closed_at IS NOT NULL AND date(closed_at)=date('now')", default=0.0)
    win_rate = scalar(conn, """
        SELECT CASE WHEN COUNT(*) > 0 THEN
            100.0 * SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) / COUNT(*)
            ELSE 0 END FROM trades WHERE realized_pnl IS NOT NULL""", default=0.0)
    open_pos = scalar(conn, "SELECT COUNT(*) FROM trades WHERE exit_price IS NULL", default=0)
    market, market_kind = _market_status()

    kpi_row([
        ("Balance", f"${bal:,.2f}"),
        ("Daily P&L", f"{pnl_today:+,.2f}"),
        ("Win Rate", f"{win_rate:.1f}%"),
        ("Open Positions", f"{int(open_pos)}"),
        ("Broker", _broker_label()),
        ("Market", market),
    ])
    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)

    col_l, col_r = st.columns([3, 2])
    with col_l:
        section("Equity Curve")
        eq_fig = charts.equity_fig(db_path)
        if eq_fig is not None:
            st.plotly_chart(eq_fig, width="stretch")
        else:
            empty("No equity history yet. Start the engine and close some trades.", "📉")
    with col_r:
        section("Live Market")
        symbol = _active_symbol()
        tf = scalar(conn, "SELECT timeframe FROM candles WHERE symbol=? ORDER BY epoch DESC LIMIT 1",
                    params=[symbol], default="15m")
        fig = charts.market_fig(db_path, symbol, tf, 120)
        if fig is not None:
            st.plotly_chart(fig, width="stretch")
            closes = load_data(conn, """
                SELECT close FROM candles WHERE symbol=? AND timeframe=?
                ORDER BY epoch DESC LIMIT 2""", [symbol, tf])
            if not closes.empty:
                last = closes.iloc[0]["close"]
                prev = closes.iloc[-1]["close"]
                chg, direction = deltas(last, prev)
                st.markdown(f'{symbol} {tf} · {badge(f"{last:,.4f}")} {badge(chg, "ok" if direction == "up" else "err")}',
                            unsafe_allow_html=True)
        else:
            empty(f"No candle data for {symbol} yet.", "📊")

    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        section("Active Strategy")
        strat = scalar(conn, "SELECT strategy FROM signals ORDER BY timestamp DESC LIMIT 1") \
            or scalar(conn, "SELECT strategy FROM trades ORDER BY opened_at DESC LIMIT 1") or "EMACrossover"
        st.markdown(f'<div class="terminal-panel" style="min-height:150px;">'
                    f'<div style="color:{C["muted"]};font-size:0.8rem;">STRATEGY</div>'
                    f'<div style="color:{C["text"]};font-size:1.3rem;font-weight:700;margin-top:0.4rem;">{strat}</div>'
                    f'<div style="color:{C["faint"]};margin-top:0.5rem;">Confirmation: 1h · Min confidence 0.60</div>'
                    f'</div>', unsafe_allow_html=True)
    with c2:
        section("Risk Exposure")
        dd, dd_pct = _drawdown()
        open_risk = _open_risk()
        st.markdown(
            f'<div class="terminal-panel" style="min-height:150px;">'
            f'<div style="color:{C["muted"]};font-size:0.8rem;">DRAWDOWN</div>'
            f'<div style="color:{C["text"]};font-size:1.3rem;font-weight:700;margin-top:0.4rem;">'
            f'${dd:,.2f} <span style="font-size:0.9rem;color:{C["faint"]};">({dd_pct:.1f}%)</span></div>'
            f'<div style="color:{C["faint"]};margin-top:0.5rem;">Open risk: ${open_risk:,.2f}</div>'
            f'</div>', unsafe_allow_html=True)
    with c3:
        section("Portfolio Allocation")
        alloc_fig = charts.allocation_fig(db_path)
        if alloc_fig is not None:
            st.plotly_chart(alloc_fig, width="stretch")
        else:
            st.markdown('<div class="terminal-panel" style="min-height:150px;">'
                        f'<div style="color:{C["faint"]};">No allocation data yet.</div></div>',
                        unsafe_allow_html=True)

    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([3, 3, 2])
    with c1:
        section("Recent Trades")
        recent = load_data(conn, """
            SELECT symbol, direction, status, realized_pnl, opened_at, exit_reason
            FROM trades ORDER BY opened_at DESC LIMIT 8""")
        if not recent.empty:
            st.dataframe(recent, width="stretch", hide_index=True)
        else:
            empty("No trades yet.", "🕘")
    with c2:
        section("System Logs")
        logs = load_data(conn, "SELECT timestamp, level, message FROM system_logs "
                               "ORDER BY timestamp DESC LIMIT 8")
        if not logs.empty:
            st.dataframe(logs, width="stretch", hide_index=True)
        else:
            empty("No engine logs recorded.", "📜")
    with c3:
        section("Notifications")
        notes = load_data(conn, "SELECT timestamp, level, message FROM system_logs "
                                "WHERE level IN ('WARNING','ERROR') ORDER BY timestamp DESC LIMIT 8")
        if not notes.empty:
            for _, r in notes.iterrows():
                kind = "err" if r["level"] == "ERROR" else "warn"
                st.markdown(
                    f'<div style="padding:0.4rem 0;border-bottom:1px solid {C["border"]};'
                    f'font-size:0.82rem;">{badge(r["level"], kind)} '
                    f'<span style="color:{C["body"]};">{r["message"][:90]}</span></div>',
                    unsafe_allow_html=True)
        else:
            empty("No alerts. All clear.", "🔔")


# === Page: Markets ===

def page_markets():
    page_header("Markets", "Live price action across instruments")

    if conn is None:
        db_missing(db_path)

    symbols = _known_symbols()
    c1, c2 = st.columns([1, 1])
    symbol = c1.selectbox("Symbol", symbols)
    tfs = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    tf = c2.selectbox("Timeframe", tfs, index=tfs.index("15m"))

    candles = load_data(conn, """
        SELECT epoch, open, high, low, close, volume FROM candles
        WHERE symbol=? AND timeframe=? ORDER BY epoch DESC LIMIT 300""",
        [symbol, tf])
    if not candles.empty:
        candles = candles.sort_values("epoch")

    if not candles.empty:
        last = candles.iloc[-1]["close"]
        prev = candles.iloc[0]["close"]
        hi = candles["high"].max()
        lo = candles["low"].min()
        chg, direction = deltas(last, prev)
        kpi_row([
            ("Last", f"{last:,.4f}", chg, direction),
            ("Session High", f"{hi:,.4f}"),
            ("Session Low", f"{lo:,.4f}"),
            ("Bars", f"{len(candles)}"),
        ])
        st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)

        fig = charts.market_full_fig(db_path, symbol, tf, 300)
        if fig is not None:
            st.plotly_chart(fig, width="stretch")
    else:
        empty(f"No candle data for {symbol} ({tf}). Start the engine to collect data.", "📊")


# === Page: Trading Engine ===

def page_trading_engine():
    page_header("Trading Engine", "Operational control centre")

    if conn is None:
        db_missing(db_path)

    running = Path("data/bot.pid").exists()
    market, market_kind = _market_status()
    sig = first_row(conn, "SELECT symbol, direction, risk_decision, confidence FROM signals "
                          "ORDER BY timestamp DESC LIMIT 1")
    current_sig = f"{sig['direction']} · {sig['risk_decision']}" if sig is not None else "—"

    kpi_row([
        ("Connection", "CONNECTED" if running else "OFFLINE"),
        ("Broker", _broker_label()),
        ("Mode", _mode_label()),
        ("Strategy", "EMACrossover"),
        ("Symbol", _active_symbol()),
        ("Signal", current_sig, "", "flat"),
    ])
    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        section("Open Position")
        pos = first_row(conn, """
            SELECT symbol, direction, entry_price, stop_loss, take_profit, position_size,
                   risk_amount, opened_at, confidence FROM trades
            WHERE exit_price IS NULL ORDER BY opened_at DESC LIMIT 1""")
        if pos is not None:
            st.markdown(
                f'<div class="terminal-panel">'
                f'<div style="font-size:1.2rem;font-weight:700;color:{C["text"]};">'
                f'{pos["symbol"]} {badge(pos["direction"], "ok" if pos["direction"] == "BUY" else "err")}</div>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.4rem 1rem;margin-top:0.7rem;color:{C["body"]};">'
                f'<div>Entry <span style="color:{C["text"]};float:right;">{pos["entry_price"]:,.4f}</span></div>'
                f'<div>Stop <span style="color:{C["danger"]};float:right;">{pos["stop_loss"]:,.4f}</span></div>'
                f'<div>Target <span style="color:{C["success"]};float:right;">{pos["take_profit"]:,.4f}</span></div>'
                f'<div>Size <span style="color:{C["text"]};float:right;">{pos["position_size"]}</span></div>'
                f'<div>Risk <span style="color:{C["text"]};float:right;">${pos["risk_amount"]:,.2f}</span></div>'
                f'<div>Conf <span style="color:{C["text"]};float:right;">{pos["confidence"]:.2f}</span></div>'
                f'</div></div>', unsafe_allow_html=True)
        else:
            empty("No open positions.", "💼")
    with c2:
        section("System Resources")
        cpu = ram = None
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
        except Exception:
            pass
        if cpu is not None:
            for label, val, kind in (("CPU", cpu, "cpu"), ("RAM", ram, "ram")):
                st.markdown(
                    f'<div class="terminal-panel" style="margin-bottom:0.6rem;">'
                    f'<div style="display:flex;justify-content:space-between;color:{C["muted"]};">'
                    f'<span>{label}</span><span style="color:{C["text"]};">{val:.1f}%</span></div>'
                    f'<div style="background:{C["border"]};height:8px;border-radius:4px;margin-top:0.4rem;">'
                    f'<div style="width:{min(val,100)}%;height:8px;border-radius:4px;'
                    f'background:{C["warning"] if val > 70 else C["success"]};"></div></div></div>',
                    unsafe_allow_html=True)
        else:
            empty("Resource metrics unavailable.", "🖥")
        st.markdown(
            f'<div class="terminal-panel"><div style="color:{C["muted"]};display:flex;'
            f'justify-content:space-between;"><span>Latency (REST ping)</span>'
            f'<span style="color:{C["faint"]};">— ms</span></div></div>',
            unsafe_allow_html=True)


# === Page: Portfolio ===

def page_portfolio():
    page_header("Portfolio", "Account equity and exposure")

    if conn is None:
        db_missing(db_path)

    bal, equity, margin, free = _balance()
    total_pnl = scalar(conn, "SELECT COALESCE(SUM(realized_pnl),0) FROM trades", default=0.0)
    open_risk = _open_risk()
    dd, dd_pct = _drawdown()

    kpi_row([
        ("Total Equity", f"${(equity or bal):,.2f}"),
        ("Available Balance", f"${(free if free is not None else bal):,.2f}"),
        ("Used Margin", f"${(margin or 0.0):,.2f}"),
        ("Open Risk", f"${open_risk:,.2f}"),
        ("Net Profit", f"{total_pnl:+,.2f}", *deltas(total_pnl, 0.0)),
        ("Max Drawdown", f"${dd:,.2f}", f"{dd_pct:.1f}%"),
    ])
    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)
    section("Equity Over Time")
    eq_fig = charts.equity_fig(db_path)
    if eq_fig is not None:
        st.plotly_chart(eq_fig, width="stretch")
    else:
        empty("No equity history yet.", "📉")


# === Page: Trade History ===

def page_trade_history():
    page_header("Trade History", "All executed trades")

    if conn is None:
        db_missing(db_path)

    trades = load_data(conn, "SELECT * FROM trades ORDER BY opened_at DESC")
    if trades.empty:
        empty("No trades recorded yet.", "📜")
        return

    c1, c2 = st.columns(2)
    statuses = c1.multiselect("Status", trades["status"].dropna().unique().tolist())
    directions = c2.multiselect("Direction", trades["direction"].dropna().unique().tolist())

    filtered = trades
    if statuses:
        filtered = filtered[filtered["status"].isin(statuses)]
    if directions:
        filtered = filtered[filtered["direction"].isin(directions)]

    total = len(filtered)
    wins = int((filtered["realized_pnl"] > 0).sum())
    losses = int((filtered["realized_pnl"] < 0).sum())
    net = filtered["realized_pnl"].fillna(0).sum()
    wr = (wins / (wins + losses) * 100.0) if (wins + losses) else 0.0
    kpi_row([
        ("Trades", f"{total}"),
        ("Wins", f"{wins}"),
        ("Losses", f"{losses}"),
        ("Win Rate", f"{wr:.1f}%"),
        ("Net P&L", f"{net:+,.2f}"),
    ])
    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)

    show = filtered.drop(columns=["id"], errors="ignore")
    st.dataframe(show, width="stretch", hide_index=True)


# === Page: Analytics ===

def page_analytics():
    page_header("Analytics", "Performance and strategy metrics")

    if conn is None:
        db_missing(db_path)

    perf = load_data(conn, "SELECT date, total_trades, win_rate, net_pnl, profit_factor, "
                           "max_drawdown FROM performance ORDER BY date")
    if not perf.empty:
        section("Daily Performance")
        st.dataframe(perf, width="stretch", hide_index=True)

    trades = load_data(conn, "SELECT opened_at, realized_pnl, direction FROM trades "
                             "WHERE realized_pnl IS NOT NULL ORDER BY opened_at")
    eq_fig, monthly_fig, dir_pie = charts.analytics_figs(db_path)

    if not trades.empty:
        trades["ts"] = pd.to_datetime(trades["opened_at"])
        c1, c2 = st.columns(2)
        with c1:
            section("Equity Curve")
            if eq_fig is not None:
                st.plotly_chart(eq_fig, width="stretch")
            else:
                empty("No closed trades yet.", "📉")
        with c2:
            section("Monthly Returns")
            if monthly_fig is not None:
                st.plotly_chart(monthly_fig, width="stretch")
            else:
                empty("No closed trades yet.", "📉")

        st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            section("Direction Split")
            if dir_pie is not None:
                st.plotly_chart(dir_pie, width="stretch")
            else:
                empty("No closed trades yet.", "📉")
        with c2:
            section("Win / Loss by Direction")
            agg = trades.groupby("direction")["realized_pnl"].agg(["count", "sum"]).reset_index()
            agg.columns = ["direction", "count", "net_pnl"]
            st.dataframe(agg, width="stretch", hide_index=True)
    else:
        if perf.empty:
            empty("No analytics yet. Close some trades to populate performance data.", "📊")


# === Page: Backtesting ===

def page_backtesting():
    page_header("Backtesting", "Walk-forward validation on historical candles")

    if conn is None:
        db_missing(db_path)

    symbols = _known_symbols()
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    symbol = c1.selectbox("Symbol", symbols)
    tf = c2.selectbox("Timeframe", ["15m", "1m", "5m", "30m", "1h"], index=0)
    bars = c3.slider("Candles", 150, 2000, 500, step=50)
    capital = c4.number_input("Initial Capital", min_value=100.0, value=2000.0, step=100.0)

    if st.button("▶ Run Backtest", type="primary"):
        df = load_data(conn, """
            SELECT epoch, open, high, low, close, volume FROM candles
            WHERE symbol=? AND timeframe=? ORDER BY epoch DESC LIMIT ?""",
            [symbol, tf, bars])
        if df.empty:
            st.warning(f"No candles available for {symbol} ({tf}). Start the engine to collect data.")
            return
        df = df.sort_values("epoch")
        candles = pd.DataFrame({
            "open": df["open"], "high": df["high"], "low": df["low"],
            "close": df["close"], "volume": df["volume"],
        }, index=pd.to_datetime(df["epoch"], unit="s"))

        from backtesting.engine import BacktestEngine
        with st.spinner(f"Running backtest on {len(candles)} candles…"):
            result = BacktestEngine(initial_capital=float(capital)).run(candles, symbol=symbol, timeframe=tf)

        kpi_row([
            ("Net P&L", f"{result.net_pnl:+,.2f}"),
            ("Trades", f"{result.total_trades}"),
            ("Win Rate", f"{result.win_rate:.1f}%"),
            ("Profit Factor", f"{result.profit_factor:.2f}"),
            ("Max Drawdown", f"{result.max_drawdown_pct:.1f}%"),
            ("Sharpe", f"{result.sharpe_ratio:.2f}"),
        ])
        st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)

        if result.equity_curve:
            section("Equity Curve")
            fig = go.Figure(go.Scatter(x=result.equity_times, y=result.equity_curve, mode="lines",
                                       line=dict(color=C["primary"], width=2), fill="tozeroy",
                                       fillcolor="rgba(59,130,246,0.08)"))
            style_figure(fig, 360)
            st.plotly_chart(fig, width="stretch")

        if result.trades:
            section("Trades")
            rows = [{"time": t.entry_time, "direction": t.direction, "entry": round(t.entry_price, 5),
                     "exit": round(t.exit_price, 5), "pnl": round(t.pnl, 2), "exit_reason": t.exit_reason}
                    for t in result.trades]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        empty("Configure a scenario and press **Run Backtest**. Uses the same EMACrossover "
              "strategy + risk rules as live trading.", "🧪")


# === Page: Strategy Lab ===

def _strategy_stats():
    trades = load_data(conn, "SELECT strategy, realized_pnl, status FROM trades")
    if trades.empty:
        return {}
    out = {}
    for strat, grp in trades.groupby("strategy"):
        closed = grp["realized_pnl"].dropna()
        wins = int((closed > 0).sum())
        losses = int((closed < 0).sum())
        wr = (wins / (wins + losses) * 100.0) if (wins + losses) else 0.0
        gp = closed[closed > 0].sum()
        gl = abs(closed[closed < 0].sum())
        pf = (gp / gl) if gl else float("inf") if gp else 0.0
        out[strat] = {"trades": len(grp), "wins": wins, "losses": losses,
                      "win_rate": wr, "profit_factor": pf, "net_pnl": closed.sum()}
    return out


STRATEGIES = [
    ("EMA Cross", "emacross", "12/26 EMA crossover on 15m with ATR-based stops", "primary"),
    ("RSI Reversal", "rsi", "RSI(14) mean-reversion in a trending filter", "success"),
    ("MACD Momentum", "macd", "MACD histogram momentum + higher-timeframe confirmation", "info"),
]


def page_strategy_lab():
    page_header("Strategy Lab", "Compare strategies and performance at a glance")

    if conn is None:
        db_missing(db_path)

    stats = _strategy_stats()
    active_strat = scalar(conn, "SELECT strategy FROM signals ORDER BY timestamp DESC LIMIT 1") or "EMACrossover"

    for name, key, desc, accent in STRATEGIES:
        s = stats.get(name, {})
        with st.container():
            is_active = name == active_strat
            col_c, col_e = st.columns([5, 1])
            with col_c:
                st.markdown(
                    f'<div class="terminal-panel">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                    f'<div style="font-size:1.05rem;font-weight:700;color:{C["text"]};">{name} '
                    f'{"&nbsp;" + badge("ACTIVE", "ok") if is_active else ""}</div>'
                    f'</div>'
                    f'<div style="color:{C["faint"]};font-size:0.82rem;margin-top:0.2rem;">{desc}</div>'
                    f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.6rem;margin-top:0.8rem;">'
                    f'<div><div style="color:{C["faint"]};font-size:0.7rem;">WIN RATE</div>'
                    f'<div style="color:{C["text"]};">{s.get("win_rate", 0):.1f}%</div></div>'
                    f'<div><div style="color:{C["faint"]};font-size:0.7rem;">PROFIT FACTOR</div>'
                    f'<div style="color:{C["text"]};">{s.get("profit_factor", 0):.2f}</div></div>'
                    f'<div><div style="color:{C["faint"]};font-size:0.7rem;">TRADES</div>'
                    f'<div style="color:{C["text"]};">{s.get("trades", 0)}</div></div>'
                    f'<div><div style="color:{C["faint"]};font-size:0.7rem;">NET P&L</div>'
                    f'<div style="color:{C["success"] if s.get("net_pnl", 0) >= 0 else C["danger"]};">'
                    f'{s.get("net_pnl", 0):+,.2f}</div></div>'
                    f'</div></div>', unsafe_allow_html=True)
            with col_e:
                st.toggle("Enable", value=is_active, key=f"strat_{key}",
                          help="Engine control is managed by the bot; this is a display toggle.")
            st.markdown('<div style="height:0.6rem;"></div>', unsafe_allow_html=True)

    st.markdown(
        f'<div class="terminal-sub" style="margin-top:1rem;">Strategy control lives in the trading '
        f'engine. The dashboard only displays state and statistics.</div>', unsafe_allow_html=True)


# === Page: Risk Center ===

def page_risk_center():
    page_header("Risk Center", "Exposure, drawdown and safety switches")

    if conn is None:
        db_missing(db_path)

    dd, dd_pct = _drawdown()
    open_risk = _open_risk()
    bal, *_ = _balance()
    kill = scalar(conn, "SELECT kill_switch_active FROM risk_state WHERE id = 1", default=0)

    if kill:
        banner("🚨 KILL SWITCH ACTIVE — ALL TRADING HALTED")

    c1, c2 = st.columns([1, 1])
    max_daily_loss = c1.number_input("Max Daily Loss ($)", value=60.0, disabled=True)
    risk_per_trade = c2.number_input("Risk Per Trade ($)", value=30.0, disabled=True)

    daily_pnl = scalar(conn, "SELECT COALESCE(SUM(realized_pnl),0) FROM trades "
                             "WHERE closed_at IS NOT NULL AND date(closed_at)=date('now')", default=0.0)
    daily_loss_pct = abs(min(daily_pnl, 0)) / max_daily_loss * 100 if max_daily_loss else 0.0
    dd_limit = 200.0
    dd_used = (dd / dd_limit * 100.0) if dd_limit else 0.0

    kpi_row([
        ("Drawdown", f"${dd:,.2f}", f"{dd_pct:.1f}% of equity"),
        ("Drawdown Limit", f"${dd_limit:,.0f}", f"{dd_used:.0f}% used", "warn" if dd_used > 60 else "ok"),
        ("Open Risk", f"${open_risk:,.2f}"),
        ("Daily Loss", f"{daily_pnl:+,.2f}", f"{daily_loss_pct:.0f}% of limit", "warn" if daily_loss_pct > 60 else "ok"),
        ("Max Open Trades", "2"),
        ("Kill Switch", "ACTIVE" if kill else "ARMED", "", "err" if kill else "ok"),
    ])
    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)

    rs = first_row(conn, "SELECT * FROM risk_state WHERE id = 1")
    if rs is not None:
        section("Risk State")
        st.dataframe(pd.DataFrame([rs.to_dict()]).drop(columns=["id"], errors="ignore"),
                     width="stretch", hide_index=True)

    if st.button("🛑 Emergency Stop (display only)", type="secondary"):
        st.warning("Emergency stop is wired to the engine's kill switch; "
                   "use the engine CLI to halt trading.")


# === Page: Signals ===

def page_signals():
    page_header("Signals", "Signal history, AI research notes and risk decisions")

    if conn is None:
        db_missing(db_path)

    signals = load_data(conn, """
        SELECT symbol, direction, strength, confidence, timestamp, strategy, timeframe,
               reason, risk_decision, risk_reason
        FROM signals ORDER BY timestamp DESC LIMIT 200""")

    if signals.empty:
        empty("No signals generated yet. Start the engine to produce signals.", "🔔")
        return

    signals["has_ai_note"] = signals["reason"].fillna("").astype(str).str.startswith("AI:")

    c1, c2, c3 = st.columns(3)
    direction_filter = c1.multiselect("Direction", signals["direction"].unique().tolist())
    decision_filter = c2.multiselect("Risk Decision", signals["risk_decision"].dropna().unique().tolist())
    ai_only = c3.checkbox("AI-enhanced only", value=False)

    filtered = signals
    if direction_filter:
        filtered = filtered[filtered["direction"].isin(direction_filter)]
    if decision_filter:
        filtered = filtered[filtered["risk_decision"].isin(decision_filter)]
    if ai_only:
        filtered = filtered[filtered["has_ai_note"]]

    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)
    section("🤖 AI Research Notes")
    ai_notes = filtered[filtered["has_ai_note"]]
    if not ai_notes.empty:
        for _, sig in ai_notes.iterrows():
            with st.expander(
                f"{sig['timestamp']} | {sig['symbol']} {sig['direction']} "
                f"| {sig['risk_decision']} | conf {sig['confidence']:.2f}"
            ):
                st.write(sig["reason"])
    else:
        st.info("No AI research notes for the selected signals.")

    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)
    section("Full Signal History")
    st.dataframe(filtered.drop(columns=["has_ai_note"]), width="stretch", hide_index=True)

    pie, bar = charts.signals_figs(db_path)
    c1, c2 = st.columns(2)
    with c1:
        section("Risk Decisions")
        if pie is not None:
            st.plotly_chart(pie, width="stretch")
        else:
            empty("No signals yet.", "🔔")
    with c2:
        section("Signal Distribution")
        if bar is not None:
            st.plotly_chart(bar, width="stretch")
        else:
            empty("No signals yet.", "🔔")


# === Page: Settings ===

def page_settings():
    page_header("Settings", "Configuration overview (read-only)")

    if conn is None:
        db_missing(db_path)

    section("Risk Parameters")
    st.markdown(
        f'<div class="terminal-panel">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<tr><td style="padding:0.4rem 0;color:{C["muted"]};">Initial Capital</td>'
        f'<td style="text-align:right;color:{C["text"]};">$2,000</td></tr>'
        f'<tr><td style="padding:0.4rem 0;color:{C["muted"]};">Max Risk / Trade</td>'
        f'<td style="text-align:right;color:{C["text"]};">1.5% ($30)</td></tr>'
        f'<tr><td style="padding:0.4rem 0;color:{C["muted"]};">Max Daily Loss</td>'
        f'<td style="text-align:right;color:{C["text"]};">3% ($60)</td></tr>'
        f'<tr><td style="padding:0.4rem 0;color:{C["muted"]};">Max Drawdown</td>'
        f'<td style="text-align:right;color:{C["text"]};">10% ($200) → Kill Switch</td></tr>'
        f'<tr><td style="padding:0.4rem 0;color:{C["muted"]};">Max Open Trades</td>'
        f'<td style="text-align:right;color:{C["text"]};">2</td></tr>'
        f'<tr><td style="padding:0.4rem 0;color:{C["muted"]};">Sessions</td>'
        f'<td style="text-align:right;color:{C["text"]};">London + NY (crypto 24/7)</td></tr>'
        f'<tr><td style="padding:0.4rem 0;color:{C["muted"]};">Primary Timeframe</td>'
        f'<td style="text-align:right;color:{C["text"]};">15m (confirmation 1h)</td></tr>'
        f'</table></div>', unsafe_allow_html=True)

    st.markdown('<hr style="border-color:#1E293B;">', unsafe_allow_html=True)
    section("Database")
    db_stats = load_data(conn, """
        SELECT 'candles' as table_name, COUNT(*) as count FROM candles
        UNION ALL SELECT 'trades', COUNT(*) FROM trades
        UNION ALL SELECT 'signals', COUNT(*) FROM signals
        UNION ALL SELECT 'balance', COUNT(*) FROM balance
        UNION ALL SELECT 'performance', COUNT(*) FROM performance
        UNION ALL SELECT 'system_logs', COUNT(*) FROM system_logs
    """)
    if not db_stats.empty:
        st.dataframe(db_stats, width="stretch", hide_index=True)


# === Page: Logs ===

def page_logs():
    page_header("Logs", "Engine log stream with filtering")

    if conn is None:
        db_missing(db_path)

    c1, c2 = st.columns([1, 2])
    level = c1.selectbox("Level", ["ALL", "INFO", "WARNING", "ERROR", "DEBUG"])
    search = c2.text_input("Search", placeholder="Filter by keyword…")

    query = "SELECT timestamp, level, logger, message FROM system_logs"
    params = []
    clauses = []
    if level != "ALL":
        clauses.append("level = ?")
        params.append(level)
    if search.strip():
        clauses.append("message LIKE ?")
        params.append(f"%{search.strip()}%")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY timestamp DESC LIMIT 300"

    logs = load_data(conn, query, params)
    if not logs.empty:
        colored = []
        for _, r in logs.iterrows():
            kind = {"ERROR": "err", "WARNING": "warn", "INFO": "info"}.get(r["level"], "neutral")
            colored.append({
                "time": r["timestamp"], "level": r["level"], "logger": r["logger"],
                "message": r["message"],
            })
        st.dataframe(pd.DataFrame(colored), width="stretch", hide_index=True)
    else:
        empty("No logs in the database. Check `logs/bot.log` on disk.", "📜")


# === Dispatch ===

if page == "🏠 Dashboard":
    page_dashboard()
elif page == "📈 Markets":
    page_markets()
elif page == "🤖 Trading Engine":
    page_trading_engine()
elif page == "💼 Portfolio":
    page_portfolio()
elif page == "📜 Trade History":
    page_trade_history()
elif page == "📊 Analytics":
    page_analytics()
elif page == "🧪 Backtesting":
    page_backtesting()
elif page == "⚡ Strategy Lab":
    page_strategy_lab()
elif page == "🛡 Risk Center":
    page_risk_center()
elif page == "🔔 Signals":
    page_signals()
elif page == "⚙️ Settings":
    page_settings()
elif page == "📋 Logs":
    page_logs()

st.markdown('<div class="terminal-footer">ULTRA Terminal · read-only monitoring UI · '
            'engine decisions are made by the bot, not the dashboard</div>', unsafe_allow_html=True)
