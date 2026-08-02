"""
Database Layer
SQLite for local state persistence.
Everything is stored: trades, candles, balance, performance, logs.
Nothing is lost. State survives restarts.
"""
import sqlite3
import json
import pandas as pd
from typing import Optional, Dict, List, Any
from datetime import datetime
from pathlib import Path
import threading

from ..utils.logger import get_logger


class DatabaseManager:
    """SQLite database manager for trading bot."""

    def __init__(self, db_path: str = "data/trading_bot.db"):
        self.db_path = db_path
        self.logger = get_logger("database.manager")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()
        self.logger.info(f"Database initialized: {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_schema(self):
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, timeframe, epoch)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exec_id TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                strategy TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                stop_loss REAL,
                take_profit REAL,
                position_size REAL,
                risk_amount REAL,
                realized_pnl REAL,
                status TEXT NOT NULL,
                mode TEXT NOT NULL,
                opened_at TIMESTAMP,
                closed_at TIMESTAMP,
                exit_reason TEXT,
                confidence REAL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS balance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                balance REAL NOT NULL,
                equity REAL,
                margin_used REAL,
                free_margin REAL,
                currency TEXT DEFAULT 'USD',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS risk_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_balance REAL NOT NULL,
                peak_balance REAL NOT NULL,
                daily_pnl REAL DEFAULT 0,
                daily_trades INTEGER DEFAULT 0,
                kill_switch_active INTEGER DEFAULT 0,
                last_loss_time TIMESTAMP,
                today_date TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                strength TEXT,
                confidence REAL,
                timestamp TIMESTAMP,
                strategy TEXT,
                timeframe TEXT,
                reason TEXT,
                risk_decision TEXT,
                risk_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                losing_trades INTEGER DEFAULT 0,
                win_rate REAL,
                gross_profit REAL DEFAULT 0,
                gross_loss REAL DEFAULT 0,
                net_pnl REAL DEFAULT 0,
                profit_factor REAL,
                max_drawdown REAL DEFAULT 0,
                avg_win REAL,
                avg_loss REAL,
                largest_win REAL,
                largest_loss REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                logger TEXT NOT NULL,
                message TEXT NOT NULL,
                module TEXT,
                function TEXT,
                line INTEGER,
                extra TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf ON candles(symbol, timeframe, epoch)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_balance_time ON balance(timestamp)")
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM risk_state")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO risk_state (id, current_balance, peak_balance, today_date) VALUES (1, 2000.0, 2000.0, ?)", (datetime.utcnow().date().isoformat(),))
            conn.commit()

    # === Candle Operations ===

    def save_candles(self, candles_df: pd.DataFrame, symbol: str, timeframe: str):
        if candles_df.empty:
            return
        conn = self._get_connection()
        records = []
        for _, row in candles_df.iterrows():
            epoch = int(row.name.timestamp()) if hasattr(row.name, 'timestamp') else int(row['epoch'])
            records.append((
                symbol, timeframe, epoch,
                float(row['open']), float(row['high']),
                float(row['low']), float(row['close']),
                int(row.get('volume', 0))
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO candles 
            (symbol, timeframe, epoch, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        conn.commit()

    def get_candles(self, symbol: str, timeframe: str, limit: int = 1000, since: Optional[datetime] = None) -> pd.DataFrame:
        conn = self._get_connection()
        query = "SELECT epoch, open, high, low, close, volume FROM candles WHERE symbol = ? AND timeframe = ?"
        params = [symbol, timeframe]
        if since:
            query += " AND epoch >= ?"
            params.append(int(since.timestamp()))
        query += " ORDER BY epoch DESC LIMIT ?"
        params.append(limit)
        df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            df['datetime'] = pd.to_datetime(df['epoch'], unit='s', utc=True)
            df.set_index('datetime', inplace=True)
        return df

    # === Trade Operations ===

    def save_trade(self, trade: Dict):
        conn = self._get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO trades (
                exec_id, symbol, direction, strategy, timeframe,
                entry_price, exit_price, stop_loss, take_profit,
                position_size, risk_amount, realized_pnl, status,
                mode, opened_at, closed_at, exit_reason, confidence, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.get('exec_id'), trade.get('symbol'), trade.get('direction'),
            trade.get('strategy'), trade.get('timeframe'),
            trade.get('entry_price'), trade.get('exit_price'),
            trade.get('stop_loss'), trade.get('take_profit'),
            trade.get('position_size'), trade.get('risk_amount'),
            trade.get('realized_pnl'), trade.get('status'),
            trade.get('mode'), trade.get('opened_at'),
            trade.get('closed_at'), trade.get('exit_reason'),
            trade.get('confidence'), trade.get('reason')
        ))
        conn.commit()

    def update_trade(self, exec_id: str, updates: Dict):
        conn = self._get_connection()
        fields = []
        values = []
        for key, value in updates.items():
            fields.append(f"{key} = ?")
            values.append(value)
        values.append(exec_id)
        query = f"UPDATE trades SET {', '.join(fields)} WHERE exec_id = ?"
        conn.execute(query, values)
        conn.commit()

    def get_trades(self, status: Optional[str] = None, symbol: Optional[str] = None, limit: int = 100) -> pd.DataFrame:
        conn = self._get_connection()
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY opened_at DESC LIMIT ?"
        params.append(limit)
        return pd.read_sql_query(query, conn, params=params)

    def get_signals(self, symbol: Optional[str] = None, limit: int = 100) -> pd.DataFrame:
        """Fetch recorded signals (newest first), optional symbol filter."""
        conn = self._get_connection()
        query = "SELECT * FROM signals WHERE 1=1"
        params = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        return pd.read_sql_query(query, conn, params=params)

    # === Balance Operations ===

    def save_balance(self, balance: float, equity: Optional[float] = None, 
                     margin_used: Optional[float] = None, free_margin: Optional[float] = None):
        conn = self._get_connection()
        conn.execute("""
            INSERT INTO balance (balance, equity, margin_used, free_margin)
            VALUES (?, ?, ?, ?)
        """, (balance, equity, margin_used, free_margin))
        conn.commit()

    def get_latest_balance(self) -> Optional[float]:
        conn = self._get_connection()
        cursor = conn.execute("SELECT balance FROM balance ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None

    # === Risk State Operations ===

    def save_risk_state(self, state: Dict):
        conn = self._get_connection()
        conn.execute("""
            UPDATE risk_state SET
                current_balance = ?,
                peak_balance = ?,
                daily_pnl = ?,
                daily_trades = ?,
                kill_switch_active = ?,
                last_loss_time = ?,
                today_date = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (
            state.get('current_balance', 2000.0),
            state.get('peak_balance', 2000.0),
            state.get('daily_pnl', 0.0),
            state.get('daily_trades', 0),
            1 if state.get('kill_switch_active', False) else 0,
            state.get('last_loss_time'),
            state.get('today_date', datetime.utcnow().date().isoformat())
        ))
        conn.commit()

    def load_risk_state(self) -> Dict:
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM risk_state WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return {
                'current_balance': row['current_balance'],
                'peak_balance': row['peak_balance'],
                'daily_pnl': row['daily_pnl'],
                'daily_trades': row['daily_trades'],
                'kill_switch_active': bool(row['kill_switch_active']),
                'last_loss_time': row['last_loss_time'],
                'today_date': row['today_date']
            }
        return {}

    # === Signal Operations ===

    def save_signal(self, signal: Dict, risk_decision: str = "HOLD", risk_reason: str = ""):
        conn = self._get_connection()
        conn.execute("""
            INSERT INTO signals 
            (symbol, direction, strength, confidence, timestamp, strategy, 
             timeframe, reason, risk_decision, risk_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.get('symbol'), signal.get('direction'),
            signal.get('strength'), signal.get('confidence'),
            signal.get('timestamp'), signal.get('strategy'),
            signal.get('timeframe'), signal.get('reason'),
            risk_decision, risk_reason
        ))
        conn.commit()

    # === Performance Operations ===

    def update_daily_performance(self, date: str, metrics: Dict):
        conn = self._get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO performance (
                date, total_trades, winning_trades, losing_trades,
                win_rate, gross_profit, gross_loss, net_pnl,
                profit_factor, max_drawdown, avg_win, avg_loss,
                largest_win, largest_loss
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date, metrics.get('total_trades', 0), metrics.get('winning_trades', 0),
            metrics.get('losing_trades', 0), metrics.get('win_rate'),
            metrics.get('gross_profit', 0), metrics.get('gross_loss', 0),
            metrics.get('net_pnl', 0), metrics.get('profit_factor'),
            metrics.get('max_drawdown', 0), metrics.get('avg_win'),
            metrics.get('avg_loss'), metrics.get('largest_win'),
            metrics.get('largest_loss')
        ))
        conn.commit()

    def get_performance(self, days: int = 30) -> pd.DataFrame:
        conn = self._get_connection()
        return pd.read_sql_query("""
            SELECT * FROM performance 
            ORDER BY date DESC LIMIT ?
        """, conn, params=(days,))

    # === Log Operations ===

    def save_log(self, log_entry: Dict):
        conn = self._get_connection()
        conn.execute("""
            INSERT INTO system_logs 
            (timestamp, level, logger, message, module, function, line, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_entry.get('timestamp'), log_entry.get('level'),
            log_entry.get('logger'), log_entry.get('message'),
            log_entry.get('module'), log_entry.get('function'),
            log_entry.get('line'), json.dumps(log_entry.get('extra', {}))
        ))
        conn.commit()

    # === Maintenance ===

    def cleanup_old_data(self, candle_days: int = 365, log_days: int = 30):
        conn = self._get_connection()
        conn.execute(f"DELETE FROM candles WHERE epoch < strftime('%s', 'now', '-{candle_days} days')")
        conn.execute(f"DELETE FROM system_logs WHERE created_at < datetime('now', '-{log_days} days')")
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
        self.logger.info(f"Database cleanup completed. Retained: candles={candle_days}d, logs={log_days}d")

    def get_stats(self) -> Dict:
        conn = self._get_connection()
        cursor = conn.cursor()
        stats = {}
        for table in ['candles', 'trades', 'balance', 'signals', 'performance', 'system_logs']:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]
        cursor.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
        size_row = cursor.fetchone()
        stats['size_bytes'] = size_row[0] if size_row else 0
        return stats
