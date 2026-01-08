"""
Persistent trade tracking and performance monitoring.

Tracks all trades, predictions, and performance metrics to disk.
"""

import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from dataclasses import dataclass, asdict

from ..logger import StructuredLogger


@dataclass
class TradeRecord:
    """Single trade record."""
    timestamp: str
    market_id: str
    ticker: str
    side: str  # YES or NO
    size: float
    entry_price: float
    p_true: float
    p_market: float
    edge: float
    confidence: float
    status: str  # open, closed, cancelled
    outcome: Optional[str] = None
    pnl: Optional[float] = None
    close_timestamp: Optional[str] = None
    baseline: Optional[float] = None
    final_price: Optional[float] = None
    won: Optional[bool] = None


@dataclass
class PredictionRecord:
    """Single prediction record."""
    timestamp: str
    market_id: str
    ticker: str
    baseline: float
    current_price: float
    p_yes: float
    p_no: float
    confidence: float
    predicted_outcome: str
    market_price_yes: float
    edge: float
    traded: bool


class TradeTracker:
    """Tracks all trades and predictions to disk."""
    
    def __init__(self, data_dir: str = "data/trading"):
        self.logger = StructuredLogger(__name__)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.trades_file = self.data_dir / "trades.jsonl"
        self.predictions_file = self.data_dir / "predictions.jsonl"
        self.performance_file = self.data_dir / "performance.json"
        
        # In-memory tracking
        self.open_trades: Dict[str, TradeRecord] = {}
        self.closed_trades: List[TradeRecord] = []
        self.predictions: List[PredictionRecord] = []
        
        # Performance metrics
        self.balance = 200.0  # Starting balance
        self.peak_balance = 200.0
        
        # Load existing data
        self._load_data()
    
    def _load_data(self):
        """Load existing trades and predictions from disk."""
        # Load trades
        if self.trades_file.exists():
            with open(self.trades_file, 'r') as f:
                for line in f:
                    trade_dict = json.loads(line)
                    trade = TradeRecord(**trade_dict)
                    
                    if trade.status == "open":
                        self.open_trades[trade.market_id] = trade
                    else:
                        self.closed_trades.append(trade)
        
        # Load predictions
        if self.predictions_file.exists():
            with open(self.predictions_file, 'r') as f:
                for line in f:
                    pred_dict = json.loads(line)
                    pred = PredictionRecord(**pred_dict)
                    self.predictions.append(pred)
        
        # Load performance
        if self.performance_file.exists():
            with open(self.performance_file, 'r') as f:
                perf = json.load(f)
                self.balance = perf.get('balance', 200.0)
                self.peak_balance = perf.get('peak_balance', 200.0)
        
        self.logger.info(f"Loaded {len(self.closed_trades)} closed trades, "
                        f"{len(self.open_trades)} open trades, "
                        f"{len(self.predictions)} predictions")
    
    def record_prediction(self, pred: PredictionRecord):
        """Record a prediction."""
        self.predictions.append(pred)
        
        # Append to file
        with open(self.predictions_file, 'a') as f:
            f.write(json.dumps(asdict(pred)) + '\n')
    
    def open_trade(self, trade: TradeRecord) -> bool:
        """
        Open a new trade.
        
        Returns True if trade opened successfully, False if insufficient funds.
        """
        if trade.size > self.balance:
            self.logger.warning(f"Insufficient balance: ${self.balance:.2f} < ${trade.size:.2f}")
            return False
        
        # Deduct from balance
        self.balance -= trade.size
        
        # Record trade
        self.open_trades[trade.market_id] = trade
        
        # Append to file
        with open(self.trades_file, 'a') as f:
            f.write(json.dumps(asdict(trade)) + '\n')
        
        self._save_performance()
        
        self.logger.info(f"Opened {trade.side} trade on {trade.ticker} "
                        f"for ${trade.size:.2f} @ {trade.entry_price:.3f}")
        
        return True
    
    def close_trade(self, market_id: str, outcome: str, final_price: float):
        """Close an open trade with the settlement outcome."""
        if market_id not in self.open_trades:
            self.logger.warning(f"No open trade found for {market_id}")
            return
        
        trade = self.open_trades[market_id]
        
        # Calculate P&L
        won = (trade.side == outcome)
        
        if won:
            # Win: get back stake + profit
            payout = trade.size / trade.entry_price
            pnl = payout - trade.size
            self.balance += payout
        else:
            # Loss: lose the stake
            pnl = -trade.size
        
        # Update trade
        trade.outcome = outcome
        trade.pnl = pnl
        trade.final_price = final_price
        trade.close_timestamp = datetime.now().isoformat()
        trade.status = "closed"
        
        # Move to closed trades
        self.closed_trades.append(trade)
        del self.open_trades[market_id]
        
        # Update peak
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        
        # Re-write trades file (to update status)
        self._rewrite_trades_file()
        self._save_performance()
        
        result = "WON" if won else "LOST"
        self.logger.info(f"{result} trade on {trade.ticker}: "
                        f"{trade.side} @ {trade.entry_price:.3f}, "
                        f"outcome: {outcome}, "
                        f"P&L: ${pnl:+.2f}, "
                        f"Balance: ${self.balance:.2f}")
    
    def _rewrite_trades_file(self):
        """Rewrite entire trades file (called after updates)."""
        with open(self.trades_file, 'w') as f:
            for trade in self.closed_trades:
                f.write(json.dumps(asdict(trade)) + '\n')
            for trade in self.open_trades.values():
                f.write(json.dumps(asdict(trade)) + '\n')
    
    def _save_performance(self):
        """Save performance metrics."""
        perf = {
            'balance': self.balance,
            'peak_balance': self.peak_balance,
            'last_update': datetime.now().isoformat()
        }
        
        with open(self.performance_file, 'w') as f:
            json.dump(perf, f, indent=2)
    
    def get_stats(self) -> Dict:
        """Get performance statistics."""
        if not self.closed_trades:
            return {
                'balance': self.balance,
                'initial': 200.0,
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'roi': 0,
                'drawdown': 0,
                'open_trades': len(self.open_trades)
            }
        
        wins = sum(1 for t in self.closed_trades if t.pnl and t.pnl > 0)
        total_pnl = sum(t.pnl for t in self.closed_trades if t.pnl)
        roi = (self.balance - 200.0) / 200.0
        drawdown = (self.peak_balance - self.balance) / self.peak_balance if self.peak_balance > 0 else 0
        
        return {
            'balance': self.balance,
            'initial': 200.0,
            'total_trades': len(self.closed_trades),
            'wins': wins,
            'losses': len(self.closed_trades) - wins,
            'win_rate': wins / len(self.closed_trades) if self.closed_trades else 0,
            'total_pnl': total_pnl,
            'roi': roi,
            'drawdown': drawdown,
            'peak_balance': self.peak_balance,
            'open_trades': len(self.open_trades)
        }
    
    def export_csv(self):
        """Export trades and predictions to CSV for analysis."""
        # Export trades
        if self.closed_trades:
            trades_df = pd.DataFrame([asdict(t) for t in self.closed_trades])
            trades_csv = self.data_dir / "trades.csv"
            trades_df.to_csv(trades_csv, index=False)
            self.logger.info(f"Exported {len(self.closed_trades)} trades to {trades_csv}")
        
        # Export predictions
        if self.predictions:
            preds_df = pd.DataFrame([asdict(p) for p in self.predictions])
            preds_csv = self.data_dir / "predictions.csv"
            preds_df.to_csv(preds_csv, index=False)
            self.logger.info(f"Exported {len(self.predictions)} predictions to {preds_csv}")
    
    def print_summary(self):
        """Print a summary of performance."""
        stats = self.get_stats()
        
        print()
        print("=" * 80)
        print("📊 TRADING PERFORMANCE SUMMARY")
        print("=" * 80)
        print()
        print(f"Balance:          ${stats.get('balance', 0):.2f}")
        print(f"Starting:         ${stats.get('initial', 200):.2f}")
        print(f"P&L:              ${stats.get('total_pnl', 0):+.2f}")
        print(f"ROI:              {stats.get('roi', 0):+.1%}")
        print(f"Peak Balance:     ${stats.get('peak_balance', 200):.2f}")
        print(f"Drawdown:         {stats.get('drawdown', 0):.1%}")
        print()
        print(f"Total Trades:     {stats.get('total_trades', 0)}")
        print(f"Wins:             {stats.get('wins', 0)}")
        print(f"Losses:           {stats.get('losses', 0)}")
        print(f"Win Rate:         {stats.get('win_rate', 0):.1%}")
        print(f"Open Trades:      {stats.get('open_trades', 0)}")
        print()
        
        if self.closed_trades:
            winning_trades = [t for t in self.closed_trades if t.pnl and t.pnl > 0]
            losing_trades = [t for t in self.closed_trades if t.pnl and t.pnl <= 0]
            
            if winning_trades:
                avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades)
                print(f"Avg Win:          ${avg_win:+.2f}")
            
            if losing_trades:
                avg_loss = sum(t.pnl for t in losing_trades) / len(losing_trades)
                print(f"Avg Loss:         ${avg_loss:+.2f}")
        
        print("=" * 80)
        print()

