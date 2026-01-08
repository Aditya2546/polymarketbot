"""
Canonical CopySignal - The standardized format for all gabagool trades.

Every gabagool trade is converted to a CopySignal with deterministic ID
generation for idempotent processing.
"""

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from dataclasses import dataclass, field, asdict


class SignalSide(str, Enum):
    """Position side."""
    YES = "YES"
    NO = "NO"


class SignalAction(str, Enum):
    """Trade action."""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class CopySignal:
    """
    Canonical signal representing a gabagool trade to copy.
    
    The signal_id is deterministically generated from the source trade
    to ensure idempotent processing.
    """
    
    # Core identifiers
    signal_id: str  # Deterministic hash
    ts_ms: int  # Timestamp in milliseconds
    
    # Source
    source: str = "gabagool22"
    
    # Polymarket market info
    polymarket_market_id: str = ""
    polymarket_event_name: str = ""
    polymarket_slug: str = ""
    
    # Trade details
    side: SignalSide = SignalSide.YES
    action: SignalAction = SignalAction.BUY
    qty: float = 0.0  # Shares
    price: float = 0.0  # Fill price (0-1)
    value_usd: float = 0.0  # qty * price
    
    # Metadata
    meta: Dict[str, Any] = field(default_factory=dict)
    
    # Processing state
    processed: bool = False
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.value_usd == 0.0 and self.qty > 0 and self.price > 0:
            self.value_usd = self.qty * self.price
    
    @classmethod
    def generate_signal_id(
        cls,
        polymarket_trade_id: str,
        fill_index: int = 0,
        tx_hash: Optional[str] = None
    ) -> str:
        """
        Generate deterministic signal_id from trade identifiers.
        
        Args:
            polymarket_trade_id: The Polymarket trade/transaction ID
            fill_index: Index for multiple fills in same transaction
            tx_hash: Optional transaction hash for additional uniqueness
            
        Returns:
            Deterministic SHA256-based signal ID
        """
        components = [
            str(polymarket_trade_id),
            str(fill_index),
            str(tx_hash or "")
        ]
        payload = "|".join(components)
        return hashlib.sha256(payload.encode()).hexdigest()[:32]
    
    @classmethod
    def from_polymarket_trade(cls, trade: Dict[str, Any], fill_index: int = 0) -> "CopySignal":
        """
        Create a CopySignal from a raw Polymarket trade.
        
        Args:
            trade: Raw trade data from Polymarket API
            fill_index: Index if this is one of multiple fills
            
        Returns:
            CopySignal instance
        """
        # Extract trade ID - try multiple possible fields
        trade_id = (
            trade.get("id") or
            trade.get("transactionHash") or
            f"{trade.get('timestamp', 0)}_{trade.get('asset', '')}"
        )
        
        # Generate deterministic signal_id
        signal_id = cls.generate_signal_id(
            polymarket_trade_id=trade_id,
            fill_index=fill_index,
            tx_hash=trade.get("transactionHash")
        )
        
        # Parse timestamp
        ts = trade.get("timestamp", 0)
        if isinstance(ts, str):
            try:
                ts = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
            except:
                ts = int(float(ts) * 1000) if float(ts) < 1e12 else int(ts)
        elif ts > 1e12:
            ts = int(ts)  # Already in ms
        else:
            ts = int(ts * 1000)  # Convert seconds to ms
        
        # Determine side
        outcome = trade.get("outcome", "").lower()
        if "up" in outcome or outcome == "yes":
            side = SignalSide.YES
        elif "down" in outcome or outcome == "no":
            side = SignalSide.NO
        else:
            side = SignalSide.YES  # Default
        
        # Determine action
        action_str = trade.get("side", "BUY").upper()
        action = SignalAction.SELL if action_str == "SELL" else SignalAction.BUY
        
        # Extract quantities
        qty = float(trade.get("size", 0))
        price = float(trade.get("price", 0))
        
        # Build metadata
        meta = {
            "wallet": trade.get("proxyWallet", trade.get("user", "")),
            "tx_hash": trade.get("transactionHash", ""),
            "block_ts": trade.get("blockTimestamp"),
            "condition_id": trade.get("conditionId", ""),
            "asset": trade.get("asset", ""),
            "raw_outcome": trade.get("outcome", ""),
        }
        
        return cls(
            signal_id=signal_id,
            ts_ms=ts,
            source="gabagool22",
            polymarket_market_id=trade.get("conditionId", ""),
            polymarket_event_name=trade.get("title", ""),
            polymarket_slug=trade.get("slug", trade.get("eventSlug", "")),
            side=side,
            action=action,
            qty=qty,
            price=price,
            value_usd=qty * price,
            meta=meta
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        d = asdict(self)
        d["side"] = self.side.value
        d["action"] = self.action.value
        if self.created_at:
            d["created_at"] = self.created_at.isoformat()
        return d
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CopySignal":
        """Create from dictionary."""
        d = d.copy()
        d["side"] = SignalSide(d["side"])
        d["action"] = SignalAction(d["action"])
        if d.get("created_at"):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        return cls(**d)
    
    def __hash__(self):
        return hash(self.signal_id)
    
    def __eq__(self, other):
        if isinstance(other, CopySignal):
            return self.signal_id == other.signal_id
        return False

