"""Lighter DEX integration test — testnet.

Opens 3 BTC market positions simultaneously at $200 each, verifies they
appear on the exchange, then closes the combined position.

Fetches live BTC price from mainnet for accurate sizing.
Uses the production LighterClient with hardcoded testnet credentials.

Usage:
    python test_client_live.py
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from backend.services.lighter_client import LighterClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# --- Testnet credentials (hardcoded) ---
TESTNET_HOST = "https://testnet.zklighter.elliot.ai"
MAINNET_HOST = "https://mainnet.zklighter.elliot.ai"
PRIVATE_KEY = "098df0e805aee76a9c59e77d5b82d163e2e2a21d4914ced02b97367416cf292a6d2476d89ab5461d"
API_KEY_INDEX = 4
ACCOUNT_INDEX = 67

BTC_MARKET_INDEX = 1
NOTIONAL_PER_ORDER = 200.0  # $200 per order
NUM_ORDERS = 3
SLIPPAGE = 0.02


async def get_btc_price() -> float:
    """Fetch live BTC mid-price from mainnet orderbook."""
    import lighter

    config = lighter.Configuration(host=MAINNET_HOST)
    api_client = lighter.ApiClient(configuration=config)
    try:
        order_api = lighter.OrderApi(api_client)
        resp = await order_api.order_book_orders(market_id=BTC_MARKET_INDEX, limit=1)
        best_ask = float(resp.asks[0].price) if resp.asks else None
        best_bid = float(resp.bids[0].price) if resp.bids else None
        if best_ask and best_bid:
            return (best_ask + best_bid) / 2
        return best_ask or best_bid or 87000.0
    except Exception as e:
        logger.warning(f"Failed to fetch mainnet price, using fallback: {e}")
        return 87000.0
    finally:
        await api_client.close()


async def main():
    client = LighterClient(
        host=TESTNET_HOST,
        private_key=PRIVATE_KEY,
        api_key_index=API_KEY_INDEX,
        account_index=ACCOUNT_INDEX,
    )

    print("=" * 60)
    print("LIGHTER TESTNET INTEGRATION TEST")
    print(f"  3 concurrent BTC market orders, ${NOTIONAL_PER_ORDER} each")
    print("=" * 60)

    # 0. Pre-flight: clean up leftover positions
    print("\n--- Pre-flight cleanup ---")
    await client.cancel_all_orders()
    existing = await client.get_positions()
    if existing:
        print(f"  Found {len(existing)} leftover positions — closing")
        for pos in existing:
            is_ask = pos["side"] == "long"
            worst = pos["entry_price"] * (1 - SLIPPAGE) if is_ask else pos["entry_price"] * (1 + SLIPPAGE)
            coi = int(time.time() * 1000) % (2**31) + pos["market_index"]
            r = await client.place_order(
                market_index=pos["market_index"],
                base_amount=pos["size"],
                price=worst,
                is_ask=is_ask,
                client_order_index=coi,
                market=True,
                reduce_only=True,
            )
            print(f"    market {pos['market_index']}: {'closed' if r.success else 'FAIL: ' + str(r.error)}")
        await asyncio.sleep(5)
        still = await client.get_positions()
        print(f"  {'Clean' if not still else f'WARNING: {len(still)} positions remain'}")
    else:
        print("  Clean — no leftover positions")

    # 1. Balance check
    balance = await client.get_balance()
    print(f"\nBalance: ${balance:.2f}")
    total_notional = NOTIONAL_PER_ORDER * NUM_ORDERS
    if balance < total_notional:
        print(f"WARNING: Balance ${balance:.2f} < required ${total_notional:.2f}")

    # 2. Fetch BTC price from mainnet
    btc_price = await get_btc_price()
    print(f"BTC price (mainnet): ${btc_price:,.2f}")

    # 3. Fetch testnet market meta
    await client._ensure_clients()
    meta = await client._get_market_meta(BTC_MARKET_INDEX)
    print(f"BTC market meta: {meta}")

    # 4. Compute order params
    size_per_order = NOTIONAL_PER_ORDER / btc_price
    worst_price = btc_price * (1 + SLIPPAGE)
    print(f"\nOrder plan: {NUM_ORDERS}x BUY {size_per_order:.6f} BTC @ worst ${worst_price:,.2f}")

    # 5. Place 3 market BUY orders simultaneously
    print(f"\n--- Opening {NUM_ORDERS} positions ---")

    async def open_position(tag: int):
        coi = int(time.time() * 1000) % (2**31) + tag * 1000
        result = await client.place_order(
            market_index=BTC_MARKET_INDEX,
            base_amount=size_per_order,
            price=worst_price,
            is_ask=False,
            client_order_index=coi,
            market=True,
        )
        status = "OK" if result.success else f"FAIL: {result.error}"
        print(f"  Order {tag}: {status} (fill_price={result.filled_price}, fill_amount={result.filled_amount})")
        return result

    entry_results = await asyncio.gather(
        open_position(1),
        open_position(2),
        open_position(3),
    )

    entry_ok = sum(1 for r in entry_results if r.success)
    print(f"\nEntry: {entry_ok}/{NUM_ORDERS} orders succeeded")

    if entry_ok == 0:
        print("All entries failed — aborting.")
        return

    # 6. Wait for settlement
    print("\nWaiting 10s for settlement...")
    await asyncio.sleep(10)

    # 7. Fetch open positions
    print("\n--- Open positions ---")
    positions = await client.get_positions()
    btc_pos = None
    for p in positions:
        if p["market_index"] == BTC_MARKET_INDEX:
            btc_pos = p
            print(f"  BTC: side={p['side']}, size={p['size']}, entry_price={p['entry_price']}")

    if not btc_pos:
        print("  NO BTC POSITION — orders may not have settled")
        remaining = await client.get_positions()
        print(f"\n  Result: FAIL (no position to close)")
        return

    # 8. Close the combined position
    print(f"\n--- Closing BTC position (size={btc_pos['size']}) ---")
    is_ask = btc_pos["side"] == "long"
    close_worst = btc_price * (1 - SLIPPAGE) if is_ask else btc_price * (1 + SLIPPAGE)
    close_coi = int(time.time() * 1000) % (2**31) + 9999

    close_result = await client.place_order(
        market_index=BTC_MARKET_INDEX,
        base_amount=btc_pos["size"],
        price=close_worst,
        is_ask=is_ask,
        client_order_index=close_coi,
        market=True,
        reduce_only=True,
    )
    print(f"  Close: {'OK' if close_result.success else 'FAIL: ' + str(close_result.error)}")
    print(f"  Fill: price={close_result.filled_price}, amount={close_result.filled_amount}")

    # 9. Verify position is closed (with retry)
    for attempt in range(3):
        wait = [3, 5, 10][attempt]
        print(f"\nWaiting {wait}s for close settlement (attempt {attempt + 1}/3)...")
        await asyncio.sleep(wait)
        remaining = await client.get_positions()
        btc_remaining = [p for p in remaining if p["market_index"] == BTC_MARKET_INDEX]
        if not btc_remaining:
            print("  Position closed!")
            break
        print(f"  Still open: size={btc_remaining[0]['size']}")
    else:
        remaining = await client.get_positions()

    # 10. Summary
    btc_remaining = [p for p in remaining if p["market_index"] == BTC_MARKET_INDEX]
    passed = entry_ok == NUM_ORDERS and close_result.success and not btc_remaining

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Entries:    {entry_ok}/{NUM_ORDERS} succeeded")
    print(f"  Position:   size={btc_pos['size']} @ {btc_pos['entry_price']}")
    print(f"  Close:      {'OK' if close_result.success else 'FAIL'}")
    print(f"  Remaining:  {len(btc_remaining)} BTC positions")
    print(f"  Result:     {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
