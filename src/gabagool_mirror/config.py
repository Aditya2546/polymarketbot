"""
Configuration management using Pydantic Settings.

All configuration is loaded from environment variables with sensible defaults.
"""

from enum import Enum
from typing import Optional, List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionMode(str, Enum):
    """Execution mode for the mirror bot."""
    SIM = "SIM"        # Replay stored data, no external calls
    SHADOW = "SHADOW"  # Real-time data, simulated execution
    LIVE = "LIVE"      # Real execution on Kalshi (if enabled)


class Settings(BaseSettings):
    """Application settings loaded from environment."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    # === Execution Mode ===
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.SHADOW,
        description="SIM, SHADOW, or LIVE"
    )
    
    # === Database ===
    database_url: str = Field(
        default="sqlite+aiosqlite:///data/gabagool_mirror.db",
        description="Async database URL (postgres or sqlite)"
    )
    
    # === Polymarket ===
    gabagool_wallet: str = Field(
        default="0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d",
        description="Gabagool's Polymarket wallet address"
    )
    polymarket_poll_interval_ms: int = Field(
        default=2000,
        description="Polling interval for Polymarket trades"
    )
    
    # === Kalshi ===
    kalshi_api_key_id: Optional[str] = Field(
        default=None,
        description="Kalshi API key ID"
    )
    kalshi_private_key_path: Optional[str] = Field(
        default=None,
        description="Path to Kalshi RSA private key"
    )
    kalshi_live_enabled: bool = Field(
        default=False,
        description="Enable live trading on Kalshi (DANGEROUS)"
    )
    kalshi_base_url: str = Field(
        default="https://trading-api.kalshi.com/trade-api/v2",
        description="Kalshi API base URL"
    )
    
    # === Mapping ===
    min_mapping_confidence: float = Field(
        default=0.7,
        ge=0.0, le=1.0,
        description="Minimum confidence to map Polymarket -> Kalshi"
    )
    
    # === Simulation ===
    default_latency_ms: int = Field(
        default=2000,
        description="Default simulated latency in ms"
    )
    slippage_bps_buffer: int = Field(
        default=50,
        description="Slippage buffer in basis points"
    )
    kalshi_fee_bps: int = Field(
        default=70,
        description="Kalshi fee in basis points"
    )
    
    # === Risk ===
    max_qty_scale: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="Max fraction of gabagool size to copy"
    )
    max_position_usd: float = Field(
        default=50.0,
        description="Maximum position size in USD per market"
    )
    max_total_exposure_usd: float = Field(
        default=200.0,
        description="Maximum total exposure across all markets"
    )
    daily_loss_limit_usd: float = Field(
        default=50.0,
        description="Daily loss limit to trigger circuit breaker"
    )
    max_drawdown_pct: float = Field(
        default=0.25,
        description="Maximum drawdown percentage"
    )
    
    # === Learning ===
    learning_enabled: bool = Field(
        default=True,
        description="Enable online learning"
    )
    learning_epsilon: float = Field(
        default=0.1,
        ge=0.0, le=1.0,
        description="Exploration rate for bandit"
    )
    
    # === Ops ===
    log_level: str = Field(default="INFO")
    metrics_port: int = Field(default=9090)
    health_port: int = Field(default=8080)
    
    # === Bounds for Learner ===
    min_mapping_confidence_bounds: tuple = Field(
        default=(0.5, 0.95),
        description="(min, max) bounds for learned mapping confidence"
    )
    slippage_bps_buffer_bounds: tuple = Field(
        default=(10, 200),
        description="(min, max) bounds for slippage buffer"
    )
    max_qty_scale_bounds: tuple = Field(
        default=(0.1, 1.0),
        description="(min, max) bounds for quantity scaling"
    )


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings

