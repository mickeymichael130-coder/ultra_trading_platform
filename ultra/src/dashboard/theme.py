"""
ULTRA Terminal visual theme.

Dark, high-contrast palette tuned for professional trading terminals.
Centralizes colors + the global CSS so pages only inject HTML fragments.
"""
import streamlit as st

# === Palette (dark theme, trading-terminal style) ===
C = {
    "bg": "#0F172A",          # app background
    "sidebar": "#111827",     # sidebar background
    "card": "#1E293B",        # cards / panels
    "card_alt": "#182338",    # subtle card gradient end
    "border": "#334155",      # borders
    "text": "#F8FAFC",        # primary text (near-white)
    "body": "#CBD5E1",        # body text
    "muted": "#94A3B8",       # secondary text
    "faint": "#64748B",       # labels / captions
    "primary": "#3B82F6",     # blue accent
    "primary_dim": "#1D4ED8",
    "success": "#10B981",     # green
    "success_dim": "#065F46",
    "warning": "#F59E0B",     # amber
    "warning_dim": "#92400E",
    "danger": "#EF4444",      # red
    "danger_dim": "#7F1D1D",
    "info": "#38BDF8",        # cyan
}

_FONT = "'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif"

_CSS = f"""
<style>
:root {{
    --bg: {C['bg']}; --card: {C['card']}; --border: {C['border']};
    --text: {C['text']}; --muted: {C['muted']}; --primary: {C['primary']};
    --success: {C['success']}; --warning: {C['warning']}; --danger: {C['danger']};
}}

html, body, [data-testid="stAppViewContainer"] {{
    background: {C['bg']};
    color: {C['body']};
    font-family: {_FONT};
}}
[data-testid="stHeader"] {{ background: transparent; }}

.block-container {{ padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1400px; }}

/* ---- Sidebar ---- */
[data-testid="stSidebar"] {{
    background: {C['sidebar']};
    border-right: 1px solid {C['border']};
}}
[data-testid="stSidebar"] hr {{ border-color: #1E293B; }}
[data-testid="stSidebar"] .stTextInput input,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span {{ color: {C['muted']}; }}
[data-testid="stSidebar"] .stTextInput input {{
    background: #0B1220; border: 1px solid {C['border']}; border-radius: 8px;
}}

/* Sidebar radio = nav. Hide the radio circles so it reads as a nav menu. */
[data-testid="stSidebar"] [data-testid="stRadio"] label {{
    color: {C['body']}; padding: 0.35rem 0.6rem; border-radius: 8px;
    transition: background .15s ease;
}}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {{
    background: #1E293B; color: {C['text']};
}}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {{
    background: {C['card']}; color: {C['primary']};
    border-left: 3px solid {C['primary']};
}}

/* ---- Headings ---- */
h1, h2, h3, h4 {{ color: {C['text']}; font-family: {_FONT}; letter-spacing: -0.01em; }}
h1 {{ font-size: 1.55rem; font-weight: 700; }}
h2 {{ font-size: 1.15rem; font-weight: 600; }}
h3 {{ font-size: 1.0rem; font-weight: 600; color: {C['body']}; }}

/* ---- Buttons / inputs ---- */
.stButton > button {{
    background: {C['card']}; color: {C['text']};
    border: 1px solid {C['border']}; border-radius: 8px;
    font-weight: 500; transition: all .15s ease;
}}
.stButton > button:hover {{ border-color: {C['primary']}; color: {C['primary']}; }}
.stTextInput input, .stNumberInput input, .stSelectbox [data-baseweb="select"] > div,
.stDateInput input, .stTextArea textarea {{
    background: #0B1220; color: {C['body']}; border-radius: 8px;
}}
.stSelectbox [data-baseweb="select"] > div {{ border-color: {C['border']}; }}

/* ---- Metrics (native st.metric) ---- */
[data-testid="stMetric"] {{
    background: {C['card']}; border: 1px solid {C['border']};
    border-radius: 10px; padding: 0.7rem 1rem;
}}
[data-testid="stMetricLabel"] {{ color: {C['faint']}; font-size: 0.72rem; }}
[data-testid="stMetricValue"] {{ color: {C['text']}; font-size: 1.35rem; font-weight: 700; }}

/* ---- Dataframes / tables ---- */
[data-testid="stDataFrame"] {{ border: 1px solid {C['border']}; border-radius: 10px; overflow: hidden; }}

/* ---- Expanders ---- */
[data-testid="stExpander"] details {{
    background: {C['card']}; border: 1px solid {C['border']};
    border-radius: 10px;
}}
[data-testid="stExpander"] summary {{ color: {C['body']}; }}

/* ---- Tabs ---- */
.stTabs [data-baseweb="tab-list"] {{ border-bottom: 1px solid {C['border']}; }}
.stTabs [data-baseweb="tab"] {{ color: {C['muted']}; font-weight: 500; }}
.stTabs [aria-selected="true"] {{ color: {C['primary']} !important; }}

/* ---- Custom HTML building blocks ---- */
.terminal-brand {{ font-size: 1.35rem; font-weight: 800; color: {C['text']}; letter-spacing: 0.02em; }}
.terminal-brand .dot {{ color: {C['success']}; }}
.terminal-sub {{ font-size: 0.72rem; color: {C['faint']}; letter-spacing: 0.12em; text-transform: uppercase; }}

.terminal-kpi {{
    background: linear-gradient(180deg, {C['card']}, {C['card_alt']});
    border: 1px solid {C['border']}; border-radius: 12px;
    padding: 0.85rem 1rem; min-height: 92px;
}}
.terminal-kpi .kpi-label {{
    color: {C['faint']}; font-size: 0.7rem; font-weight: 600;
    letter-spacing: 0.09em; text-transform: uppercase;
}}
.terminal-kpi .kpi-value {{ color: {C['text']}; font-size: 1.5rem; font-weight: 700; margin-top: 0.25rem; }}
.terminal-kpi .kpi-value.small {{ font-size: 1.15rem; }}
.terminal-kpi .kpi-delta {{ font-size: 0.78rem; margin-top: 0.15rem; }}
.terminal-kpi .kpi-delta.up {{ color: {C['success']}; }}
.terminal-kpi .kpi-delta.down {{ color: {C['danger']}; }}
.terminal-kpi .kpi-delta.flat {{ color: {C['faint']}; }}

.terminal-badge {{
    display: inline-block; padding: 0.14rem 0.6rem; border-radius: 999px;
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.04em;
}}
.terminal-badge.ok {{ background: {C['success_dim']}; color: {C['success']}; }}
.terminal-badge.warn {{ background: {C['warning_dim']}; color: {C['warning']}; }}
.terminal-badge.err {{ background: {C['danger_dim']}; color: {C['danger']}; }}
.terminal-badge.info {{ background: #1E3A8A; color: {C['info']}; }}
.terminal-badge.neutral {{ background: {C['card']}; color: {C['muted']}; border: 1px solid {C['border']}; }}

.terminal-status-dot {{ font-size: 0.8rem; }}
.terminal-status-dot.ok {{ color: {C['success']}; }}
.terminal-status-dot.warn {{ color: {C['warning']}; }}
.terminal-status-dot.err {{ color: {C['danger']}; }}

.terminal-page-title {{ color: {C['text']}; font-size: 1.5rem; font-weight: 700; }}
.terminal-page-sub {{ color: {C['faint']}; font-size: 0.85rem; margin-top: -0.2rem; }}

.terminal-banner {{
    padding: 0.7rem 1rem; border-radius: 10px; font-weight: 600;
    border: 1px solid {C['danger']}; background: {C['danger_dim']}; color: {C['danger']};
}}

.terminal-panel {{
    background: {C['card']}; border: 1px solid {C['border']};
    border-radius: 12px; padding: 1rem;
}}

.terminal-mono {{ font-family: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace; font-size: 0.85rem; }}
.terminal-footer {{ color: {C['faint']}; font-size: 0.72rem; text-align: center; margin-top: 1rem; }}
</style>
"""


def apply_theme():
    """Inject the global dark theme CSS. Call once, before rendering content."""
    st.markdown(_CSS, unsafe_allow_html=True)
