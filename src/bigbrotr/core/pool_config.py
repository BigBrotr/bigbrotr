"""Configuration models for the async PostgreSQL pool."""

import os
from typing import Any

from pydantic import BaseModel, Field, SecretStr, ValidationInfo, field_validator, model_validator


class DatabaseConfig(BaseModel):
    """PostgreSQL connection parameters."""

    host: str = Field(default="localhost", min_length=1, description="Database hostname")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    database: str = Field(default="bigbrotr", min_length=1, description="Database name")
    user: str = Field(default="admin", min_length=1, description="Database user")
    password_env: str = Field(
        default="DB_ADMIN_PASSWORD",  # pragma: allowlist secret
        min_length=1,
        description="Environment variable name for database password",
    )
    password: SecretStr = Field(description="Database password (loaded from password_env)")

    @model_validator(mode="before")
    @classmethod
    def resolve_password(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Resolve the database password from the environment variable."""
        if isinstance(data, dict) and "password" not in data:
            env_var = data.get("password_env", "DB_ADMIN_PASSWORD")  # pragma: allowlist secret
            value = os.getenv(env_var)
            if not value:
                raise ValueError(f"{env_var} environment variable not set")
            data["password"] = SecretStr(value)
        return data


class LimitsConfig(BaseModel):
    """Connection pool size and resource limits."""

    min_size: int = Field(default=1, ge=1, le=100, description="Minimum connections")
    max_size: int = Field(default=5, ge=1, le=200, description="Maximum connections")
    max_queries: int = Field(default=50_000, ge=100, description="Queries before recycling")
    max_inactive_connection_lifetime: float = Field(
        default=300.0, ge=0.0, description="Idle timeout (seconds)"
    )

    @field_validator("max_size")
    @classmethod
    def validate_max_size(cls, v: int, info: ValidationInfo) -> int:
        """Ensure max_size >= min_size."""
        min_size = info.data.get("min_size", 1)
        if v < min_size:
            raise ValueError(f"max_size ({v}) must be >= min_size ({min_size})")
        return v


class TimeoutsConfig(BaseModel):
    """Timeout settings for pool operations (in seconds)."""

    acquisition: float = Field(default=10.0, ge=0.1, description="Connection acquisition timeout")


class RetryConfig(BaseModel):
    """Retry strategy for failed connection attempts."""

    max_attempts: int = Field(default=3, ge=1, le=10, description="Max retry attempts")
    initial_delay: float = Field(default=1.0, ge=0.1, description="Initial retry delay")
    max_delay: float = Field(default=10.0, ge=0.1, description="Maximum retry delay")
    exponential_backoff: bool = Field(default=True, description="Use exponential backoff")

    @field_validator("max_delay")
    @classmethod
    def validate_max_delay(cls, v: float, info: ValidationInfo) -> float:
        """Ensure max_delay >= initial_delay."""
        initial_delay = info.data.get("initial_delay", 1.0)
        if v < initial_delay:
            raise ValueError(f"max_delay ({v}) must be >= initial_delay ({initial_delay})")
        return v


class ServerSettingsConfig(BaseModel):
    """PostgreSQL server-side session settings."""

    application_name: str = Field(default="bigbrotr", min_length=1, description="Application name")
    timezone: str = Field(default="UTC", min_length=1, description="Timezone")
    statement_timeout: int = Field(
        default=0,
        ge=0,
        description=(
            "Server-side query timeout in milliseconds. Set to 0 (default) when using "
            "PgBouncer in transaction mode, as it is stripped by ignore_startup_parameters."
        ),
    )


class PoolConfig(BaseModel):
    """Aggregate configuration for the connection pool."""

    database: DatabaseConfig = Field(
        default_factory=lambda: DatabaseConfig.model_validate({}),
        description="PostgreSQL connection credentials",
    )
    limits: LimitsConfig = Field(
        default_factory=LimitsConfig, description="Connection pool size and resource limits"
    )
    timeouts: TimeoutsConfig = Field(
        default_factory=TimeoutsConfig, description="Pool operation timeouts"
    )
    retry: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry strategy for failed connections"
    )
    server_settings: ServerSettingsConfig = Field(
        default_factory=ServerSettingsConfig, description="PostgreSQL session-level settings"
    )
