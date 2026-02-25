"""Application configuration via environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    database_url: str = "postgresql://trading:trading_secret@postgres:5432/trading"
    encryption_key: str = ""  # Fernet key; generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]  # Vite dev server

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_ids: list[int] = []

    model_config = {"env_prefix": "TS_", "env_file": ".env"}


settings = Settings()
