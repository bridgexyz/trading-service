"""Credential model — encrypted Lighter DEX API credentials."""

from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class Credential(SQLModel, table=True):
    __tablename__ = "credential"

    id: int | None = Field(default=None, primary_key=True)
    name: str = "default"
    lighter_host: str = "https://mainnet.zklighter.elliot.ai"
    api_key_index: int = 3
    private_key_encrypted: str = ""  # Fernet-encrypted hex private key
    account_index: int = 0
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
