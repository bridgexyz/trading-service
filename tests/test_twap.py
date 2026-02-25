"""Tests for TWAP order functionality across schema, model, client, and routing layers."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.schemas.trading_pair import TradingPairCreate, TradingPairUpdate
from backend.models.trading_pair import TradingPair
from backend.services.lighter_client import LighterClient, OrderResult


# ---------------------------------------------------------------------------
# 1. Schema validation tests
# ---------------------------------------------------------------------------

class TestCreateSchematwap:
    def test_create_schema_twap_default(self):
        schema = TradingPairCreate(asset_a="ETH", asset_b="BTC")
        assert schema.twap_minutes == 0

    def test_create_schema_twap_positive(self):
        schema = TradingPairCreate(asset_a="ETH", asset_b="BTC", twap_minutes=5)
        assert schema.twap_minutes == 5

    def test_create_schema_twap_negative_rejected(self):
        with pytest.raises(ValidationError):
            TradingPairCreate(asset_a="ETH", asset_b="BTC", twap_minutes=-1)


class TestUpdateSchemaTwap:
    def test_update_schema_twap_none_default(self):
        schema = TradingPairUpdate()
        assert schema.twap_minutes is None

    def test_update_schema_twap_valid(self):
        schema = TradingPairUpdate(twap_minutes=10)
        assert schema.twap_minutes == 10


# ---------------------------------------------------------------------------
# 2. Model test
# ---------------------------------------------------------------------------

def test_trading_pair_model_twap_default():
    pair = TradingPair(name="X-Y", asset_a="X", asset_b="Y")
    assert pair.twap_minutes == 0


# ---------------------------------------------------------------------------
# 3. LighterClient mock-mode tests
# ---------------------------------------------------------------------------

def _make_mock_client() -> LighterClient:
    """Create a LighterClient that is already in mock mode."""
    client = LighterClient(
        host="https://mock", private_key="0xdead", api_key_index=0, account_index=0
    )
    client._mock_mode = True
    # Skip _ensure_clients by pretending we already initialised
    client._api_client = "mock"
    return client


@pytest.mark.asyncio
async def test_place_twap_order_mock_success():
    client = _make_mock_client()
    result = await client.place_twap_order(
        market_index=1, base_amount=0.5, price=100.0,
        is_ask=False, duration_minutes=5, client_order_index=42,
    )
    assert result.success is True
    assert result.order_id.startswith("mock-twap-")


@pytest.mark.asyncio
async def test_place_twap_order_mock_logs_duration(caplog):
    client = _make_mock_client()
    with caplog.at_level(logging.INFO):
        await client.place_twap_order(
            market_index=1, base_amount=0.5, price=100.0,
            is_ask=True, duration_minutes=7,
        )
    assert "duration=7min" in caplog.text


# ---------------------------------------------------------------------------
# 4. LighterClient SDK-path tests (mock _signer_client)
# ---------------------------------------------------------------------------

def _make_sdk_client(market_meta: dict | None = None) -> LighterClient:
    """Create a LighterClient with a mocked SDK signer."""
    client = LighterClient(
        host="https://real", private_key="0xbeef", api_key_index=0, account_index=0
    )
    client._mock_mode = False
    client._api_client = MagicMock()
    client._signer_client = AsyncMock()
    # Pre-populate market metadata to avoid API call
    client._market_meta = market_meta or {1: {"price_decimals": 2, "size_decimals": 4}}
    return client


@pytest.mark.asyncio
async def test_place_twap_order_calls_create_order_with_type_6():
    client = _make_sdk_client()
    order_obj = SimpleNamespace(price=None, filled_amount=None, status=None)
    client._signer_client.create_order.return_value = (order_obj, "resp", None)

    await client.place_twap_order(
        market_index=1, base_amount=1.0, price=50.0,
        is_ask=False, duration_minutes=5, client_order_index=99,
    )

    client._signer_client.create_order.assert_called_once()
    call_kwargs = client._signer_client.create_order.call_args.kwargs
    assert call_kwargs["order_type"] == 6
    assert call_kwargs["time_in_force"] == 1
    assert call_kwargs["order_expiry"] == 300  # 5 * 60


@pytest.mark.asyncio
async def test_place_twap_order_encodes_price_and_amount():
    meta = {2: {"price_decimals": 3, "size_decimals": 2}}
    client = _make_sdk_client(market_meta=meta)
    order_obj = SimpleNamespace(price=None, filled_amount=None, status=None)
    client._signer_client.create_order.return_value = (order_obj, "resp", None)

    await client.place_twap_order(
        market_index=2, base_amount=1.5, price=123.456,
        is_ask=True, duration_minutes=10, client_order_index=1,
    )

    call_kwargs = client._signer_client.create_order.call_args.kwargs
    # price=123.456 * 10^3 = 123456
    assert call_kwargs["price"] == 123456
    # amount=1.5 * 10^2 = 150
    assert call_kwargs["base_amount"] == 150


@pytest.mark.asyncio
async def test_place_twap_order_error_returns_failure():
    client = _make_sdk_client()
    client._signer_client.create_order.return_value = (None, "resp", "insufficient margin")

    result = await client.place_twap_order(
        market_index=1, base_amount=1.0, price=50.0,
        is_ask=False, duration_minutes=5,
    )

    assert result.success is False
    assert "insufficient margin" in result.error


# ---------------------------------------------------------------------------
# 5. _place_pair_order routing tests
# ---------------------------------------------------------------------------

def _import_place_pair_order():
    """Import _place_pair_order while mocking the database module to avoid DB init."""
    import sys
    mock_db = MagicMock()
    saved = sys.modules.get("backend.database")
    sys.modules["backend.database"] = mock_db
    try:
        # Force reimport if already cached with broken DB
        sys.modules.pop("backend.engine.pair_job", None)
        from backend.engine.pair_job import _place_pair_order
        return _place_pair_order
    finally:
        if saved is not None:
            sys.modules["backend.database"] = saved
        else:
            sys.modules.pop("backend.database", None)


@pytest.mark.asyncio
async def test_place_pair_order_routes_to_twap():
    _place_pair_order = _import_place_pair_order()

    client = AsyncMock(spec=LighterClient)
    client.place_twap_order.return_value = OrderResult(success=True, order_id="twap-1")

    pair = TradingPair(name="A-B", asset_a="A", asset_b="B", twap_minutes=5)

    result = await _place_pair_order(client, pair, market_index=1, base_amount=1.0, price=100.0, is_ask=False)

    client.place_twap_order.assert_called_once_with(
        market_index=1, base_amount=1.0, price=100.0,
        is_ask=False, duration_minutes=5,
    )
    client.place_order.assert_not_called()
    assert result.order_id == "twap-1"


@pytest.mark.asyncio
async def test_place_pair_order_routes_to_market():
    _place_pair_order = _import_place_pair_order()

    client = AsyncMock(spec=LighterClient)
    client.place_order.return_value = OrderResult(success=True, order_id="mkt-1")

    pair = TradingPair(name="A-B", asset_a="A", asset_b="B", twap_minutes=0)

    result = await _place_pair_order(client, pair, market_index=1, base_amount=1.0, price=100.0, is_ask=True)

    client.place_order.assert_called_once_with(
        market_index=1, base_amount=1.0, price=100.0,
        is_ask=True, market=True,
    )
    client.place_twap_order.assert_not_called()
    assert result.order_id == "mkt-1"
