"""
Cached plotly figure builders for the dashboard.

Every builder takes a `db_path` (string) as its cache key, so a Streamlit
rerun within the TTL reuses the already-built figure instead of re-querying
SQLite and reconstructing the chart. Returns None when there is no data so
callers can render an empty state.
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit import cache_data

from . import db
from .components import style_figure
from .theme import C

_TTL = 5.0  # seconds — refresh-friendly while staying near-live


def _load(db_path, query, params=None):
    conn = db.get_db_connection(db_path)
    if conn is None:
        return pd.DataFrame()
    return db.load_data(conn, query, params)


@cache_data(ttl=_TTL, show_spinner=False)
def equity_fig(db_path: str):
    """Equity / balance over time. Prefers balance history, falls back to
    cumulative realized P&L."""
    df = _load(db_path, "SELECT timestamp, balance FROM balance ORDER BY timestamp")
    if len(df) >= 2:
        df["ts"] = pd.to_datetime(df["timestamp"])
        df["y"] = df["balance"]
    else:
        df = _load(db_path, "SELECT opened_at, realized_pnl FROM trades "
                            "WHERE realized_pnl IS NOT NULL ORDER BY opened_at")
        if df.empty:
            return None
        df = df.sort_values("opened_at")
        df["ts"] = pd.to_datetime(df["opened_at"])
        df["y"] = df["realized_pnl"].cumsum()
    fig = go.Figure(go.Scatter(x=df["ts"], y=df["y"], mode="lines",
                               line=dict(color=C["primary"], width=2), fill="tozeroy",
                               fillcolor="rgba(59,130,246,0.08)"))
    return style_figure(fig, 340)


@cache_data(ttl=_TTL, show_spinner=False)
def market_fig(db_path: str, symbol: str, timeframe: str, limit: int = 120):
    """Candlestick chart for the most recent candles."""
    df = _load(db_path, """
        SELECT epoch, open, high, low, close, volume FROM candles
        WHERE symbol=? AND timeframe=? ORDER BY epoch DESC LIMIT ?""",
        [symbol, timeframe, limit])
    if df.empty:
        return None
    df = df.sort_values("epoch")
    x = pd.to_datetime(df["epoch"], unit="s")
    fig = go.Figure(go.Candlestick(
        x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color=C["success"], decreasing_line_color=C["danger"]))
    fig.update_layout(showlegend=False)
    return style_figure(fig, 340)


@cache_data(ttl=_TTL, show_spinner=False)
def market_full_fig(db_path: str, symbol: str, timeframe: str, limit: int = 300):
    """Candlestick + volume (two stacked rows) for the Markets page."""
    df = _load(db_path, """
        SELECT epoch, open, high, low, close, volume FROM candles
        WHERE symbol=? AND timeframe=? ORDER BY epoch DESC LIMIT ?""",
        [symbol, timeframe, limit])
    if df.empty:
        return None
    df = df.sort_values("epoch")
    x = pd.to_datetime(df["epoch"], unit="s")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
                        vertical_spacing=0.04)
    fig.add_trace(go.Candlestick(x=x, open=df["open"], high=df["high"],
                                 low=df["low"], close=df["close"],
                                 increasing_line_color=C["success"],
                                 decreasing_line_color=C["danger"], name="Price"),
                  row=1, col=1)
    fig.add_trace(go.Bar(x=x, y=df["volume"], marker_color=C["info"],
                         marker_opacity=0.5, name="Volume"), row=2, col=1)
    fig.update_xaxes(rangeslider_visible=False)
    return style_figure(fig, 560)


@cache_data(ttl=_TTL, show_spinner=False)
def allocation_fig(db_path: str):
    """Portfolio allocation by symbol (open positions, else all trades)."""
    alloc = _load(db_path, """
        SELECT symbol, SUM(position_size) as size FROM trades
        WHERE exit_price IS NULL GROUP BY symbol""")
    if alloc.empty:
        alloc = _load(db_path, "SELECT symbol, COUNT(*) as size FROM trades GROUP BY symbol")
    if alloc.empty:
        return None
    fig = go.Figure(go.Pie(labels=alloc["symbol"], values=alloc["size"], hole=0.55,
                           marker=dict(colors=[C["primary"], C["success"], C["warning"], C["info"]])))
    fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=0, b=0), height=150,
                      paper_bgcolor=C["card"], font=dict(color=C["muted"], size=11))
    return fig


@cache_data(ttl=_TTL, show_spinner=False)
def analytics_figs(db_path: str):
    """Equity, monthly returns, and direction split for the Analytics page.
    Returns (equity_fig, monthly_fig, direction_pie) — any may be None."""
    trades = _load(db_path, "SELECT opened_at, realized_pnl, direction FROM trades "
                            "WHERE realized_pnl IS NOT NULL ORDER BY opened_at")
    if trades.empty:
        return None, None, None
    trades = trades.sort_values("opened_at")
    trades["ts"] = pd.to_datetime(trades["opened_at"])
    trades["month"] = trades["ts"].dt.to_period("M").astype(str)
    trades["cum"] = trades["realized_pnl"].cumsum()

    equity = go.Figure(go.Scatter(x=trades["ts"], y=trades["cum"], mode="lines",
                                  line=dict(color=C["success"], width=2), fill="tozeroy",
                                  fillcolor="rgba(16,185,129,0.08)"))
    equity = style_figure(equity, 320)

    monthly = trades.groupby("month")["realized_pnl"].sum()
    if monthly.empty:
        monthly_fig = None
    else:
        colors = [C["success"] if v >= 0 else C["danger"] for v in monthly.values]
        monthly_fig = go.Figure(go.Bar(x=[str(m) for m in monthly.index], y=list(monthly.values),
                                       marker_color=colors))
        monthly_fig = style_figure(monthly_fig, 320)

    dc = trades["direction"].value_counts()
    if dc.empty:
        dir_pie = None
    else:
        dir_pie = go.Figure(go.Pie(labels=dc.index, values=dc.values, hole=0.55,
                                   marker=dict(colors=[C["success"], C["danger"]])))
        dir_pie.update_layout(showlegend=False, margin=dict(l=0, r=0, t=0, b=0), height=260,
                              paper_bgcolor=C["bg"], font=dict(color=C["muted"]))
    return equity, monthly_fig, dir_pie


@cache_data(ttl=_TTL, show_spinner=False)
def signals_figs(db_path: str):
    """Risk-decision pie + per-symbol signal counts for the Signals page."""
    signals = _load(db_path, "SELECT risk_decision, symbol FROM signals")
    if signals.empty:
        return None, None
    dc = signals["risk_decision"].fillna("unknown").value_counts()
    colors = [C["success"] if k == "accepted" else C["danger"] if k == "rejected" else C["warning"]
              for k in dc.index]
    pie = go.Figure(go.Pie(labels=dc.index, values=dc.values, hole=0.55, marker=dict(colors=colors)))
    pie.update_layout(showlegend=False, margin=dict(l=0, r=0, t=0, b=0), height=260,
                      paper_bgcolor=C["bg"], font=dict(color=C["muted"]))

    sc = signals["symbol"].value_counts()
    bar = go.Figure(go.Bar(x=list(sc.index), y=list(sc.values), marker_color=C["info"]))
    bar = style_figure(bar, 260)
    return pie, bar
