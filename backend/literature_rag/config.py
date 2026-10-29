"""Validated application settings."""

import ipaddress
import re
import unicodedata
from pathlib import Path
from typing import Self
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from defaults, environment variables, and ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="RAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path(".rag-data")
    chunk_size: int = Field(default=1200, gt=0)
    chunk_overlap: int = Field(default=200, ge=0)
    embedding_batch_size: int = Field(default=64, gt=0, le=2048)
    top_k: int = Field(default=8, ge=1, le=50)
    min_score: float = Field(default=0.35, ge=0, le=1, allow_inf_nan=False)
    context_expansion_enabled: bool = False
    context_neighbor_radius: int = Field(default=1,ge=0,le=2)
    context_max_evidence_chars: int = Field(default=8000,ge=256,le=100000)
    context_max_total_chars: int = Field(default=24000,ge=256,le=100000)

    embedding_provider: str = "openai"
    embedding_model: str | None = None
    embedding_dimensions: int | None = Field(default=None, gt=0)
    embedding_api_key: SecretStr | None = None
    embedding_base_url: str | None = None

    llm_provider: str = "openai"
    llm_model: str | None = None
    llm_thinking_enabled: bool | None = None
    llm_reasoning_effort: Literal['low', 'high', 'max'] | None = None
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None

    @field_validator("embedding_base_url", "llm_base_url", mode="before")
    @classmethod
    def validate_base_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            return None
        if any(
            character.isspace() or unicodedata.category(character) in {"Cc", "Cf"}
            for character in normalized
        ):
            raise ValueError("base URL must not contain whitespace or control characters")
        try:
            parsed = urlsplit(normalized)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as error:
            raise ValueError("base URL is malformed") from error
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not hostname:
            raise ValueError("base URL must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base URL must not contain user information")
        if parsed.query or parsed.fragment:
            raise ValueError("base URL must not contain a query or fragment")
        if port is not None and port == 0:
            raise ValueError("base URL port must be between 1 and 65535")
        cls._validate_hostname(hostname)
        return normalized

    @staticmethod
    def _validate_hostname(hostname: str) -> None:
        try:
            ipaddress.ip_address(hostname)
            return
        except ValueError:
            pass
        if re.fullmatch(r"[0-9.]+", hostname):
            raise ValueError("base URL host is malformed")
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii").removesuffix(".")
        except UnicodeError as error:
            raise ValueError("base URL host is malformed") from error
        labels = ascii_hostname.split(".")
        if (
            not ascii_hostname
            or len(ascii_hostname) > 253
            or any(
                not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in labels
            )
        ):
            raise ValueError("base URL host is malformed")

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> Self:
        """Ensure adjacent chunks do not completely overlap."""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self
