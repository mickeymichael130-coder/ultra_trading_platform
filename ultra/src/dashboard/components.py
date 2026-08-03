"""
Reusable dashboard UI components.

HTML-driven building blocks (KPI cards, badges, page headers) styled by the
global dark theme, plus plotly chart helpers. Kept import-light so the app
stays fast and every component renders safely with empty data.
"""
import streamlit as st

from .theme import C


def page_header(title: str, subtitle: str = ""):
    st.markdown(
        f'<div class="terminal-page-title">{title}</div>'
        f'<div class="terminal-page-sub">{subtitle}</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="border-color:#1E293B; margin-top:0.4rem;">', unsafe_allow_html=True)


def section(title: str):
    st.markdown(
        f'<h3 style="color:{C["body"]}; margin-bottom:0.5rem;">{title}</h3>',
        unsafe_allow_html=True,
    )


def _kpi_cell(label: str, value: str, delta: str, delta_dir: str,
              small: bool, value_color: str) -> str:
    val_style = f"color:{value_color};" if value_color else ""
    small_cls = " small" if small else ""
    delta_html = ""
    if delta:
        arrow = {"up": "▲", "down": "▼", "flat": "•"}.get(delta_dir, "•")
        delta_html = f'<div class="kpi-delta {delta_dir}">{arrow} {delta}</div>'
    return (
        f'<div class="terminal-kpi">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value{small_cls}" style="{val_style}">{value}</div>'
        f'{delta_html}'
        f'</div>'
    )


def kpi(label: str, value: str, delta: str = "", delta_dir: str = "flat",
        small: bool = False, value_color: str = None) -> None:
    """Render one terminal-style KPI card. `delta_dir` in {up,down,flat}."""
    st.markdown(_kpi_cell(label, value, delta, delta_dir, small, value_color),
                unsafe_allow_html=True)


def kpi_row(items, columns=None, gap: float = 0.75) -> None:
    """Render a list of (label, value[, delta[, delta_dir]]) tuples as KPI
    cards. All cells are emitted as ONE HTML grid so a rerun produces a
    single element instead of one per card."""
    n = columns or len(items)
    cells = []
    for item in items:
        label, value = item[0], item[1]
        delta = item[2] if len(item) > 2 else ""
        ddir = item[3] if len(item) > 3 else "flat"
        cells.append(_kpi_cell(label, value, delta, ddir, small=True, value_color=None))
    grid = " ".join(["1fr"] * n)
    st.markdown(
        f'<div style="display:grid;grid-template-columns:{grid};gap:{gap}rem;">'
        f'{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )


def badge(text: str, kind: str = "neutral") -> str:
    """Return an HTML badge span (ok/warn/err/info/neutral)."""
    return f'<span class="terminal-badge {kind}">{text}</span>'


def status_dot(text: str, kind: str = "ok") -> str:
    return f'<span class="terminal-status-dot {kind}">●</span> {text}'


def banner(text: str, kind: str = "danger") -> None:
    st.markdown(f'<div class="terminal-banner">{text}</div>', unsafe_allow_html=True)


def empty(message: str, icon: str = "🗂") -> None:
    st.markdown(
        f'<div style="padding:1.4rem;border:1px dashed {C["border"]};'
        f'border-radius:12px;color:{C["faint"]};text-align:center;">'
        f'<div style="font-size:1.4rem;">{icon}</div>{message}</div>',
        unsafe_allow_html=True,
    )


def db_missing(path: str) -> None:
    empty(f"No database found at <b>{path}</b>. Start the trading engine to generate data.", "⚙️")


def style_figure(fig, height: int = 380):
    """Apply the terminal dark theme to a plotly figure."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C["bg"],
        plot_bgcolor=C["bg"],
        font=dict(color=C["muted"], family="Inter, Segoe UI, sans-serif"),
        height=height,
        margin=dict(l=8, r=8, t=36, b=8),
        title_font=dict(color=C["body"], size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
        xaxis=dict(gridcolor=C["border"], linecolor=C["border"], zerolinecolor=C["border"]),
        yaxis=dict(gridcolor=C["border"], linecolor=C["border"], zerolinecolor=C["border"]),
        hoverlabel=dict(bgcolor=C["card"], font_color=C["text"], bordercolor=C["border"]),
    )
    return fig


def deltas(current: float, previous: float = 0.0):
    """Return (delta_text, delta_dir) for a KPI, tolerating 0 baseline."""
    diff = current - previous
    if previous > 0 and diff != 0:
        pct = diff / previous * 100.0
        return f"{'+' if diff > 0 else ''}{pct:.1f}%", ("up" if diff > 0 else "down")
    if diff > 0:
        return f"+{diff:,.2f}", "up"
    if diff < 0:
        return f"{diff:,.2f}", "down"
    return "", "flat"
