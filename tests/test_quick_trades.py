import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import backend.models  # noqa: F401
from backend.api import quick_trades
from backend.api.deps import get_current_user
from backend.models.simple_trade import SimplePairTrade
from backend.services.lighter_client import OrderResult, PairOrderResult


def _client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(quick_trades, "db_engine", engine)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: {"username": "test"}
    app.include_router(quick_trades.router)
    return TestClient(app), engine


def _add_trade(engine, status: str = "open") -> SimplePairTrade:
    trade = SimplePairTrade(
        asset_a="BTC",
        asset_b="ETH",
        lighter_market_a=1,
        lighter_market_b=2,
        direction=1,
        ratio=1,
        margin_usd=100,
        leverage=5,
        stop_loss_pct=15,
        take_profit_pct=5,
        order_mode="limit",
        slice_chunks=5,
        slice_delay_sec=2,
        status=status,
    )
    with Session(engine) as session:
        session.add(trade)
        session.commit()
        session.refresh(trade)
        return trade


def test_update_open_quick_trade_tp_sl(monkeypatch):
    client, engine = _client(monkeypatch)
    trade = _add_trade(engine)

    response = client.patch(
        f"/api/quick-trades/{trade.id}",
        json={"stop_loss_pct": 8.5, "take_profit_pct": 12.25},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stop_loss_pct"] == 8.5
    assert body["take_profit_pct"] == 12.25

    with Session(engine) as session:
        saved = session.get(SimplePairTrade, trade.id)
        assert saved.stop_loss_pct == 8.5
        assert saved.take_profit_pct == 12.25


def test_update_quick_trade_rejects_closed_trade(monkeypatch):
    client, engine = _client(monkeypatch)
    trade = _add_trade(engine, status="closed")

    response = client.patch(
        f"/api/quick-trades/{trade.id}",
        json={"stop_loss_pct": 8, "take_profit_pct": 12},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Trade is not open (status=closed)"


def test_update_quick_trade_rejects_failed_trade(monkeypatch):
    client, engine = _client(monkeypatch)
    trade = _add_trade(engine, status="failed")

    response = client.patch(
        f"/api/quick-trades/{trade.id}",
        json={"stop_loss_pct": 8, "take_profit_pct": 12},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Trade is not open (status=failed)"


def test_update_quick_trade_rejects_negative_threshold(monkeypatch):
    client, engine = _client(monkeypatch)
    trade = _add_trade(engine)

    response = client.patch(
        f"/api/quick-trades/{trade.id}",
        json={"stop_loss_pct": -1, "take_profit_pct": 12},
    )

    assert response.status_code == 422


def test_update_quick_trade_allows_zero_thresholds(monkeypatch):
    client, engine = _client(monkeypatch)
    trade = _add_trade(engine)

    response = client.patch(
        f"/api/quick-trades/{trade.id}",
        json={"stop_loss_pct": 0, "take_profit_pct": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stop_loss_pct"] == 0
    assert body["take_profit_pct"] == 0


def _patch_open_deps(monkeypatch, *, chunk_calls: list[dict] | None = None):
    from backend.engine import order_executor, pair_job

    async def fake_fetch_markets():
        return [
            {"symbol": "BTC", "market_id": 1},
            {"symbol": "ETH", "market_id": 2},
        ]

    async def fake_fetch_orderbook(_market_id: int):
        return {"mid_price": 100.0}

    async def fake_get_lighter_client(_credential_id=None):
        return FakeClient()

    async def fake_execute_chunked_pair_orders(**kwargs):
        if chunk_calls is not None:
            chunk_calls.append(kwargs)
        return (
            OrderResult(success=True, order_id="a", filled_price=100, filled_amount=1),
            OrderResult(success=True, order_id="b", filled_price=100, filled_amount=1),
            kwargs["chunks"],
        )

    fake_market_data = SimpleNamespace(
        fetch_markets=fake_fetch_markets,
        fetch_orderbook=fake_fetch_orderbook,
    )
    monkeypatch.setitem(sys.modules, "backend.services.market_data", fake_market_data)
    monkeypatch.setattr(pair_job, "_get_lighter_client", fake_get_lighter_client)
    monkeypatch.setattr(order_executor, "execute_chunked_pair_orders", fake_execute_chunked_pair_orders)


class FakeClient:
    def __init__(self):
        self.place_pair_orders_calls = []

    async def place_pair_orders(self, **kwargs):
        self.place_pair_orders_calls.append(kwargs)
        return PairOrderResult(
            success=True,
            result_a=OrderResult(success=True, order_id="a", filled_price=kwargs["price_a"], filled_amount=kwargs["base_amount_a"]),
            result_b=OrderResult(success=True, order_id="b", filled_price=kwargs["price_b"], filled_amount=kwargs["base_amount_b"]),
        )


def test_create_quick_trade_defaults_to_limit(monkeypatch):
    client, _engine = _client(monkeypatch)
    chunk_calls = []
    _patch_open_deps(monkeypatch, chunk_calls=chunk_calls)

    response = client.post(
        "/api/quick-trades",
        json={
            "asset_a": "BTC",
            "asset_b": "ETH",
            "direction": 1,
            "ratio": 1,
            "margin_usd": 100,
            "leverage": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()["order_mode"] == "limit"
    assert chunk_calls[0]["market"] is False


def test_create_quick_trade_rejects_invalid_order_mode(monkeypatch):
    client, _engine = _client(monkeypatch)

    response = client.post(
        "/api/quick-trades",
        json={
            "asset_a": "BTC",
            "asset_b": "ETH",
            "direction": 1,
            "order_mode": "maker",
        },
    )

    assert response.status_code == 422


def test_create_quick_trade_rejects_out_of_range_chunks_and_delay(monkeypatch):
    client, _engine = _client(monkeypatch)

    chunks_response = client.post(
        "/api/quick-trades",
        json={
            "asset_a": "BTC",
            "asset_b": "ETH",
            "direction": 1,
            "slice_chunks": 1,
        },
    )
    delay_response = client.post(
        "/api/quick-trades",
        json={
            "asset_a": "BTC",
            "asset_b": "ETH",
            "direction": 1,
            "slice_delay_sec": 0.1,
        },
    )

    assert chunks_response.status_code == 422
    assert delay_response.status_code == 422


def test_create_quick_trade_uses_sliced_market_execution(monkeypatch):
    client, _engine = _client(monkeypatch)
    chunk_calls = []
    _patch_open_deps(monkeypatch, chunk_calls=chunk_calls)

    response = client.post(
        "/api/quick-trades",
        json={
            "asset_a": "BTC",
            "asset_b": "ETH",
            "direction": 1,
            "order_mode": "sliced",
            "slice_chunks": 4,
            "slice_delay_sec": 1,
        },
    )

    assert response.status_code == 200
    assert chunk_calls[0]["market"] is True
    assert chunk_calls[0]["chunks"] == 4
    assert chunk_calls[0]["delay_sec"] == 1


def test_create_quick_trade_uses_immediate_market_batch(monkeypatch):
    from backend.engine import order_executor, pair_job

    client, _engine = _client(monkeypatch)
    fake_client = FakeClient()

    async def fake_fetch_markets():
        return [
            {"symbol": "BTC", "market_id": 1},
            {"symbol": "ETH", "market_id": 2},
        ]

    async def fake_fetch_orderbook(_market_id: int):
        return {"mid_price": 100.0}

    async def fake_get_lighter_client(_credential_id=None):
        return fake_client

    async def fail_chunked(**_kwargs):
        raise AssertionError("market mode should not use chunked executor")

    fake_market_data = SimpleNamespace(
        fetch_markets=fake_fetch_markets,
        fetch_orderbook=fake_fetch_orderbook,
    )
    monkeypatch.setitem(sys.modules, "backend.services.market_data", fake_market_data)
    monkeypatch.setattr(pair_job, "_get_lighter_client", fake_get_lighter_client)
    monkeypatch.setattr(order_executor, "execute_chunked_pair_orders", fail_chunked)

    response = client.post(
        "/api/quick-trades",
        json={
            "asset_a": "BTC",
            "asset_b": "ETH",
            "direction": 1,
            "order_mode": "market",
        },
    )

    assert response.status_code == 200
    assert response.json()["order_mode"] == "market"
    assert fake_client.place_pair_orders_calls[0]["market"] is True
