from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import backend.models  # noqa: F401
from backend.api import quick_trades
from backend.api.deps import get_current_user
from backend.models.simple_trade import SimplePairTrade


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
