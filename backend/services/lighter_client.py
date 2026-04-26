"""Lighter DEX client wrapper for order placement and account management.

Wraps the lighter-sdk async API for pair trading operations.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    success: bool
    order_id: str | None = None
    error: str | None = None
    filled_price: float | None = None
    filled_amount: float | None = None
    order_status: str | None = None
    raw_response: str | None = None


@dataclass
class PairOrderResult:
    success: bool
    result_a: OrderResult
    result_b: OrderResult
    error: str | None = None


class LighterClient:
    """Wrapper around the Lighter SDK for trading operations."""

    def __init__(
        self,
        host: str,
        private_key: str,
        api_key_index: int,
        account_index: int | str,
    ):
        self.host = host
        self.private_key = private_key
        self.api_key_index = api_key_index
        self.account_index = int(account_index)
        self._api_client = None
        self._signer_client = None
        self._mock_mode = False
        self._market_meta: dict[int, dict] = {}  # market_index → {price_decimals, size_decimals}
        self._sign_lock = asyncio.Lock()
        self._last_sign_ts: float = 0.0
        self.min_sign_interval: float = 1.1  # 60 req/min rate limit → ~1s between signed txs

    async def _ensure_clients(self):
        """Lazily initialize Lighter SDK clients."""
        if self._api_client is not None:
            return

        try:
            import lighter

            config = lighter.Configuration(host=self.host)
            self._api_client = lighter.ApiClient(configuration=config)
            self._signer_client = lighter.SignerClient(
                url=self.host,
                account_index=self.account_index,
                api_private_keys={self.api_key_index: self.private_key},
            )
            logger.info("Lighter SDK clients initialized")
        except ImportError:
            logger.warning("lighter-sdk not installed; using mock mode")
            self._mock_mode = True
        except Exception as e:
            logger.error(f"Failed to initialize Lighter clients: {e}")
            raise

    async def _throttle(self):
        """Enforce minimum interval between signed transactions (call while holding _sign_lock)."""
        elapsed = time.time() - self._last_sign_ts
        if elapsed < self.min_sign_interval:
            await asyncio.sleep(self.min_sign_interval - elapsed)
        self._last_sign_ts = time.time()

    async def reinit_signer(self):
        """Rebuild the signer client. Use after a failed signed tx to avoid
        nonce desync: if the SDK incremented its local nonce for a tx the
        server rejected, the SDK is ahead of the server and every subsequent
        signed call fails with 'invalid signature'. A fresh SignerClient
        re-reads nonce from the server.
        """
        if self._mock_mode:
            return
        try:
            old = self._signer_client
            self._signer_client = None
            if old is not None:
                try:
                    await old.close()
                except Exception as e:
                    logger.debug(f"Ignoring error closing old signer: {e}")
            import lighter
            self._signer_client = lighter.SignerClient(
                url=self.host,
                account_index=self.account_index,
                api_private_keys={self.api_key_index: self.private_key},
            )
            logger.warning("Signer re-initialized (nonce resync)")
        except Exception as e:
            logger.error(f"Signer re-init failed: {e}")

    @staticmethod
    def _is_sign_error(err: str | None) -> bool:
        if not err:
            return False
        e = err.lower()
        return (
            "invalid signature" in e
            or "21120" in e
            or "nonce" in e
        )

    async def _get_market_meta(self, market_index: int) -> dict:
        """Fetch and cache price/size decimal info for a market."""
        if market_index in self._market_meta:
            return self._market_meta[market_index]

        import lighter
        order_api = lighter.OrderApi(self._api_client)
        resp = await order_api.order_book_details(market_id=market_index)
        # resp.order_book_details = perps markets, resp.spot_order_book_details = spot
        for book in (resp.order_book_details or []) + (resp.spot_order_book_details or []):
            if book.market_id == market_index:
                meta = {
                    "price_decimals": int(book.supported_price_decimals),
                    "size_decimals": int(book.supported_size_decimals),
                }
                self._market_meta[market_index] = meta
                logger.info(f"Market {market_index} meta: {meta}")
                return meta
        raise ValueError(f"Could not find market metadata for market_index={market_index}")

    async def test_connection(self) -> dict:
        """Test connectivity to Lighter."""
        await self._ensure_clients()

        if self._mock_mode:
            return {"status": "mock", "message": "lighter-sdk not installed"}

        try:
            import lighter

            account_api = lighter.AccountApi(self._api_client)
            account = await account_api.account(
                by="index", value=str(self.account_index)
            )
            return {"status": "ok", "account": str(account)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def place_order(
        self,
        market_index: int,
        base_amount: float,
        price: float,
        is_ask: bool,
        client_order_index: int | None = None,
        market: bool = False,
        reduce_only: bool = False,
    ) -> OrderResult:
        """Place an order on Lighter.

        Args:
            market_index: Lighter market index.
            base_amount: Quantity in asset units.
            price: Limit price, or worst acceptable price for market orders.
            is_ask: True for sell, False for buy.
            client_order_index: Unique order reference. Auto-generated if None.
            market: If True, use IOC market order instead of limit.
        """
        await self._ensure_clients()

        if client_order_index is None:
            client_order_index = int(time.time() * 1000) % (2**31)

        if self._mock_mode:
            order_type_str = "MARKET" if market else "LIMIT"
            logger.info(
                f"MOCK {order_type_str} order: market={market_index}, amount={base_amount:.4f}, "
                f"price={price:.2f}, side={'sell' if is_ask else 'buy'}"
            )
            return OrderResult(success=True, order_id=f"mock-{client_order_index}")

        try:
            meta = await self._get_market_meta(market_index)
            price_int = int(round(price * 10 ** meta["price_decimals"]))
            amount_int = int(round(base_amount * 10 ** meta["size_decimals"]))
            logger.debug(
                f"Order encode: price={price} → {price_int} ({meta['price_decimals']}dp), "
                f"amount={base_amount} → {amount_int} ({meta['size_decimals']}dp)"
            )

            async with self._sign_lock:
                await self._throttle()
                if market:
                    order, resp, error = await self._signer_client.create_order(
                        market_index=market_index,
                        client_order_index=client_order_index,
                        base_amount=amount_int,
                        price=price_int,
                        is_ask=is_ask,
                        order_type=1,       # MARKET
                        time_in_force=0,    # IMMEDIATE_OR_CANCEL
                        order_expiry=0,     # SDK DEFAULT_IOC_EXPIRY
                        reduce_only=reduce_only,
                    )
                else:
                    order, resp, error = await self._signer_client.create_order(
                        market_index=market_index,
                        client_order_index=client_order_index,
                        base_amount=amount_int,
                        price=price_int,
                        is_ask=is_ask,
                        order_type=0,       # LIMIT
                        time_in_force=1,    # GOOD_TILL_TIME
                        reduce_only=reduce_only,
                    )
                if error is not None:
                    logger.error(f"Order rejected: {error}")
                    if self._is_sign_error(str(error)):
                        await self.reinit_signer()
                    return OrderResult(success=False, error=str(error), raw_response=str(resp) if resp else None)
            order_id = str(client_order_index)
            # avg_execution_price is the actual fill; order.price is the limit/worst we submitted
            raw_price = getattr(order, "avg_execution_price", None) or getattr(order, "price", None)
            raw_amount = getattr(order, "filled_amount", None) or getattr(order, "base_amount", None)
            order_status = getattr(order, "status", None)
            # Decode raw integer values back to human-readable using market decimals
            filled_price = float(raw_price) / 10 ** meta["price_decimals"] if raw_price is not None else None
            filled_amount = float(raw_amount) / 10 ** meta["size_decimals"] if raw_amount is not None else None
            logger.info(f"Order placed: {order_id} ({'market' if market else 'limit'}), fill_price={filled_price}, fill_amount={filled_amount}")
            return OrderResult(
                success=True,
                order_id=order_id,
                filled_price=filled_price,
                filled_amount=filled_amount,
                order_status=str(order_status) if order_status is not None else None,
                raw_response=str(resp) if resp else None,
            )
        except Exception as e:
            logger.error(f"Order failed: {e}")
            if self._is_sign_error(str(e)):
                async with self._sign_lock:
                    await self.reinit_signer()
            return OrderResult(success=False, error=str(e))

    async def place_pair_orders(
        self,
        market_index_a: int,
        base_amount_a: float,
        price_a: float,
        is_ask_a: bool,
        market_index_b: int,
        base_amount_b: float,
        price_b: float,
        is_ask_b: bool,
        client_order_index_a: int | None = None,
        client_order_index_b: int | None = None,
        market: bool = False,
        reduce_only: bool = False,
    ) -> PairOrderResult:
        """Place two orders in a single batch HTTP call.

        Signs both legs locally, then submits via send_tx_batch() — one
        rate-limit slot, one throttle wait, no price drift between legs.
        """
        await self._ensure_clients()

        ts = int(time.time() * 1000) % (2**31)
        if client_order_index_a is None:
            client_order_index_a = ts
        if client_order_index_b is None:
            client_order_index_b = ts + 1

        _fail_a = OrderResult(success=False)
        _fail_b = OrderResult(success=False)

        if self._mock_mode:
            logger.info(f"MOCK batch: A=market{market_index_a}, B=market{market_index_b}")
            return PairOrderResult(
                success=True,
                result_a=OrderResult(success=True, order_id=f"mock-{client_order_index_a}"),
                result_b=OrderResult(success=True, order_id=f"mock-{client_order_index_b}"),
            )

        nonces_obtained = False
        nm = None
        api_key_idx = self.api_key_index

        try:
            meta_a = await self._get_market_meta(market_index_a)
            meta_b = await self._get_market_meta(market_index_b)

            price_int_a = int(round(price_a * 10 ** meta_a["price_decimals"]))
            amount_int_a = int(round(base_amount_a * 10 ** meta_a["size_decimals"]))
            price_int_b = int(round(price_b * 10 ** meta_b["price_decimals"]))
            amount_int_b = int(round(base_amount_b * 10 ** meta_b["size_decimals"]))

            order_type = 1 if market else 0
            time_in_force = 0 if market else 1
            order_expiry = 0 if market else -1

            async with self._sign_lock:
                await self._throttle()

                nm = self._signer_client.nonce_manager
                api_key_idx, nonce_a = nm.next_nonce(api_key=self.api_key_index)
                _, nonce_b = nm.next_nonce(api_key=self.api_key_index)
                nonces_obtained = True

                tx_type_a, tx_info_a, tx_hash_a, err_a = self._signer_client.sign_create_order(
                    market_index=market_index_a,
                    client_order_index=client_order_index_a,
                    base_amount=amount_int_a,
                    price=price_int_a,
                    is_ask=is_ask_a,
                    order_type=order_type,
                    time_in_force=time_in_force,
                    order_expiry=order_expiry,
                    reduce_only=reduce_only,
                    nonce=nonce_a,
                    api_key_index=api_key_idx,
                )
                if err_a is not None:
                    logger.error(f"Batch sign leg A failed: {err_a}")
                    nm.acknowledge_failure(api_key_idx)
                    nm.acknowledge_failure(api_key_idx)
                    if self._is_sign_error(str(err_a)):
                        await self.reinit_signer()
                    return PairOrderResult(success=False, result_a=_fail_a, result_b=_fail_b, error=f"sign A: {err_a}")

                tx_type_b, tx_info_b, tx_hash_b, err_b = self._signer_client.sign_create_order(
                    market_index=market_index_b,
                    client_order_index=client_order_index_b,
                    base_amount=amount_int_b,
                    price=price_int_b,
                    is_ask=is_ask_b,
                    order_type=order_type,
                    time_in_force=time_in_force,
                    order_expiry=order_expiry,
                    reduce_only=reduce_only,
                    nonce=nonce_b,
                    api_key_index=api_key_idx,
                )
                if err_b is not None:
                    logger.error(f"Batch sign leg B failed: {err_b}")
                    nm.acknowledge_failure(api_key_idx)
                    nm.acknowledge_failure(api_key_idx)
                    if self._is_sign_error(str(err_b)):
                        await self.reinit_signer()
                    return PairOrderResult(success=False, result_a=_fail_a, result_b=_fail_b, error=f"sign B: {err_b}")

                batch_resp = await self._signer_client.send_tx_batch(
                    tx_types=[tx_type_a, tx_type_b],
                    tx_infos=[tx_info_a, tx_info_b],
                )

                if batch_resp.code != 200:
                    err_msg = batch_resp.message or f"code {batch_resp.code}"
                    logger.error(f"Batch rejected: {err_msg}")
                    nm.acknowledge_failure(api_key_idx)
                    nm.acknowledge_failure(api_key_idx)
                    if self._is_sign_error(str(err_msg)):
                        await self.reinit_signer()
                    return PairOrderResult(success=False, result_a=_fail_a, result_b=_fail_b, error=err_msg)

            filled_price_a = price_a
            filled_amount_a = base_amount_a
            filled_price_b = price_b
            filled_amount_b = base_amount_b
            raw = str(batch_resp)

            logger.info(
                f"Batch placed: A={client_order_index_a} (market{market_index_a}), "
                f"B={client_order_index_b} (market{market_index_b})"
            )
            return PairOrderResult(
                success=True,
                result_a=OrderResult(
                    success=True, order_id=str(client_order_index_a),
                    filled_price=filled_price_a, filled_amount=filled_amount_a, raw_response=raw,
                ),
                result_b=OrderResult(
                    success=True, order_id=str(client_order_index_b),
                    filled_price=filled_price_b, filled_amount=filled_amount_b, raw_response=raw,
                ),
            )

        except Exception as e:
            logger.error(f"Batch order failed: {e}")
            if nonces_obtained and nm:
                nm.acknowledge_failure(api_key_idx)
                nm.acknowledge_failure(api_key_idx)
            if self._is_sign_error(str(e)):
                async with self._sign_lock:
                    await self.reinit_signer()
            return PairOrderResult(success=False, result_a=_fail_a, result_b=_fail_b, error=str(e))

    async def cancel_all_orders(self) -> bool:
        """Cancel all open orders across all markets."""
        await self._ensure_clients()
        if self._mock_mode:
            logger.info("MOCK cancel all orders")
            return True

        try:
            async with self._sign_lock:
                await self._throttle()
                _result, resp, error = await self._signer_client.cancel_all_orders(
                    time_in_force=0,   # CANCEL_ALL_TIF_IMMEDIATE
                    timestamp_ms=0,    # must be 0 for IMMEDIATE; only set for SCHEDULED
                )
                if error is not None:
                    logger.error(f"Cancel all orders failed: {error}")
                    await self.reinit_signer()
                    return False
            logger.info("Cancelled all open orders")
            return True
        except Exception as e:
            logger.error(f"Cancel all orders failed: {e}")
            async with self._sign_lock:
                await self.reinit_signer()
            return False

    async def cancel_order(self, market_index: int, order_id: str) -> bool:
        """Cancel an order."""
        await self._ensure_clients()
        if self._mock_mode:
            logger.info(f"MOCK cancel: market={market_index}, order={order_id}")
            return True
        try:
            async with self._sign_lock:
                await self._throttle()
                _cancel, resp, error = await self._signer_client.cancel_order(
                    market_index=market_index, order_index=int(order_id)
                )
                if error is not None:
                    logger.error(f"Cancel rejected: {error} | resp={resp}")
                    if self._is_sign_error(str(error)):
                        await self.reinit_signer()
                    return False
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            async with self._sign_lock:
                if self._is_sign_error(str(e)):
                    await self.reinit_signer()
            return False

    async def get_balance(self) -> float:
        """Get available USDC balance."""
        await self._ensure_clients()
        if self._mock_mode:
            return 99999.0
        try:
            import lighter

            account_api = lighter.AccountApi(self._api_client)
            resp = await account_api.account(
                by="index", value=str(self.account_index)
            )
            logger.debug(f"Balance response type={type(resp).__name__}, value={resp}")
            if hasattr(resp, "accounts") and resp.accounts:
                balance = resp.accounts[0].available_balance
            elif hasattr(resp, "available_balance"):
                balance = resp.available_balance
            else:
                logger.error(f"Balance fetch: unexpected response structure: {resp}")
                return 0.0
            logger.info(f"Balance fetched: {balance}")
            return float(balance)
        except Exception as e:
            logger.error(f"Balance fetch failed: {e}", exc_info=True)
            return 0.0

    async def _get_account(self):
        """Fetch the account object from Lighter."""
        import lighter

        account_api = lighter.AccountApi(self._api_client)
        resp = await account_api.account(
            by="index", value=str(self.account_index)
        )
        if hasattr(resp, "accounts") and resp.accounts:
            return resp.accounts[0]
        return resp

    async def get_positions(self) -> list[dict]:
        """Get all open positions from the Lighter exchange.

        Returns a list of dicts with keys: market_index, side, size, entry_price, realized_pnl.
        """
        await self._ensure_clients()
        if self._mock_mode:
            return []

        account = await self._get_account()
        positions = []
        raw_positions = getattr(account, "positions", None) or []
        for pos in raw_positions:
            size = float(getattr(pos, "position", 0))
            if abs(size) < 1e-10:
                continue
            sign = int(getattr(pos, "sign", 1))
            positions.append({
                "market_index": int(getattr(pos, "market_id", 0)),
                "side": "long" if sign >= 0 else "short",
                "size": abs(size),
                "entry_price": float(getattr(pos, "avg_entry_price", 0)),
                "realized_pnl": float(getattr(pos, "realized_pnl", 0)),
            })
        return positions

    async def get_realized_pnl(self, market_indices: list[int]) -> dict[int, float]:
        """Get realized PnL for specific markets (works even with zero-size positions).

        Returns {market_index: realized_pnl}.
        """
        await self._ensure_clients()
        if self._mock_mode:
            return {m: 0.0 for m in market_indices}

        account = await self._get_account()
        result = {}
        raw_positions = getattr(account, "positions", None) or []
        for pos in raw_positions:
            mid = int(getattr(pos, "market_id", 0))
            if mid in market_indices:
                result[mid] = float(getattr(pos, "realized_pnl", 0))
        # Fill in any missing markets with 0
        for m in market_indices:
            if m not in result:
                result[m] = 0.0
        return result

    async def close(self):
        """Close SDK clients."""
        if self._api_client and not self._mock_mode:
            try:
                await self._api_client.close()
            except Exception:
                pass
        self._api_client = None
        self._signer_client = None
        self._mock_mode = False
        self._market_meta = {}
