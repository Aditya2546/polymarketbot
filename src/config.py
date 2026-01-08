"""Configuration management."""

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


class Config:
    """Configuration manager for the trading system."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration.
        
        Args:
            config_path: Path to config file. If None, looks for config.yaml in project root.
        """
        if config_path is None:
            config_path = self._find_config_file()
        
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._load_config()
        self._override_from_env()
    
    def _find_config_file(self) -> str:
        """Find config file in project root."""
        current_dir = Path(__file__).parent.parent
        config_file = current_dir / "config.yaml"
        
        if not config_file.exists():
            template_file = current_dir / "config.template.yaml"
            if template_file.exists():
                raise FileNotFoundError(
                    f"Config file not found. Please copy {template_file} to {config_file} "
                    "and fill in your credentials."
                )
            else:
                raise FileNotFoundError(f"Config file not found: {config_file}")
        
        return str(config_file)
    
    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        with open(self.config_path, 'r') as f:
            self._config = yaml.safe_load(f)
    
    def _override_from_env(self) -> None:
        """Override config values from environment variables."""
        # API credentials from environment
        if api_key_id := os.getenv("KALSHI_API_KEY_ID"):
            self._config.setdefault("kalshi", {})["api_key_id"] = api_key_id
        if private_key_path := os.getenv("KALSHI_PRIVATE_KEY_PATH"):
            self._config.setdefault("kalshi", {})["private_key_path"] = private_key_path
        
        # Polymarket
        if poly_enabled := os.getenv("POLYMARKET_ENABLED"):
            self._config.setdefault("polymarket", {})["enabled"] = poly_enabled.lower() == "true"
        
        # Live trading safety
        if live_enabled := os.getenv("LIVE_TRADING_ENABLED"):
            self._config.setdefault("live_trading", {})["enabled"] = live_enabled.lower() == "true"
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """Get configuration value using dot notation.
        
        Args:
            key_path: Dot-separated path (e.g., "kalshi.api_key")
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        keys = key_path.split(".")
        value = self._config
        
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        
        return value
    
    def set(self, key_path: str, value: Any) -> None:
        """Set configuration value using dot notation.
        
        Args:
            key_path: Dot-separated path (e.g., "kalshi.api_key")
            value: Value to set
        """
        keys = key_path.split(".")
        config = self._config
        
        for key in keys[:-1]:
            config = config.setdefault(key, {})
        
        config[keys[-1]] = value
    
    @property
    def kalshi_api_key_id(self) -> str:
        """Get Kalshi API key ID."""
        return self.get("kalshi.api_key_id", "")
    
    @property
    def kalshi_private_key_path(self) -> str:
        """Get Kalshi private key path."""
        return self.get("kalshi.private_key_path", "")
    
    @property
    def kalshi_base_url(self) -> str:
        """Get Kalshi base URL."""
        return self.get("kalshi.base_url", "https://trading-api.kalshi.com/trade-api/v2")
    
    @property
    def kalshi_ws_url(self) -> str:
        """Get Kalshi WebSocket URL."""
        return self.get("kalshi.ws_url", "wss://trading-api.kalshi.com/trade-api/ws/v2")
    
    @property
    def initial_bankroll(self) -> float:
        """Get initial bankroll in USD."""
        return self.get("risk.initial_bankroll_usd", 200.0)
    
    @property
    def max_risk_per_trade_usd(self) -> float:
        """Get max risk per trade in USD."""
        return self.get("risk.position_sizing.max_risk_per_trade_usd", 8.0)
    
    @property
    def max_open_exposure_usd(self) -> float:
        """Get max open exposure in USD."""
        return self.get("risk.position_sizing.max_open_exposure_usd", 24.0)
    
    @property
    def daily_loss_limit_usd(self) -> float:
        """Get daily loss limit in USD."""
        return self.get("risk.circuit_breakers.daily_loss_limit_usd", 20.0)
    
    @property
    def min_edge_threshold(self) -> float:
        """Get minimum edge threshold."""
        return self.get("edge_detection.min_edge_threshold", 0.03)
    
    @property
    def settlement_convention(self) -> str:
        """Get settlement convention (A or B)."""
        return self.get("settlement.convention", "A")
    
    @property
    def num_monte_carlo_sims(self) -> int:
        """Get number of Monte Carlo simulations."""
        return self.get("probability.monte_carlo.num_simulations", 10000)
    
    @property
    def live_trading_enabled(self) -> bool:
        """Check if live trading is enabled."""
        return self.get("live_trading.enabled", False)
    
    @property
    def paper_trading_enabled(self) -> bool:
        """Check if paper trading is enabled."""
        return self.get("paper_trading.enabled", True)
    
    def validate(self) -> None:
        """Validate configuration.
        
        Raises:
            ValueError: If configuration is invalid
        """
        # Check required API credentials
        if not self.kalshi_api_key_id or not self.kalshi_private_key_path:
            raise ValueError(
                "Kalshi API credentials not configured. "
                "Please set kalshi.api_key_id and kalshi.private_key_path in config.yaml "
                "or set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH environment variables. "
                "Get your API key at: https://kalshi.com/account/api"
            )
        
        # Validate risk parameters
        if self.max_risk_per_trade_usd > self.initial_bankroll:
            raise ValueError(
                f"max_risk_per_trade_usd ({self.max_risk_per_trade_usd}) "
                f"cannot exceed initial_bankroll ({self.initial_bankroll})"
            )
        
        if self.max_open_exposure_usd > self.initial_bankroll:
            raise ValueError(
                f"max_open_exposure_usd ({self.max_open_exposure_usd}) "
                f"cannot exceed initial_bankroll ({self.initial_bankroll})"
            )
        
        # Validate settlement convention
        if self.settlement_convention not in ["A", "B"]:
            raise ValueError(
                f"Invalid settlement convention: {self.settlement_convention}. "
                "Must be 'A' or 'B'."
            )
        
        # Validate edge threshold
        if self.min_edge_threshold <= 0 or self.min_edge_threshold >= 1:
            raise ValueError(
                f"min_edge_threshold ({self.min_edge_threshold}) must be between 0 and 1"
            )


# Global config instance
_config: Optional[Config] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """Get global configuration instance.
    
    Args:
        config_path: Path to config file (only used on first call)
        
    Returns:
        Config instance
    """
    global _config
    if _config is None:
        _config = Config(config_path)
    return _config


def reload_config(config_path: Optional[str] = None) -> Config:
    """Reload configuration.
    
    Args:
        config_path: Path to config file
        
    Returns:
        New Config instance
    """
    global _config
    _config = Config(config_path)
    return _config

