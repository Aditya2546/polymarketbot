"""
Trade Settler - Automatically settles trades when markets expire.

Checks the actual BTC price at settlement time and calculates P&L.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import re

from ..logger import StructuredLogger


class TradeSettler:
    """
    Automatically settles trades when their 15-minute window expires.
    """
    
    def __init__(self, data_dir: str, get_current_price_func):
        self.logger = StructuredLogger(__name__)
        self.data_dir = Path(data_dir)
        self.get_current_price = get_current_price_func
        
        self.trades_file = self.data_dir / "trades.jsonl"
        self.performance_file = self.data_dir / "performance.json"
        
        # Settlement window (15 minutes)
        self.settlement_minutes = 15
    
    def check_and_settle(self) -> List[Dict]:
        """
        Check all open trades and settle any that have expired.
        
        Returns list of settled trades with P&L.
        """
        if not self.trades_file.exists():
            return []
        
        current_price = self.get_current_price()
        if current_price is None:
            return []
        
        now = datetime.now()
        settled_trades = []
        all_trades = []
        
        # Read all trades
        with open(self.trades_file, 'r') as f:
            for line in f:
                try:
                    trade = json.loads(line)
                    all_trades.append(trade)
                except:
                    continue
        
        # Check each open trade
        balance_change = 0
        trades_modified = False
        
        for trade in all_trades:
            if trade.get('status') != 'open':
                continue
            
            # Parse trade timestamp
            try:
                trade_time = datetime.fromisoformat(trade['timestamp'])
            except:
                continue
            
            # Check if 15 minutes have passed
            elapsed = (now - trade_time).total_seconds() / 60
            
            if elapsed >= self.settlement_minutes:
                # Time to settle!
                baseline = trade.get('baseline', current_price)
                
                # Determine outcome: Did price go UP or DOWN vs baseline?
                actual_outcome = "YES" if current_price > baseline else "NO"
                
                # Did we win?
                won = (trade['side'] == actual_outcome)
                
                # Calculate P&L
                size = trade['size']
                entry_price = trade['entry_price']
                
                if won:
                    # Win: get back size/entry_price
                    payout = size / entry_price
                    pnl = payout - size
                else:
                    # Loss: lose the stake
                    pnl = -size
                    payout = 0
                
                # Update trade
                trade['status'] = 'closed'
                trade['outcome'] = actual_outcome
                trade['pnl'] = pnl
                trade['close_timestamp'] = now.isoformat()
                trade['final_price'] = current_price
                trade['won'] = won
                
                balance_change += payout
                trades_modified = True
                
                settled_trades.append(trade)
                
                self.logger.info(f"{'✅ WON' if won else '❌ LOST'}: {trade['side']} @ {entry_price:.3f} | "
                               f"Outcome: {actual_outcome} | P&L: ${pnl:+.2f}")
        
        # Rewrite trades file if any were modified
        if trades_modified:
            with open(self.trades_file, 'w') as f:
                for trade in all_trades:
                    f.write(json.dumps(trade) + '\n')
            
            # Update performance
            self._update_performance(balance_change)
        
        return settled_trades
    
    def _update_performance(self, balance_change: float):
        """Update performance file with balance change."""
        if not self.performance_file.exists():
            return
        
        with open(self.performance_file, 'r') as f:
            perf = json.load(f)
        
        perf['balance'] = perf.get('balance', 0) + balance_change
        
        if perf['balance'] > perf.get('peak_balance', 0):
            perf['peak_balance'] = perf['balance']
        
        perf['last_update'] = datetime.now().isoformat()
        
        with open(self.performance_file, 'w') as f:
            json.dump(perf, f, indent=2)
    
    def get_stats(self) -> Dict:
        """Get settlement statistics."""
        if not self.trades_file.exists():
            return {'open': 0, 'closed': 0, 'wins': 0, 'losses': 0, 'pnl': 0}
        
        open_count = 0
        closed_count = 0
        wins = 0
        losses = 0
        total_pnl = 0
        
        with open(self.trades_file, 'r') as f:
            for line in f:
                try:
                    trade = json.loads(line)
                    if trade.get('status') == 'open':
                        open_count += 1
                    elif trade.get('status') == 'closed':
                        closed_count += 1
                        if trade.get('won'):
                            wins += 1
                        else:
                            losses += 1
                        total_pnl += trade.get('pnl', 0)
                except:
                    continue
        
        return {
            'open': open_count,
            'closed': closed_count,
            'wins': wins,
            'losses': losses,
            'win_rate': wins / closed_count if closed_count > 0 else 0,
            'pnl': total_pnl
        }


def settle_all_strategies(btc_price: float):
    """
    Settle trades for all strategies.
    
    Args:
        btc_price: Current BTC price for settlement
    """
    logger = StructuredLogger(__name__)
    
    strategies = [
        ("Strategy 1 (Hybrid)", "data/strategy1_hybrid"),
        ("Strategy 2 (Momentum)", "data/strategy2_momentum"),
    ]
    
    for name, data_dir in strategies:
        settler = TradeSettler(data_dir, lambda: btc_price)
        settled = settler.check_and_settle()
        
        if settled:
            stats = settler.get_stats()
            logger.info(f"{name}: Settled {len(settled)} trades | "
                       f"W/L: {stats['wins']}/{stats['losses']} | "
                       f"P&L: ${stats['pnl']:+.2f}")

