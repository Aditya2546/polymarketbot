"""
Market Mapping - Polymarket to Kalshi market equivalence.

Maps Polymarket markets to their Kalshi equivalents using scoring
based on underlying asset, time window, contract type, and strike.
"""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


class Underlying(str, Enum):
    """Supported underlying assets."""
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"
    UNKNOWN = "UNKNOWN"


class ContractType(str, Enum):
    """Contract types."""
    UP_DOWN_15M = "UP_DOWN_15M"  # 15-minute up/down
    UP_DOWN_1H = "UP_DOWN_1H"    # 1-hour up/down
    ABOVE_BELOW = "ABOVE_BELOW"  # Above/below strike
    RANGE = "RANGE"              # Range bound
    UNKNOWN = "UNKNOWN"


@dataclass
class MarketFeatures:
    """Extracted features from a market."""
    underlying: Underlying = Underlying.UNKNOWN
    contract_type: ContractType = ContractType.UNKNOWN
    expiry_ts: Optional[int] = None  # Unix timestamp ms
    strike: Optional[float] = None   # Strike price if applicable
    window_minutes: int = 15         # Time window in minutes
    raw_title: str = ""


@dataclass 
class MappingResult:
    """Result of mapping a Polymarket market to Kalshi."""
    polymarket_market_id: str
    kalshi_market_id: Optional[str] = None
    kalshi_ticker: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    feature_breakdown: Dict[str, float] = field(default_factory=dict)
    polymarket_features: Optional[MarketFeatures] = None
    kalshi_features: Optional[MarketFeatures] = None
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    @property
    def is_mappable(self) -> bool:
        """Check if mapping confidence is sufficient."""
        from ..config import get_settings
        return (
            self.kalshi_market_id is not None and
            self.confidence >= get_settings().min_mapping_confidence
        )


class MarketMapping:
    """
    Maps Polymarket markets to Kalshi equivalents.
    
    Uses a weighted scoring system:
    - underlying_match (40%): Same underlying asset
    - time_proximity (30%): Similar expiry time
    - contract_type (20%): Same contract structure
    - strike_similarity (10%): Similar strike price
    """
    
    # Scoring weights
    WEIGHT_UNDERLYING = 0.40
    WEIGHT_TIME = 0.30
    WEIGHT_CONTRACT = 0.20
    WEIGHT_STRIKE = 0.10
    
    # Time proximity settings
    MAX_TIME_DIFF_MINUTES = 30  # Max acceptable time difference
    
    def __init__(self):
        self._kalshi_markets_cache: Dict[str, Any] = {}
        self._mapping_cache: Dict[str, MappingResult] = {}
    
    def extract_polymarket_features(self, title: str, market_id: str = "") -> MarketFeatures:
        """
        Extract features from a Polymarket market title.
        
        Examples:
        - "Bitcoin Up or Down - January 7, 6:45PM-7:00PM ET"
        - "Ethereum Up or Down - January 7, 7PM ET"
        """
        features = MarketFeatures(raw_title=title)
        
        # Detect underlying
        title_lower = title.lower()
        if "bitcoin" in title_lower or "btc" in title_lower:
            features.underlying = Underlying.BTC
        elif "ethereum" in title_lower or "eth" in title_lower:
            features.underlying = Underlying.ETH
        elif "solana" in title_lower or "sol" in title_lower:
            features.underlying = Underlying.SOL
        
        # Detect contract type
        if "up or down" in title_lower:
            features.contract_type = ContractType.UP_DOWN_15M
            features.window_minutes = 15
        elif "above" in title_lower or "below" in title_lower:
            features.contract_type = ContractType.ABOVE_BELOW
        
        # Extract time window
        # Pattern: "6:45PM-7:00PM" or "7PM ET"
        time_pattern = r"(\d{1,2}):?(\d{2})?(PM|AM)(?:-(\d{1,2}):?(\d{2})?(PM|AM))?"
        match = re.search(time_pattern, title, re.IGNORECASE)
        
        if match:
            # Parse start time
            start_h = int(match.group(1))
            start_m = int(match.group(2) or 0)
            start_ampm = match.group(3).upper()
            
            if start_ampm == "PM" and start_h != 12:
                start_h += 12
            elif start_ampm == "AM" and start_h == 12:
                start_h = 0
            
            # Parse end time if present
            if match.group(4):
                end_h = int(match.group(4))
                end_m = int(match.group(5) or 0)
                end_ampm = match.group(6).upper()
                
                if end_ampm == "PM" and end_h != 12:
                    end_h += 12
                elif end_ampm == "AM" and end_h == 12:
                    end_h = 0
                
                features.window_minutes = (end_h * 60 + end_m) - (start_h * 60 + start_m)
            else:
                features.window_minutes = 15  # Default
            
            # Calculate expiry timestamp (assuming today, ET timezone)
            # ET is UTC-5 or UTC-4 depending on DST
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Parse date from title if present
            date_match = re.search(r"January (\d{1,2})", title)
            if date_match:
                day = int(date_match.group(1))
                today = today.replace(day=day, month=1)
            
            # End time in ET, convert to UTC (assuming EST = UTC-5)
            if match.group(4):
                end_hour = end_h
                end_minute = end_m
            else:
                end_hour = start_h
                end_minute = start_m + 15
                if end_minute >= 60:
                    end_hour += 1
                    end_minute -= 60
            
            expiry = today.replace(hour=end_hour, minute=end_minute)
            expiry = expiry + timedelta(hours=5)  # ET to UTC
            features.expiry_ts = int(expiry.timestamp() * 1000)
        
        return features
    
    def extract_kalshi_features(self, market: Dict[str, Any]) -> MarketFeatures:
        """
        Extract features from a Kalshi market.
        
        Kalshi tickers: KXBTC15M-26JAN071845-45
        - KXBTC15M = BTC 15-minute
        - 26JAN07 = Jan 7, 2026
        - 1845 = 6:45 PM ET
        - 45 = strike related
        """
        ticker = market.get("ticker", "")
        title = market.get("title", "")
        
        features = MarketFeatures(raw_title=title)
        
        # Parse ticker
        ticker_upper = ticker.upper()
        
        # Detect underlying
        if "BTC" in ticker_upper:
            features.underlying = Underlying.BTC
        elif "ETH" in ticker_upper:
            features.underlying = Underlying.ETH
        elif "SOL" in ticker_upper:
            features.underlying = Underlying.SOL
        
        # Detect contract type from ticker
        if "15M" in ticker_upper:
            features.contract_type = ContractType.UP_DOWN_15M
            features.window_minutes = 15
        elif "1H" in ticker_upper:
            features.contract_type = ContractType.UP_DOWN_1H
            features.window_minutes = 60
        
        # Parse time from ticker: KXBTC15M-26JAN071845-45
        time_match = re.search(r"-\d{2}[A-Z]{3}\d{2}(\d{4})-", ticker)
        if time_match:
            time_str = time_match.group(1)  # e.g., "1845"
            hour = int(time_str[:2])
            minute = int(time_str[2:])
            
            # Parse date
            date_match = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", ticker)
            if date_match:
                year = 2000 + int(date_match.group(1))
                month_str = date_match.group(2)
                day = int(date_match.group(3))
                
                months = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                         "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
                month = months.get(month_str, 1)
                
                # Build expiry (time is in ET)
                expiry = datetime(year, month, day, hour, minute)
                expiry = expiry + timedelta(hours=5)  # ET to UTC
                features.expiry_ts = int(expiry.timestamp() * 1000)
        
        # Parse strike from market data
        if market.get("floor_strike"):
            features.strike = float(market["floor_strike"])
        
        return features
    
    def score_mapping(
        self,
        poly_features: MarketFeatures,
        kalshi_features: MarketFeatures
    ) -> Tuple[float, Dict[str, float]]:
        """
        Calculate mapping score between Polymarket and Kalshi markets.
        
        Returns:
            (total_score, breakdown_dict)
        """
        breakdown = {}
        
        # 1. Underlying match (binary)
        if poly_features.underlying == kalshi_features.underlying:
            breakdown["underlying"] = 1.0
        else:
            breakdown["underlying"] = 0.0
        
        # 2. Time proximity (linear decay)
        if poly_features.expiry_ts and kalshi_features.expiry_ts:
            time_diff_ms = abs(poly_features.expiry_ts - kalshi_features.expiry_ts)
            time_diff_minutes = time_diff_ms / (60 * 1000)
            
            if time_diff_minutes <= self.MAX_TIME_DIFF_MINUTES:
                breakdown["time_proximity"] = 1.0 - (time_diff_minutes / self.MAX_TIME_DIFF_MINUTES)
            else:
                breakdown["time_proximity"] = 0.0
        else:
            breakdown["time_proximity"] = 0.5  # Uncertain
        
        # 3. Contract type match (binary)
        if poly_features.contract_type == kalshi_features.contract_type:
            breakdown["contract_type"] = 1.0
        elif poly_features.contract_type == ContractType.UNKNOWN or kalshi_features.contract_type == ContractType.UNKNOWN:
            breakdown["contract_type"] = 0.5
        else:
            breakdown["contract_type"] = 0.0
        
        # 4. Strike similarity (for applicable contracts)
        if poly_features.strike and kalshi_features.strike:
            strike_diff_pct = abs(poly_features.strike - kalshi_features.strike) / poly_features.strike
            breakdown["strike_similarity"] = max(0, 1.0 - strike_diff_pct)
        else:
            breakdown["strike_similarity"] = 0.5  # N/A or uncertain
        
        # Calculate weighted total
        total = (
            breakdown["underlying"] * self.WEIGHT_UNDERLYING +
            breakdown["time_proximity"] * self.WEIGHT_TIME +
            breakdown["contract_type"] * self.WEIGHT_CONTRACT +
            breakdown["strike_similarity"] * self.WEIGHT_STRIKE
        )
        
        return total, breakdown
    
    def find_best_kalshi_match(
        self,
        polymarket_title: str,
        polymarket_market_id: str,
        kalshi_markets: List[Dict[str, Any]]
    ) -> MappingResult:
        """
        Find the best Kalshi market match for a Polymarket market.
        
        Args:
            polymarket_title: Polymarket market title
            polymarket_market_id: Polymarket market ID
            kalshi_markets: List of available Kalshi markets
            
        Returns:
            MappingResult with best match or no match
        """
        poly_features = self.extract_polymarket_features(polymarket_title, polymarket_market_id)
        
        best_score = 0.0
        best_match = None
        best_breakdown = {}
        best_kalshi_features = None
        
        for km in kalshi_markets:
            kalshi_features = self.extract_kalshi_features(km)
            score, breakdown = self.score_mapping(poly_features, kalshi_features)
            
            if score > best_score:
                best_score = score
                best_match = km
                best_breakdown = breakdown
                best_kalshi_features = kalshi_features
        
        # Build reason string
        if best_match:
            reason = f"Matched {poly_features.underlying.value} {poly_features.window_minutes}m market"
            if best_breakdown.get("time_proximity", 0) < 1.0:
                reason += f" (time diff penalty)"
        else:
            reason = "No suitable Kalshi market found"
        
        return MappingResult(
            polymarket_market_id=polymarket_market_id,
            kalshi_market_id=best_match.get("market_id") if best_match else None,
            kalshi_ticker=best_match.get("ticker") if best_match else None,
            confidence=best_score,
            reason=reason,
            feature_breakdown=best_breakdown,
            polymarket_features=poly_features,
            kalshi_features=best_kalshi_features
        )

