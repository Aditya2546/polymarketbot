"""Backtesting engine for historical simulation."""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from ..logger import StructuredLogger


class BacktestTrade:
    """Backtest trade record."""
    
    def __init__(
        self,
        timestamp: float,
        interval_start: float,
        interval_end: float,
        baseline: float,
        side: str,
        entry_price: float,
        size_usd: float,
        edge_at_entry: float,
        signal_type: str
    ):
        """Initialize backtest trade.
        
        Args:
            timestamp: Entry timestamp
            interval_start: Interval start time
            interval_end: Interval end time (settlement)
            baseline: Baseline price
            side: "YES" or "NO"
            entry_price: Entry price
            size_usd: Position size
            edge_at_entry: Edge at entry
            signal_type: Signal type
        """
        self.timestamp = timestamp
        self.interval_start = interval_start
        self.interval_end = interval_end
        self.baseline = baseline
        self.side = side
        self.entry_price = entry_price
        self.size_usd = size_usd
        self.edge_at_entry = edge_at_entry
        self.signal_type = signal_type
        
        # Filled at settlement
        self.settlement_avg60: Optional[float] = None
        self.outcome: Optional[str] = None  # "YES" or "NO"
        self.pnl: Optional[float] = None
        self.won: Optional[bool] = None
    
    def settle(self, avg60: float) -> None:
        """Settle trade.
        
        Args:
            avg60: Settlement average price
        """
        self.settlement_avg60 = avg60
        
        # Determine outcome
        if avg60 > self.baseline:
            self.outcome = "YES"
        else:
            self.outcome = "NO"
        
        # Determine if won
        self.won = (self.side == self.outcome)
        
        # Compute PnL
        if self.won:
            # Win: gain size * (1 - entry_price)
            self.pnl = self.size_usd * (1 - self.entry_price)
        else:
            # Loss: lose size * entry_price
            self.pnl = -self.size_usd * self.entry_price


class BacktestEngine:
    """Backtesting engine for historical simulation."""
    
    def __init__(
        self,
        data_file: str,
        timestamp_column: str = "timestamp",
        price_column: str = "price",
        interval_minutes: int = 15,
        assumed_spread_pct: float = 0.01,
        fee_pct: float = 0.007,
        fill_rate: float = 0.95
    ):
        """Initialize backtest engine.
        
        Args:
            data_file: Path to historical data CSV
            timestamp_column: Name of timestamp column
            price_column: Name of price column
            interval_minutes: Interval duration in minutes
            assumed_spread_pct: Assumed spread
            fee_pct: Fee per trade
            fill_rate: Probability of fill
        """
        self.data_file = data_file
        self.timestamp_column = timestamp_column
        self.price_column = price_column
        self.interval_minutes = interval_minutes
        self.assumed_spread_pct = assumed_spread_pct
        self.fee_pct = fee_pct
        self.fill_rate = fill_rate
        
        # Data
        self.df: Optional[pd.DataFrame] = None
        
        # Trades
        self.trades: List[BacktestTrade] = []
        
        # Logging
        self.logger = StructuredLogger(__name__)
    
    def load_data(self) -> None:
        """Load historical data."""
        self.logger.info(f"Loading data from {self.data_file}")
        
        self.df = pd.read_csv(self.data_file)
        
        # Parse timestamps
        self.df[self.timestamp_column] = pd.to_datetime(
            self.df[self.timestamp_column]
        ).astype(int) / 10**9  # Convert to Unix seconds
        
        self.logger.info(
            f"Loaded {len(self.df)} data points",
            start=self.df[self.timestamp_column].min(),
            end=self.df[self.timestamp_column].max()
        )
    
    def generate_intervals(
        self,
        start_date: str,
        end_date: str
    ) -> List[Tuple[float, float]]:
        """Generate 15-minute intervals.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            List of (start_timestamp, end_timestamp) tuples
        """
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        intervals = []
        current = start_dt
        
        while current < end_dt:
            interval_start = current.timestamp()
            interval_end = (current + timedelta(minutes=self.interval_minutes)).timestamp()
            
            intervals.append((interval_start, interval_end))
            
            current += timedelta(minutes=self.interval_minutes)
        
        return intervals
    
    def compute_avg60(
        self,
        end_timestamp: float,
        convention: str = "A"
    ) -> Optional[float]:
        """Compute 60-second average for settlement.
        
        Args:
            end_timestamp: Settlement timestamp
            convention: "A" or "B"
            
        Returns:
            Average price or None
        """
        if self.df is None:
            return None
        
        if convention == "A":
            start_time = end_timestamp - 60
            end_time = end_timestamp - 1
        else:
            start_time = end_timestamp - 60
            end_time = end_timestamp
        
        # Filter data in window
        mask = (
            (self.df[self.timestamp_column] >= start_time) &
            (self.df[self.timestamp_column] <= end_time)
        )
        
        window_data = self.df[mask]
        
        if len(window_data) == 0:
            return None
        
        return float(window_data[self.price_column].mean())
    
    def simulate_strategy(
        self,
        intervals: List[Tuple[float, float]],
        strategy_func: callable,
        initial_bankroll: float = 200.0
    ) -> Dict:
        """Simulate strategy over intervals.
        
        Args:
            intervals: List of interval tuples
            strategy_func: Strategy function(interval_start, interval_end, baseline, df) -> Optional[signal]
            initial_bankroll: Initial bankroll
            
        Returns:
            Simulation results
        """
        self.trades = []
        bankroll = initial_bankroll
        peak_bankroll = initial_bankroll
        
        for interval_start, interval_end in intervals:
            # Get baseline (price at interval start)
            baseline_mask = (
                (self.df[self.timestamp_column] >= interval_start - 5) &
                (self.df[self.timestamp_column] <= interval_start + 5)
            )
            baseline_data = self.df[baseline_mask]
            
            if len(baseline_data) == 0:
                continue
            
            baseline = float(baseline_data[self.price_column].iloc[0])
            
            # Get interval data
            interval_mask = (
                (self.df[self.timestamp_column] >= interval_start) &
                (self.df[self.timestamp_column] <= interval_end)
            )
            interval_df = self.df[interval_mask]
            
            if len(interval_df) < 60:  # Need at least 60 seconds of data
                continue
            
            # Run strategy
            signal = strategy_func(interval_start, interval_end, baseline, interval_df)
            
            if signal is None:
                continue
            
            # Check fill rate
            if np.random.random() > self.fill_rate:
                continue  # Missed fill
            
            # Create trade
            trade = BacktestTrade(
                timestamp=signal.get("timestamp", interval_start),
                interval_start=interval_start,
                interval_end=interval_end,
                baseline=baseline,
                side=signal["side"],
                entry_price=signal["entry_price"],
                size_usd=signal["size_usd"],
                edge_at_entry=signal.get("edge", 0.0),
                signal_type=signal.get("signal_type", "unknown")
            )
            
            # Compute settlement
            avg60 = self.compute_avg60(interval_end)
            
            if avg60 is None:
                continue
            
            trade.settle(avg60)
            
            # Update bankroll
            if trade.pnl is not None:
                bankroll += trade.pnl
                peak_bankroll = max(peak_bankroll, bankroll)
            
            self.trades.append(trade)
        
        # Compute metrics
        metrics = self.compute_metrics(initial_bankroll, peak_bankroll, bankroll)
        
        return metrics
    
    def compute_metrics(
        self,
        initial_bankroll: float,
        peak_bankroll: float,
        final_bankroll: float
    ) -> Dict:
        """Compute backtest metrics.
        
        Args:
            initial_bankroll: Initial bankroll
            peak_bankroll: Peak bankroll
            final_bankroll: Final bankroll
            
        Returns:
            Metrics dictionary
        """
        if not self.trades:
            return {
                "num_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl_per_trade": 0
            }
        
        # Basic stats
        num_trades = len(self.trades)
        wins = sum(1 for t in self.trades if t.won)
        losses = num_trades - wins
        win_rate = wins / num_trades
        
        # PnL
        pnls = [t.pnl for t in self.trades if t.pnl is not None]
        total_pnl = sum(pnls)
        avg_pnl_per_trade = total_pnl / num_trades if num_trades > 0 else 0
        
        winning_trades = [t.pnl for t in self.trades if t.won and t.pnl is not None]
        losing_trades = [t.pnl for t in self.trades if not t.won and t.pnl is not None]
        
        avg_win = np.mean(winning_trades) if winning_trades else 0
        avg_loss = np.mean(losing_trades) if losing_trades else 0
        
        # Drawdown
        max_drawdown = (peak_bankroll - final_bankroll) / peak_bankroll if peak_bankroll > 0 else 0
        
        # Edge
        avg_edge_at_entry = np.mean([t.edge_at_entry for t in self.trades])
        
        # Sharpe (simplified)
        if len(pnls) > 1:
            returns = np.array(pnls) / initial_bankroll
            sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(365 * 96)  # Annualized
        else:
            sharpe_ratio = 0
        
        # Brier score (calibration)
        brier_score = self._compute_brier_score()
        
        # Edge attribution
        edge_attribution = self._compute_edge_attribution()
        
        # Longest losing streak
        worst_streak = self._compute_worst_streak()
        
        return {
            "num_trades": num_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_pnl_per_trade": avg_pnl_per_trade,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_drawdown": max_drawdown,
            "avg_edge_at_entry": avg_edge_at_entry,
            "sharpe_ratio": sharpe_ratio,
            "brier_score": brier_score,
            "edge_attribution": edge_attribution,
            "worst_streak": worst_streak,
            "final_bankroll": final_bankroll,
            "return_pct": (final_bankroll - initial_bankroll) / initial_bankroll
        }
    
    def _compute_brier_score(self) -> float:
        """Compute Brier score for probability calibration.
        
        Returns:
            Brier score (lower is better)
        """
        if not self.trades:
            return 0.0
        
        # For each trade, compare predicted probability (entry_price) to outcome
        scores = []
        
        for trade in self.trades:
            # Predicted probability of YES
            if trade.side == "YES":
                p_predicted = trade.entry_price
            else:
                p_predicted = 1 - trade.entry_price
            
            # Actual outcome (1 if YES, 0 if NO)
            actual = 1.0 if trade.outcome == "YES" else 0.0
            
            # Brier score component
            score = (p_predicted - actual) ** 2
            scores.append(score)
        
        return float(np.mean(scores))
    
    def _compute_edge_attribution(self) -> Dict:
        """Compute PnL attribution by signal type.
        
        Returns:
            Attribution dictionary
        """
        attribution = {}
        
        for trade in self.trades:
            signal_type = trade.signal_type
            
            if signal_type not in attribution:
                attribution[signal_type] = {
                    "num_trades": 0,
                    "total_pnl": 0.0,
                    "avg_pnl": 0.0
                }
            
            attribution[signal_type]["num_trades"] += 1
            attribution[signal_type]["total_pnl"] += trade.pnl if trade.pnl else 0
        
        # Compute averages
        for signal_type in attribution:
            num = attribution[signal_type]["num_trades"]
            if num > 0:
                attribution[signal_type]["avg_pnl"] = attribution[signal_type]["total_pnl"] / num
        
        return attribution
    
    def _compute_worst_streak(self) -> int:
        """Compute longest losing streak.
        
        Returns:
            Longest streak
        """
        if not self.trades:
            return 0
        
        max_streak = 0
        current_streak = 0
        
        for trade in self.trades:
            if not trade.won:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        
        return max_streak
    
    def export_trades(self, output_file: str) -> None:
        """Export trades to CSV.
        
        Args:
            output_file: Output file path
        """
        if not self.trades:
            self.logger.warning("No trades to export")
            return
        
        data = []
        
        for trade in self.trades:
            data.append({
                "timestamp": trade.timestamp,
                "interval_start": trade.interval_start,
                "interval_end": trade.interval_end,
                "baseline": trade.baseline,
                "side": trade.side,
                "entry_price": trade.entry_price,
                "size_usd": trade.size_usd,
                "edge_at_entry": trade.edge_at_entry,
                "signal_type": trade.signal_type,
                "settlement_avg60": trade.settlement_avg60,
                "outcome": trade.outcome,
                "won": trade.won,
                "pnl": trade.pnl
            })
        
        df = pd.DataFrame(data)
        df.to_csv(output_file, index=False)
        
        self.logger.info(f"Exported {len(data)} trades to {output_file}")

