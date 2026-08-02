import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.orchestrator import TradingOrchestrator


async def main():
    db_path = tempfile.mkdtemp() + "/binance_paper.db"
    orch = TradingOrchestrator(
        broker_type="binance",
        symbols=["BTCUSDT"],
        mode="paper",
        db_path=db_path,
    )

    async def stop_later():
        await asyncio.sleep(75)
        await orch.shutdown()

    stop = asyncio.create_task(stop_later())
    await orch.start()
    await stop

    s = orch._stats
    print("=" * 50)
    print("STATS")
    for k, v in s.items():
        print(f"  {k}: {v}")
    session = orch.candle_builder.is_session_active("BTCUSDT")
    print("  BTCUSDT session:", session)
    df = orch.candle_builder.get_candles("BTCUSDT", "15m", count=3)
    print("  last 15m candles rows:", len(df))
    if not df.empty:
        print(df[["open", "high", "low", "close"]].tail(2).to_string())
    snap = orch._last_snapshots.get("BTCUSDT")
    if snap:
        print(f"  snapshot atr_pips: {snap.atr_pips:.2f} price: {snap.current_price:.2f}")
    print("=" * 50)


asyncio.run(main())
