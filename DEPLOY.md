# Production VPS Deployment

Deploy the trading service (FastAPI backend + React frontend) on a VPS using Docker and Caddy for automatic HTTPS.

## Prerequisites

- VPS with Ubuntu 22.04+ and at least 1 GB RAM
- Domain name with an A record pointed to the VPS IP
- SSH access to the VPS

## 1. VPS Initial Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker + Docker Compose
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect

# Install git
sudo apt install -y git

# Firewall: allow SSH, HTTP, HTTPS
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 2. Clone and Configure

```bash
git clone <your-repo-url> ~/trading-service
cd ~/trading-service

# Create data directory for SQLite persistence
mkdir -p data

# Copy example env and edit
cp .env.example .env
nano .env
```

Set these values in `.env`:

| Variable | Value |
|---|---|
| `TS_ENCRYPTION_KEY` | Generate: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `TS_JWT_SECRET` | Random string: `openssl rand -hex 32` |
| `TS_LOG_LEVEL` | `INFO` (or `WARNING` for less noise) |
| `TS_CORS_ORIGINS` | Set to `[]` — not needed in production (frontend served by FastAPI) |
| `DOMAIN` | Your domain, e.g. `trading.yourdomain.com` — Caddy auto-provisions HTTPS |

## 3. Build and Start

```bash
docker compose up -d --build
```

This builds the frontend and backend in a multi-stage Docker build, starts the FastAPI app on port 8000 (internal only), and starts Caddy as reverse proxy on ports 80/443 with automatic HTTPS via Let's Encrypt. Caddy waits for the app healthcheck before accepting traffic.

## 4. Create Admin User

```bash
docker compose exec -it app python -m backend.cli create-admin
```

You'll be prompted for a username and password. A TOTP secret and QR code will be displayed — scan it with your authenticator app for 2FA login.

## 5. Verify

- `https://your-domain.com` — React admin panel
- `https://your-domain.com/api/system/health` — returns `{"status": "ok"}`
- Log in with the admin credentials from step 4

## Ongoing Operations

### View Logs

```bash
docker compose logs -f app        # Backend logs
docker compose logs -f caddy      # Reverse proxy logs
```

### Restart

```bash
docker compose restart app
```

### Update to Latest Code

```bash
cd ~/trading-service
git pull
docker compose up -d --build
```

### Database Backup

```bash
# Simple copy (briefly stop writes for consistency)
cp data/trading.db data/trading.db.backup.$(date +%Y%m%d)

# Or use SQLite online backup (no downtime)
sqlite3 data/trading.db ".backup 'data/trading.db.backup'"
```

### Automated Backups (Cron)

```bash
mkdir -p ~/trading-service/data/backups
crontab -e
# Add this line for backups every 6 hours:
# 0 */6 * * * sqlite3 ~/trading-service/data/trading.db ".backup '~/trading-service/data/backups/trading.$(date +\%Y\%m\%d_\%H).db'"
```

## Key Files

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build (frontend + backend) |
| `docker-compose.yml` | App + Caddy services, volumes, healthcheck |
| `Caddyfile` | Reverse proxy config with auto-HTTPS |
| `.env` | All configuration (encryption key, JWT secret, domain) |

## Important Notes

- **Single worker only**: APScheduler requires exactly 1 Uvicorn worker (configured in Dockerfile CMD).
- **SQLite is fine** for this single-instance deployment; the volume mount persists data across container rebuilds.
- **CORS origins**: In production the frontend is served from the same origin via FastAPI's `StaticFiles` mount, so CORS is not needed. Set `TS_CORS_ORIGINS=[]`.
- **Emergency stop**: `POST /api/system/emergency-stop` (authenticated) closes all positions and disables all pairs.
