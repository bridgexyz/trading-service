"""Lighter DEX client wrapper for order placement and account management.

Wraps the lighter-sdk async API for pair trading operations.
"""

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


class LighterClient:
    """Wrapper around the Lighter SDK for trading operations."""

    def __init__(
        self,
        host: str,
        private_key: str,
        api_key_index: int,
        account_index: int,
    ):
        self.host = host
        self.private_key = private_key
        self.api_key_index = api_key_index
        self.account_index = account_index
        self._api_client = None
        self._signer_client = None
        self._mock_mode = False
        self._market_meta: dict[int, dict] = {}  # market_index → {price_decimals, size_decimals}

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

            if market:
                order, resp, error = await self._signer_client.create_market_order(
                    market_index=market_index,
                    client_order_index=client_order_index,
                    base_amount=amount_int,
                    avg_execution_price=price_int,
                    is_ask=is_ask,
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
                )
            if error is not None:
                logger.error(f"Order rejected: {error}")
                return OrderResult(success=False, error=str(error), raw_response=str(resp) if resp else None)
            order_id = str(client_order_index)
            filled_price = getattr(order, "price", None) or getattr(order, "avg_execution_price", None)
            filled_amount = getattr(order, "filled_amount", None) or getattr(order, "base_amount", None)
            order_status = getattr(order, "status", None)
            logger.info(f"Order placed: {order_id} ({'market' if market else 'limit'})")
            return OrderResult(
                success=True,
                order_id=order_id,
                filled_price=float(filled_price) if filled_price is not None else None,
                filled_amount=float(filled_amount) if filled_amount is not None else None,
                order_status=str(order_status) if order_status is not None else None,
                raw_response=str(resp) if resp else None,
            )
        except Exception as e:
            logger.error(f"Order failed: {e}")
            return OrderResult(success=False, error=str(e))

    async def place_twap_order(
        self,
        market_index: int,
        base_amount: float,
        price: float,
        is_ask: bool,
        duration_minutes: int,
        client_order_index: int | None = None,
    ) -> OrderResult:
        """Place a TWAP order on Lighter.

        The exchange handles time-slicing server-side over the given duration.

        Args:
            market_index: Lighter market index.
            base_amount: Quantity in asset units.
            price: Worst acceptable price.
            is_ask: True for sell, False for buy.
            duration_minutes: TWAP execution window in minutes.
            client_order_index: Unique order reference. Auto-generated if None.
        """
        await self._ensure_clients()

        if client_order_index is None:
            client_order_index = int(time.time() * 1000) % (2**31)

        if self._mock_mode:
            logger.info(
                f"MOCK TWAP order: market={market_index}, amount={base_amount:.4f}, "
                f"price={price:.2f}, side={'sell' if is_ask else 'buy'}, "
                f"duration={duration_minutes}min"
            )
            return OrderResult(success=True, order_id=f"mock-twap-{client_order_index}")

        try:
            meta = await self._get_market_meta(market_index)
            price_int = int(round(price * 10 ** meta["price_decimals"]))
            amount_int = int(round(base_amount * 10 ** meta["size_decimals"]))
            logger.debug(
                f"TWAP encode: price={price} → {price_int} ({meta['price_decimals']}dp), "
                f"amount={base_amount} → {amount_int} ({meta['size_decimals']}dp), "
                f"duration={duration_minutes}min"
            )

            order, resp, error = await self._signer_client.create_order(
                market_index=market_index,
                client_order_index=client_order_index,
                base_amount=amount_int,
                price=price_int,
                is_ask=is_ask,
                order_type=6,           # TWAP
                time_in_force=1,        # GOOD_TILL_TIME
                order_expiry=duration_minutes * 60,
            )
            if error is not None:
                logger.error(f"TWAP order rejected: {error}")
                return OrderResult(success=False, error=str(error), raw_response=str(resp) if resp else None)
            order_id = str(client_order_index)
            filled_price = getattr(order, "price", None) or getattr(order, "avg_execution_price", None)
            filled_amount = getattr(order, "filled_amount", None) or getattr(order, "base_amount", None)
            order_status = getattr(order, "status", None)
            logger.info(f"TWAP order placed: {order_id} (duration={duration_minutes}min)")
            return OrderResult(
                success=True,
                order_id=order_id,
                filled_price=float(filled_price) if filled_price is not None else None,
                filled_amount=float(filled_amount) if filled_amount is not None else None,
                order_status=str(order_status) if order_status is not None else None,
                raw_response=str(resp) if resp else None,
            )
        except Exception as e:
            logger.error(f"TWAP order failed: {e}")
            return OrderResult(success=False, error=str(e))

    async def cancel_order(self, market_index: int, order_id: str) -> bool:
        """Cancel an order."""
        await self._ensure_clients()
        if self._mock_mode:
            logger.info(f"MOCK cancel: market={market_index}, order={order_id}")
            return True
        try:
            _cancel, resp, error = await self._signer_client.cancel_order(
                market_index=market_index, order_index=int(order_id)
            )
            if error is not None:
                logger.error(f"Cancel rejected: {error} | resp={resp}")
                return False
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
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

    async def get_positions(self) -> list[dict]:
        """Get all open positions from the Lighter exchange.

        Returns a list of dicts with keys: market_index, side, size, entry_price.
        """
        await self._ensure_clients()
        if self._mock_mode:
            return []
        import lighter

        account_api = lighter.AccountApi(self._api_client)
        resp = await account_api.account(
            by="index", value=str(self.account_index)
        )
        # Unwrap DetailedAccounts → DetailedAccount
        if hasattr(resp, "accounts") and resp.accounts:
            account = resp.accounts[0]
        else:
            account = resp
        positions = []
        raw_positions = getattr(account, "positions", None) or []
        for pos in raw_positions:
            size = float(getattr(pos, "size", 0))
            if abs(size) < 1e-10:
                continue
            positions.append({
                "market_index": int(getattr(pos, "market_index", 0)),
                "side": "long" if size > 0 else "short",
                "size": abs(size),
                "entry_price": float(getattr(pos, "entry_price", 0)),
            })
        return positions

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
