"""
ULTRA Algorithmic Trading Platform - Main Entry Point

Usage:
    python main.py --mode paper --broker binance
    python main.py --mode paper
    python main.py --mode live
    python main.py --mode backtest --broker binance

Environment Variables:
    BROKER            - deriv or binance (default: deriv)
    DERIV_APP_ID      - Deriv App ID (default: 1089)
    DERIV_API_TOKEN   - Deriv API Token (required for live)
    TRADING_MODE      - paper, live, or backtest
    LOG_LEVEL         - DEBUG, INFO, WARNING, ERROR
"""
import asyncio
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.orchestrator import TradingOrchestrator
from src.utils.logger import setup_logger
from src.utils.version import get_version


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ULTRA Algorithmic Trading Platform")
    parser.add_argument(
        "--mode", 
        choices=["paper", "live", "backtest"],
        default=os.getenv("TRADING_MODE", "paper"),
        help="Trading mode (default: paper)"
    )
    parser.add_argument(
        "--broker",
        choices=["deriv", "binance"],
        default=os.getenv("BROKER", "deriv"),
        help="Market data broker (default: deriv)"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Symbols to trade (default: broker defaults, e.g. frxEURUSD or BTCUSDT)"
    )
    parser.add_argument(
        "--db",
        default="data/ultra.db",
        help="Database path"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Log level"
    )
    parser.add_argument(
        "--timeframe",
        default="15m",
        help="Timeframe for backtest mode (default: 15m)"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=2000,
        help="Number of candles for backtest mode (default: 2000)"
    )
    return parser.parse_args(argv)


def write_pid_file() -> Path:
    """Write the bot PID so dashboards/healthchecks can see it's running."""
    pid_file = Path("data") / "bot.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    return pid_file


def remove_pid_file(pid_file: Path):
    """Remove the bot PID file."""
    try:
        pid_file.unlink()
    except OSError:
        pass


async def run_backtest(symbols: list, db_path: str, timeframe: str = "15m", count: int = 2000,
                       broker: str = "deriv"):
    """Run backtest on historical candles from DB (fallback: fetch from broker)."""
    from src.database.manager import DatabaseManager
    from src.backtesting.engine import BacktestEngine
    from src.broker.deriv_client import DerivClient
    from src.broker.binance_client import BinanceClient

    broker_cls = BinanceClient if broker == "binance" else DerivClient

    db = DatabaseManager(db_path)

    engine = BacktestEngine(initial_capital=2000)

    for symbol in symbols:
        df = db.get_candles(symbol, timeframe, limit=count)
        if df.empty or len(df) < 200:
            logger.warning(f"No cached candles for {symbol} {timeframe}. Fetching from {broker}...")
            client = broker_cls(app_id=app_id, api_token=api_token)
            if not await client.connect():
                logger.error(f"Could not fetch history for {symbol}. Skipping.")
                continue
            response = await client.fetch_history(symbol, timeframe, count=count)
            candles = response.get("candles", []) if response else []
            rows = [{
                "epoch": c["epoch"], "open": float(c["open"]), "high": float(c["high"]),
                "low": float(c["low"]), "close": float(c["close"]),
                "volume": int(c.get("volume", 0))
            } for c in candles]
            if not rows:
                logger.error(f"No history returned for {symbol}. Skipping.")
                await client.disconnect()
                continue
            import pandas as pd
            df = pd.DataFrame(rows)
            df['datetime'] = pd.to_datetime(df['epoch'], unit='s', utc=True)
            df.set_index('datetime', inplace=True)
            await client.disconnect()
            if len(df) < 200:
                logger.warning(f"Insufficient history for {symbol} ({len(df)} candles). Skipping.")
                continue

        logger.info("=" * 60)
        logger.info(f"BACKTEST: {symbol} | {timeframe} | {len(df)} candles")
        result = engine.run(df, symbol=symbol, timeframe=timeframe)
        logger.info("=" * 60)
        for key, value in result.to_dict().items():
            logger.info(f"  {key}: {value}")

    logger.info("Backtest complete")


async def main():
    global app_id, api_token, logger
    args = parse_args()

    from config.settings import load_config_from_env
    load_config_from_env()

    logger = setup_logger(name="ultra", log_level=args.log_level)

    logger.info(f"ULTRA v{get_version()} | mode={args.mode} | broker={args.broker}")

    app_id = os.getenv("DERIV_APP_ID", "1089")
    api_token = os.getenv("DERIV_API_TOKEN", "")

    if args.mode == "live" and not api_token:
        logger.error("ULTRA: DERIV_API_TOKEN required for live trading")
        logger.error("Set it: export DERIV_API_TOKEN=<your_api_token>")
        sys.exit(1)

    if args.mode == "backtest":
        default_symbols = (
            ["BTCUSDT", "ETHUSDT"] if args.broker == "binance"
            else ["frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD"]
        )
        await run_backtest(
            args.symbols or default_symbols,
            args.db,
            timeframe=args.timeframe,
            count=args.count,
            broker=args.broker
        )
        return

    if args.mode == "live":
        logger.warning("=" * 60)
        logger.warning("⚠️  ULTRA LIVE TRADING MODE")
        logger.warning("Real money is at risk!")
        logger.warning("Press Ctrl+C within 5 seconds to abort...")
        logger.warning("=" * 60)
        await asyncio.sleep(5)

    pid_file = write_pid_file()
    logger.info(f"Bot PID {os.getpid()} written to {pid_file}")

    try:
        orchestrator = TradingOrchestrator(
            app_id=app_id,
            api_token=api_token,
            symbols=args.symbols,
            mode=args.mode,
            db_path=args.db,
            broker_type=args.broker
        )

        await orchestrator.start()

    except KeyboardInterrupt:
        logger.info("ULTRA interrupted by user")
    except Exception as e:
        logger.error(f"ULTRA fatal error: {e}")
        raise
    finally:
        remove_pid_file(pid_file)


if __name__ == "__main__":
    asyncio.run(main())
