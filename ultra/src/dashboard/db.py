"""
Dashboard database helpers.

Small, defensive wrappers around SQLite so every page degrades gracefully
when the DB file is missing, unreadable, or the schema is still empty.

Query results are cached for a short TTL so a Streamlit rerun (every widget
interaction / refresh) doesn't re-hit SQLite for unchanged data.
"""
import os
import sqlite3

import pandas as pd
from streamlit import cache_data

_CACHE_TTL = 3.0  # seconds — keeps the UI snappy without looking stale


def db_exists(path: str) -> bool:
    return bool(path) and os.path.exists(path)


def get_db_connection(path: str):
    """Open a connection, or None if the DB is missing."""
    if not db_exists(path):
        return None
    try:
        return sqlite3.connect(path, check_same_thread=False)
    except Exception:
        return None


def _conn_path(conn) -> str:
    """Resolve the backing file path for a live connection (for cache keys)."""
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        return row[2] if row else ""
    except Exception:
        return ""


@cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _cached_read(db_path: str, query: str, params):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    try:
        return pd.read_sql_query(query, conn, params=list(params) if params else None)
    finally:
        conn.close()


def load_data(conn, query: str, params=None) -> pd.DataFrame:
    """Run a query; return an empty DataFrame on any failure."""
    if conn is None:
        return pd.DataFrame()
    try:
        path = _conn_path(conn)
        if path:
            return _cached_read(path, query, tuple(params or ()))
        return pd.read_sql_query(query, conn, params=params or [])
    except Exception:
        return pd.DataFrame()


def scalar(conn, query: str, params=None, default=None):
    """Fetch a single value; return `default` when missing/failing."""
    df = load_data(conn, query, params)
    if df.empty:
        return default
    return df.iloc[0, 0]


def first_row(conn, query: str, params=None):
    df = load_data(conn, query, params)
    if df.empty:
        return None
    return df.iloc[0]
