"""Structured logging setup."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.
        
        Args:
            record: Log record
            
        Returns:
            JSON string
        """
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)
        
        return json.dumps(log_data)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter."""
    
    def __init__(self):
        """Initialize formatter."""
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )


def setup_logging(
    level: str = "INFO",
    log_format: str = "json",
    log_dir: Optional[str] = None,
    console_enabled: bool = True
) -> None:
    """Setup logging configuration.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_format: Format ("json" or "text")
        log_dir: Directory for log files
        console_enabled: Whether to log to console
    """
    # Create log directory if needed
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    # Choose formatter
    if log_format == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    if console_enabled:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # File handler
    if log_dir:
        file_handler = logging.FileHandler(
            Path(log_dir) / "main.log",
            mode="a"
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Get logger with name.
    
    Args:
        name: Logger name
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class StructuredLogger:
    """Logger with structured data support."""
    
    def __init__(self, name: str):
        """Initialize logger.
        
        Args:
            name: Logger name
        """
        self.logger = logging.getLogger(name)
    
    def _log(
        self,
        level: int,
        message: str,
        **kwargs: Any
    ) -> None:
        """Log with structured data.
        
        Args:
            level: Log level
            message: Log message
            **kwargs: Additional structured data
        """
        extra = {"extra_data": kwargs} if kwargs else {}
        self.logger.log(level, message, extra=extra)
    
    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self._log(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message."""
        self._log(logging.CRITICAL, message, **kwargs)


class TradeLogger:
    """Specialized logger for trades."""
    
    def __init__(self, log_file: str):
        """Initialize trade logger.
        
        Args:
            log_file: Path to log file
        """
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def log_trade(
        self,
        trade_type: str,
        market_id: str,
        side: str,
        size: float,
        price: float,
        edge: float,
        **kwargs: Any
    ) -> None:
        """Log trade.
        
        Args:
            trade_type: Type of trade ("signal", "paper", "live")
            market_id: Market identifier
            side: "YES" or "NO"
            size: Position size in USD
            price: Execution price
            edge: Edge at entry
            **kwargs: Additional data
        """
        trade_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": trade_type,
            "market_id": market_id,
            "side": side,
            "size": size,
            "price": price,
            "edge": edge,
            **kwargs
        }
        
        with open(self.log_file, "a") as f:
            f.write(json.dumps(trade_data) + "\n")
    
    def log_signal(
        self,
        market_id: str,
        side: str,
        p_true: float,
        p_market: float,
        edge: float,
        recommended_size: float,
        reason: str,
        **kwargs: Any
    ) -> None:
        """Log trade signal.
        
        Args:
            market_id: Market identifier
            side: "YES" or "NO"
            p_true: True probability
            p_market: Market probability
            edge: Computed edge
            recommended_size: Recommended position size
            reason: Signal reason/type
            **kwargs: Additional data
        """
        self.log_trade(
            trade_type="signal",
            market_id=market_id,
            side=side,
            size=recommended_size,
            price=p_market,
            edge=edge,
            p_true=p_true,
            reason=reason,
            **kwargs
        )


class LatencyLogger:
    """Specialized logger for latency measurements."""
    
    def __init__(self, log_file: str):
        """Initialize latency logger.
        
        Args:
            log_file: Path to log file
        """
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def log_latency(
        self,
        source: str,
        latency_ms: float,
        **kwargs: Any
    ) -> None:
        """Log latency measurement.
        
        Args:
            source: Data source identifier
            latency_ms: Latency in milliseconds
            **kwargs: Additional data
        """
        latency_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": source,
            "latency_ms": latency_ms,
            **kwargs
        }
        
        with open(self.log_file, "a") as f:
            f.write(json.dumps(latency_data) + "\n")

