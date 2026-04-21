"""Live integration test for LighterClient through the singleton path.

Tests the actual production code path: DB credential → decryption →
singleton cache → sign lock → order execution.

Also tests concurrent ordering to verify the singleton + lock prevents
nonce races.

Usage (requires .env with TS_DATABASE_URL and TS_ENCRYPTION_KEY):
    python test_client_live.py                     # test with first active credential
    python test_client_live.py --credential-id 2   # test with specific credential
    python test_client_live.py --concurrent         # test concurrent orders (nonce race check)
"""

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def get_client(credential_id: int | None = None):
    from backend.engine.pair_job import _get_lighter_client
    client = await _get_lighter_client(credential_id)
    if client is None:
        print(f"ERROR: No active credential found (credential_id={credential_id})")
        sys.exit(1)
    return client


async def test_singleton(credential_id: int | None = None):
    """Verify two calls return the exact same instance."""
    logger.info("--- Test: singleton cache ---")
    c1 = await get_client(credential_id)
    c2 = await get_client(credential_id)
    assert c1 is c2, "Singleton cache broken: got different instances"
    logger.info(f"Same instance: {c1 is c2} (id={id(c1)})")
    return True


async def test_balance(credential_id: int | None = None):
    logger.info("--- Test: balance ---")
    client = await get_client(credential_id)
    balance = await client.get_balance()
    assert balance >= 0, f"Balance should be non-negative, got {balance}"
    logger.info(f"Balance: ${balance:.2f}")
    return True


async def test_market_meta(credential_id: int | None = None, market_index: int = 0):
    logger.info(f"--- Test: market meta (index={market_index}) ---")
    client = await get_client(credential_id)
    await client._ensure_clients()
    meta = await client._get_market_meta(market_index)
    assert "price_decimals" in meta and "size_decimals" in meta
    logger.info(f"Market {market_index}: {meta}")
    return True


async def test_positions(credential_id: int | None = None):
    logger.info("--- Test: get positions ---")
    client = await get_client(credential_id)
    positions = await client.get_positions()
    logger.info(f"Open positions: {len(positions)}")
    for p in positions:
        logger.info(f"  market={p['market_index']} side={p['side']} size={p['size']} entry={p['entry_price']}")
    return True


async def test_place_and_cancel(credential_id: int | None = None, market_index: int = 0):
    """Place a tiny limit order far from market, then cancel."""
    logger.info(f"--- Test: place + cancel (market={market_index}) ---")
    client = await get_client(credential_id)

    await client._ensure_clients()
    meta = await client._get_market_meta(market_index)
    min_size = 1 / (10 ** meta["size_decimals"])

    client_order_index = int(time.time() * 1000) % (2**31)
    result = await client.place_order(
        market_index=market_index,
        base_amount=min_size,
        price=1.0,  # $1 bid — won't fill
        is_ask=False,
        client_order_index=client_order_index,
        market=False,
    )

    if not result.success:
        logger.error(f"Order FAILED: {result.error}")
        return False

    logger.info(f"Order placed: id={result.order_id}, status={result.order_status}")

    cancelled = await client.cancel_order(market_index, result.order_id)
    logger.info(f"Cancel: {'OK' if cancelled else 'FAILED (may have expired)'}")
    return True


async def test_concurrent_singleton(credential_id: int | None = None, market_index: int = 0):
    """Fire multiple orders concurrently through the singleton (should all pass)."""
    logger.info(f"--- Test: concurrent via singleton (market={market_index}) ---")
    client = await get_client(credential_id)

    await client._ensure_clients()
    meta = await client._get_market_meta(market_index)
    min_size = 1 / (10 ** meta["size_decimals"])

    async def place_one(tag: str):
        coi = int(time.time() * 1000) % (2**31) + hash(tag) % 10000
        r = await client.place_order(
            market_index=market_index,
            base_amount=min_size,
            price=1.0,
            is_ask=False,
            client_order_index=coi,
            market=False,
        )
        logger.info(f"  [{tag}] {'OK' if r.success else 'FAIL: ' + str(r.error)}")
        return r.success

    results = await asyncio.gather(
        place_one("A"),
        place_one("B"),
        place_one("C"),
    )

    await client.cancel_all_orders()

    passed = all(results)
    logger.info(f"Singleton concurrent: {sum(results)}/3 succeeded")
    return passed


async def test_concurrent_no_lock(credential_id: int | None = None, market_index: int = 0):
    """Reproduce the original bug: separate clients, no shared lock, same account.

    Creates 3 independent LighterClient instances (like the old code did per pair job)
    and fires orders simultaneously. Without the singleton, these clients each read
    the same nonce and race — expect 'invalid signature' failures.
    """
    logger.info(f"--- Test: concurrent WITHOUT singleton (reproducing old bug) ---")
    from backend.services.lighter_client import LighterClient
    from backend.services.encryption import decrypt
    from backend.models.credential import Credential
    from backend.database import engine
    from sqlmodel import Session, select

    with Session(engine) as session:
        if credential_id is not None:
            cred = session.get(Credential, credential_id)
        else:
            cred = session.exec(
                select(Credential).where(Credential.is_active == True)
            ).first()
        if not cred:
            logger.error("No credential found")
            return False
        pk = decrypt(cred.private_key_encrypted)
        host = cred.lighter_host
        api_key_index = cred.api_key_index
        account_index = cred.account_index

    # Create 3 SEPARATE clients — same account, no shared lock
    clients = [
        LighterClient(host=host, private_key=pk, api_key_index=api_key_index, account_index=account_index)
        for _ in range(3)
    ]

    # Warm them up so they all read nonce at ~the same time
    await asyncio.gather(*(c._ensure_clients() for c in clients))
    meta = await clients[0]._get_market_meta(market_index)
    min_size = 1 / (10 ** meta["size_decimals"])

    async def place_one(tag: str, client: LighterClient):
        coi = int(time.time() * 1000) % (2**31) + hash(tag) % 10000
        r = await client.place_order(
            market_index=market_index,
            base_amount=min_size,
            price=1.0,
            is_ask=False,
            client_order_index=coi,
            market=False,
        )
        logger.info(f"  [no-lock {tag}] {'OK' if r.success else 'FAIL: ' + str(r.error)}")
        return r.success

    results = await asyncio.gather(
        place_one("X", clients[0]),
        place_one("Y", clients[1]),
        place_one("Z", clients[2]),
    )

    for c in clients:
        await c.cancel_all_orders()

    succeeded = sum(results)
    logger.info(f"No-lock concurrent: {succeeded}/3 succeeded")

    if succeeded < 3:
        logger.info("^ Expected! This reproduces the nonce race bug that the singleton fix prevents.")
    return succeeded  # return count, not pass/fail — failures are expected here


async def main():
    parser = argparse.ArgumentParser(description="Live LighterClient integration test")
    parser.add_argument("--credential-id", type=int, default=None)
    parser.add_argument("--market-index", type=int, default=0)
    parser.add_argument("--concurrent", action="store_true", help="Run concurrent order test")
    args = parser.parse_args()

    cred_id = args.credential_id
    market = args.market_index

    results = {}
    try:
        results["singleton"] = await test_singleton(cred_id)
        results["balance"] = await test_balance(cred_id)
        results["market_meta"] = await test_market_meta(cred_id, market)
        results["positions"] = await test_positions(cred_id)
        results["place_cancel"] = await test_place_and_cancel(cred_id, market)

        if args.concurrent:
            results["concurrent_singleton"] = await test_concurrent_singleton(cred_id, market)
            no_lock_ok = await test_concurrent_no_lock(cred_id, market)
            results["concurrent_no_lock"] = no_lock_ok  # int: how many succeeded out of 3
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)

    print("\n=== Results ===")
    all_pass = True
    for name, value in results.items():
        if name == "concurrent_no_lock":
            # This test reproduces the old bug — fewer than 3 means the race exists
            print(f"  {name}: {value}/3 succeeded (< 3 confirms the nonce race bug)")
        else:
            status = "PASS" if value else "FAIL"
            if not value:
                all_pass = False
            print(f"  {name}: {status}")

    print(f"\n{'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(main())
