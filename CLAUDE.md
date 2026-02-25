# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Live cryptocurrency pair trading service for the Lighter DEX. FastAPI backend handles signal computation, order execution, and scheduling. React admin panel provides pair management and monitoring.

## Commands

### Backend (from project root)
```bash
pip install -e .              # Install dependencies
pip install -e ".[dev]"       # Install with dev/test dependencies
uvicorn backend.main:app --reload   # Run dev server (port 8000)
pytest                        # Run all tests
pytest tests/test_foo.py::test_bar  # Run a single test
```

### Frontend (from `frontend/`)
```bash
npm install                   # Install dependencies
npm run dev                   # Vite dev server (port 5173)
npm run build                 # TypeScript check + production build
npm run lint                  # ESLint
```

## Architecture

### Backend (`backend/`)

**Entrypoint**: `main.py` — FastAPI app with lifespan that starts/stops the APScheduler.

**Core trading loop** (`engine/pair_job.py` → `run_pair_cycle()`):
1. Load pair config + encrypted credential from DB
2. Fetch candles from Hyperliquid (`services/market_data.py`)
3. Compute signals — z-score, hedge ratio, ADX, RSI, half-life (`services/signal_engine.py`, stateless)
4. Entry/exit decision logic
5. Place orders on Lighter DEX (`services/lighter_client.py`)
6. Persist results: `OpenPosition`, `Trade`, `EquitySnapshot`, `JobLog`

**Scheduling**: `engine/scheduler.py` — APScheduler integration; each active `TradingPair` gets its own interval job. `engine/position_sync.py` reconciles DB positions with exchange state on startup.

**Models** (`models/`): SQLModel ORM — `TradingPair` (40+ strategy params), `Credential` (Fernet-encrypted API keys), `Trade`, `OpenPosition`, `EquitySnapshot`, `JobLog`.

**API routers** (`api/`): `pairs`, `trades`, `positions`, `dashboard`, `credentials`, `system`, `markets`.

### Frontend (`frontend/src/`)

React 19 + TypeScript + Vite + Tailwind CSS. React Query for server state, React Router for navigation, Recharts for charts, Axios for HTTP.

**Pages**: `DashboardPage`, `PairsPage`, `PairDetailPage`, `CredentialsPage`, `LogsPage`.

## Configuration

Environment variables prefixed with `TS_` (loaded from `.env`):
- `TS_ENCRYPTION_KEY` — Fernet key for credential encryption
- `TS_LOG_LEVEL` — Logging level (default: INFO)
- `TS_DATABASE_URL` — SQLite URL (default: `data/trading.db`)
- `TS_CORS_ORIGINS` — Allowed origins (default: localhost:5173)

## Key Design Decisions

- **Signal engine is stateless**: all indicators computed fresh each cycle from raw candle data; no internal state accumulation.
- **Hyperliquid for data, Lighter for execution**: market data comes from Hyperliquid SDK; trades execute on Lighter DEX.
- **Credentials encrypted at rest**: Fernet symmetric encryption; key stored in env, not in DB.
- **One scheduler job per pair**: each `TradingPair` runs on its own interval; toggling a pair adds/removes its job.
