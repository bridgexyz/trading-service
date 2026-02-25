"""Pydantic schemas for Credential API."""

from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator

_HEX_KEY_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64,}$")


class CredentialCreate(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=120)
    lighter_host: str = "https://mainnet.zklighter.elliot.ai"
    api_key_index: int = Field(default=3, ge=0)
    private_key: str  # Raw hex private key — will be encrypted before storage
    account_index: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("lighter_host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        host = value.strip()
        if not host:
            raise ValueError("must not be empty")
        if not (host.startswith("http://") or host.startswith("https://")):
            raise ValueError("must start with http:// or https://")
        return host.rstrip("/")

    @field_validator("private_key")
    @classmethod
    def _validate_private_key(cls, value: str) -> str:
        key = value.strip()
        if not key:
            raise ValueError("must not be empty")
        if not _HEX_KEY_RE.fullmatch(key):
            raise ValueError("must be a hex string (at least 64 chars), with optional 0x prefix")
        return key


class CredentialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    lighter_host: str | None = None
    api_key_index: int | None = Field(default=None, ge=0)
    private_key: str | None = None  # If provided, re-encrypts
    account_index: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _trim_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("lighter_host")
    @classmethod
    def _validate_optional_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        host = value.strip()
        if not host:
            raise ValueError("must not be empty")
        if not (host.startswith("http://") or host.startswith("https://")):
            raise ValueError("must start with http:// or https://")
        return host.rstrip("/")

    @field_validator("private_key")
    @classmethod
    def _validate_optional_private_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        key = value.strip()
        if not key:
            raise ValueError("must not be empty")
        if not _HEX_KEY_RE.fullmatch(key):
            raise ValueError("must be a hex string (at least 64 chars), with optional 0x prefix")
        return key


class CredentialRead(BaseModel):
    id: int
    name: str
    lighter_host: str
    api_key_index: int
    account_index: int
    is_active: bool
    created_at: datetime
    # private_key is NEVER exposed

    model_config = {"from_attributes": True}
