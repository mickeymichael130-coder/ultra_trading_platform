import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.broker.deriv_client import DerivClient


def _env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return ""


async def main():
    app_id = _env("DERIV_APP_ID") or "1089"
    token = _env("DERIV_API_TOKEN")
    if not token:
        print("SKIP: DERIV_API_TOKEN not set in .env (unauthenticated mode OK for market data)")
        sys.exit(0)

    client = DerivClient(app_id=app_id, api_token=token)
    ok = await client.connect()
    print("=" * 50)
    print(f"state: {client.state.value if hasattr(client.state, 'value') else client.state}")
    if not ok:
        print("ERROR: Deriv authentication failed - check DERIV_API_TOKEN / DERIV_APP_ID")
        await client.disconnect()
        sys.exit(1)

    bal = await client.get_balance()
    print(f"account: {bal.broker} balance={bal.balance} {bal.currency} equity={bal.equity}"
          if bal else "account: none")

    ticks = []

    def on_tick(tick):
        ticks.append(tick)

    client.on_tick(on_tick)
    symbol = "frxEURUSD"
    await client.subscribe_ticks(symbol)
    while len(ticks) < 5:
        await asyncio.sleep(1)

    candles = await client.fetch_history(symbol, timeframe="1m", count=10)
    hist = (candles or {}).get("candles") or []

    print(f"ticks received: {len(ticks)}  last={ticks[-1].price if ticks else 'n/a'}")
    print(f"1m history candles: {len(hist)}")
    print("=" * 50)

    await client.disconnect()
    print("OK: Deriv token valid, balance + market data confirmed (paper mode, no orders placed)")


asyncio.run(main())
