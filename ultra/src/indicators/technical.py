"""
Technical Indicator Engine
Calculates indicators from OHLC DataFrames.
Pure functions - no side effects, no broker communication.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, List
from dataclasses import dataclass

from ..utils.logger import get_logger
from ..utils.pips import get_pip_size


@dataclass
class MarketSnapshot:
    """Complete market state for strategy consumption"""
    symbol: str
    timeframe: str
    timestamp: pd.Timestamp

    # Price data
    current_price: float
    open: float
    high: float
    low: float
    close: float

    # EMA
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    ema_trend: Optional[float] = None

    # RSI
    rsi: Optional[float] = None

    # ATR
    atr: Optional[float] = None
    atr_pips: Optional[float] = None

    # MACD
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None

    # Bollinger Bands
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_position: Optional[float] = None  # 0-1 position within bands

    # ADX
    adx: Optional[float] = None
    adx_plus_di: Optional[float] = None
    adx_minus_di: Optional[float] = None

    # Volume
    volume: Optional[int] = None

    # Derived signals
    trend_direction: Optional[str] = None  # "bullish", "bearish", "neutral"
    volatility_regime: Optional[str] = None  # "high", "normal", "low"

    def to_dict(self) -> Dict:
        return {
            k: (round(v, 5) if isinstance(v, float) else v)
            for k, v in self.__dict__.items()
        }


class IndicatorEngine:
    """
    Calculates all technical indicators from candle DataFrame.
    Stateless - takes data, returns snapshot.
    """

    def __init__(
        self,
        ema_fast: int = 12,
        ema_slow: int = 26,
        ema_trend: int = 200,
        rsi_period: int = 14,
        atr_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_period: int = 20,
        bb_std: float = 2.0,
        adx_period: int = 14,
        pip_size: float = 0.0001
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.ema_trend = ema_trend
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.adx_period = adx_period
        self.pip_size = pip_size

        self.logger = get_logger("indicators.engine")

    def _pip_for(self, symbol: str) -> float:
        """Pip size for a symbol (crypto-aware). Falls back to the configured
        forex default when no symbol context is available."""
        if symbol:
            return get_pip_size(symbol)
        return self.pip_size

    def calculate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[MarketSnapshot]:
        """
        Calculate all indicators from candle DataFrame.

        Args:
            df: DataFrame with columns [open, high, low, close, volume]
            symbol: Trading symbol
            timeframe: Candle timeframe

        Returns:
            MarketSnapshot with all indicators
        """
        if df is None or len(df) < self.ema_trend:
            self.logger.warning(f"Insufficient data for {symbol} {timeframe}: {len(df) if df is not None else 0} candles")
            return None

        try:
            # Ensure we have required columns
            required = ['open', 'high', 'low', 'close']
            if not all(col in df.columns for col in required):
                self.logger.error(f"Missing required columns in data for {symbol}")
                return None

            # Get latest values
            latest = df.iloc[-1]
            current_price = latest['close']

            # === EMA Calculations ===
            ema_fast_val = self._ema(df['close'], self.ema_fast).iloc[-1]
            ema_slow_val = self._ema(df['close'], self.ema_slow).iloc[-1]
            ema_trend_val = self._ema(df['close'], self.ema_trend).iloc[-1]

            # === RSI ===
            rsi_val = self._rsi(df['close'], self.rsi_period).iloc[-1]

            # === ATR ===
            atr_val = self._atr(df, self.atr_period).iloc[-1]
            atr_pips = atr_val / self._pip_for(symbol)

            # === MACD ===
            macd_line, macd_signal_line, macd_hist = self._macd(df['close'])

            # === Bollinger Bands ===
            bb_upper, bb_middle, bb_lower = self._bollinger_bands(df['close'])
            bb_pos = self._bb_position(current_price, bb_upper.iloc[-1], bb_lower.iloc[-1])

            # === ADX ===
            adx_val, plus_di, minus_di = self._adx(df)

            # === Trend Direction ===
            trend = self._determine_trend(ema_fast_val, ema_slow_val, ema_trend_val, current_price)

            # === Volatility Regime ===
            volatility = self._determine_volatility(atr_pips)

            snapshot = MarketSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=df.index[-1],
                current_price=current_price,
                open=latest['open'],
                high=latest['high'],
                low=latest['low'],
                close=latest['close'],
                volume=int(latest.get('volume', 0)),

                ema_fast=ema_fast_val,
                ema_slow=ema_slow_val,
                ema_trend=ema_trend_val,

                rsi=rsi_val,

                atr=atr_val,
                atr_pips=atr_pips,

                macd_line=macd_line.iloc[-1],
                macd_signal=macd_signal_line.iloc[-1],
                macd_histogram=macd_hist.iloc[-1],

                bb_upper=bb_upper.iloc[-1],
                bb_middle=bb_middle.iloc[-1],
                bb_lower=bb_lower.iloc[-1],
                bb_position=bb_pos,

                adx=adx_val.iloc[-1],
                adx_plus_di=plus_di.iloc[-1],
                adx_minus_di=minus_di.iloc[-1],

                trend_direction=trend,
                volatility_regime=volatility
            )

            return snapshot

        except Exception as e:
            self.logger.error(f"Indicator calculation error for {symbol}: {e}")
            return None

    # === Indicator Calculations ===

    def _ema(self, series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average"""
        return series.ewm(span=period, adjust=False).mean()

    def _rsi(self, series: pd.Series, period: int) -> pd.Series:
        """Relative Strength Index"""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        # RSI is 100 when there were no losses in the window
        rsi = rsi.where(loss > 0, 100.0)
        return rsi.fillna(50.0)

    def _atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        """Average True Range"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def _macd(
        self,
        series: pd.Series
    ) -> tuple:
        """MACD: line, signal, histogram"""
        ema_fast = self._ema(series, self.macd_fast)
        ema_slow = self._ema(series, self.macd_slow)
        macd_line = ema_fast - ema_slow
        signal_line = self._ema(macd_line, self.macd_signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _bollinger_bands(self, series: pd.Series) -> tuple:
        """Bollinger Bands: upper, middle, lower"""
        middle = series.rolling(window=self.bb_period).mean()
        std = series.rolling(window=self.bb_period).std()
        upper = middle + (std * self.bb_std)
        lower = middle - (std * self.bb_std)
        return upper, middle, lower

    def _bb_position(self, price: float, upper: float, lower: float) -> float:
        """Position within Bollinger Bands (0 = lower, 1 = upper)"""
        if upper == lower:
            return 0.5
        return (price - lower) / (upper - lower)

    def _adx(self, df: pd.DataFrame) -> tuple:
        """Average Directional Index with +DI and -DI"""
        # True Range
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

        # +DM and -DM
        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        # Smoothed
        atr = tr.rolling(window=self.adx_period).mean()
        plus_di = 100 * (plus_dm.rolling(window=self.adx_period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=self.adx_period).mean() / atr)

        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=self.adx_period).mean()

        return adx, plus_di, minus_di

    def _determine_trend(
        self,
        ema_fast: float,
        ema_slow: float,
        ema_trend: float,
        price: float
    ) -> str:
        """Determine trend direction from EMA alignment"""
        if ema_fast > ema_slow > ema_trend and price > ema_fast:
            return "bullish"
        elif ema_fast < ema_slow < ema_trend and price < ema_fast:
            return "bearish"
        else:
            return "neutral"

    def _determine_volatility(self, atr_pips: float) -> str:
        """Classify volatility regime based on ATR in pips"""
        if atr_pips > 20:
            return "high"
        elif atr_pips < 8:
            return "low"
        else:
            return "normal"

    def calculate_all_timeframes(
        self,
        candle_builder,
        symbol: str,
        timeframes: List[str]
    ) -> Dict[str, MarketSnapshot]:
        """Calculate indicators for multiple timeframes"""
        snapshots = {}

        for tf in timeframes:
            df = candle_builder.get_candles(symbol, tf)
            if df is not None and len(df) > 0:
                snapshot = self.calculate(df, symbol, tf)
                if snapshot:
                    snapshots[tf] = snapshot

        return snapshots

    def calculate_series(self, df: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
        """
        Compute full indicator series for every row in one pass.

        All indicators here (EMA, RSI, ATR, MACD, BB, ADX) use only past data,
        so precomputing over the full series produces identical values to
        computing on each growing window. This makes backtesting fast instead
        of O(n^2).

        Args:
            df: Candle DataFrame with open/high/low/close/volume columns.
            symbol: Optional symbol for crypto-aware pip sizing.

        Returns:
            DataFrame indexed like `df` with one column per indicator.
        """
        out = pd.DataFrame(index=df.index)

        # Raw price columns so snapshots can be rebuilt from any row
        out["open"] = df["open"].astype(float)
        out["high"] = df["high"].astype(float)
        out["low"] = df["low"].astype(float)
        out["close"] = df["close"].astype(float)

        ema_fast = self._ema(df['close'], self.ema_fast)
        ema_slow = self._ema(df['close'], self.ema_slow)
        ema_trend = self._ema(df['close'], self.ema_trend)

        rsi = self._rsi(df['close'], self.rsi_period)
        atr = self._atr(df, self.atr_period)

        macd_line, macd_signal, macd_hist = self._macd(df['close'])
        bb_upper, bb_middle, bb_lower = self._bollinger_bands(df['close'])
        adx, plus_di, minus_di = self._adx(df)

        out["ema_fast"] = ema_fast
        out["ema_slow"] = ema_slow
        out["ema_trend"] = ema_trend
        out["rsi"] = rsi
        out["atr"] = atr
        out["atr_pips"] = atr / self._pip_for(symbol)
        out["macd_line"] = macd_line
        out["macd_signal"] = macd_signal
        out["macd_histogram"] = macd_hist
        out["bb_upper"] = bb_upper
        out["bb_middle"] = bb_middle
        out["bb_lower"] = bb_lower
        out["adx"] = adx
        out["adx_plus_di"] = plus_di
        out["adx_minus_di"] = minus_di

        # Vectorized bb_position
        denom = (bb_upper - bb_lower)
        out["bb_position"] = ((df['close'] - bb_lower) / denom).where(denom > 0, 0.5)

        # Vectorized trend direction
        trend = pd.Series("neutral", index=df.index)
        trend[(ema_fast > ema_slow) & (ema_slow > ema_trend) & (df['close'] > ema_fast)] = "bullish"
        trend[(ema_fast < ema_slow) & (ema_slow < ema_trend) & (df['close'] < ema_fast)] = "bearish"
        out["trend_direction"] = trend

        # Vectorized volatility regime
        out["volatility_regime"] = np.select(
            [out["atr_pips"] > 20, out["atr_pips"] < 8],
            ["high", "low"],
            default="normal"
        )

        out["volume"] = df.get("volume", 0)

        return out

    def snapshot_from_row(
        self,
        row: pd.Series,
        symbol: str,
        timeframe: str
    ) -> Optional[MarketSnapshot]:
        """Build a MarketSnapshot from a single row of calculate_series()."""
        price = float(row["close"])
        return MarketSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=row.name,
            current_price=price,
            open=float(row.get("open", price)),
            high=float(row.get("high", price)),
            low=float(row.get("low", price)),
            close=price,
            volume=int(row.get("volume", 0)),
            ema_fast=self._to_float(row.get("ema_fast")),
            ema_slow=self._to_float(row.get("ema_slow")),
            ema_trend=self._to_float(row.get("ema_trend")),
            rsi=self._to_float(row.get("rsi")),
            atr=self._to_float(row.get("atr")),
            atr_pips=self._to_float(row.get("atr_pips")),
            macd_line=self._to_float(row.get("macd_line")),
            macd_signal=self._to_float(row.get("macd_signal")),
            macd_histogram=self._to_float(row.get("macd_histogram")),
            bb_upper=self._to_float(row.get("bb_upper")),
            bb_middle=self._to_float(row.get("bb_middle")),
            bb_lower=self._to_float(row.get("bb_lower")),
            bb_position=self._to_float(row.get("bb_position")),
            adx=self._to_float(row.get("adx")),
            adx_plus_di=self._to_float(row.get("adx_plus_di")),
            adx_minus_di=self._to_float(row.get("adx_minus_di")),
            trend_direction=row.get("trend_direction"),
            volatility_regime=row.get("volatility_regime"),
        )

    @staticmethod
    def _to_float(value) -> Optional[float]:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        return float(value)
