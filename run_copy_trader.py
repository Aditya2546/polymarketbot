#!/usr/bin/env python3
"""
Copy Trading System

Tracks a Polymarket wallet and mirrors their trades with a virtual balance.
Specifically tracking: gabagool22 (0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d)
"""

import asyncio
import sys
import json
import signal
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import aiohttp

sys.path.insert(0, str(Path(__file__).parent))

from src.logger import setup_logging, StructuredLogger
from src.tracking.polymarket_tracker import PolymarketWalletTracker, PolymarketTrade, PolymarketPosition


@dataclass
class CopyTrade:
    """A copy trade executed."""
    timestamp: str
    original_trade: dict
    trader: str
    side: str
    outcome: str
    market_title: str
    market_id: str
    original_shares: float
    original_value: float
    copy_size: float  # Our position size
    copy_price: float
    status: str  # open, closed
    pnl: Optional[float] = None
    close_timestamp: Optional[str] = None


class CopyTradingVirtualWallet:
    """Virtual wallet for copy trading."""
    
    def __init__(self, initial_balance: float = 200.0, data_dir: str = "data/copy_trading"):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.peak_balance = initial_balance
        
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.trades_file = self.data_dir / "copy_trades.jsonl"
        self.positions_file = self.data_dir / "positions.json"
        self.performance_file = self.data_dir / "performance.json"
        self.followed_file = self.data_dir / "followed_trades.jsonl"
        
        self.open_positions: Dict[str, CopyTrade] = {}
        self.closed_trades: List[CopyTrade] = []
        
        self._load_data()
    
    def _load_data(self):
        """Load existing data from disk."""
        # Load performance
        if self.performance_file.exists():
            with open(self.performance_file, 'r') as f:
                perf = json.load(f)
                self.balance = perf.get('balance', self.initial_balance)
                self.peak_balance = perf.get('peak_balance', self.initial_balance)
        
        # Load closed trades
        if self.trades_file.exists():
            with open(self.trades_file, 'r') as f:
                for line in f:
                    trade_dict = json.loads(line)
                    if trade_dict.get('status') == 'closed':
                        self.closed_trades.append(CopyTrade(**trade_dict))
    
    def _save_performance(self):
        """Save performance to disk."""
        perf = {
            'balance': self.balance,
            'initial_balance': self.initial_balance,
            'peak_balance': self.peak_balance,
            'open_positions': len(self.open_positions),
            'closed_trades': len(self.closed_trades),
            'last_update': datetime.now().isoformat()
        }
        
        with open(self.performance_file, 'w') as f:
            json.dump(perf, f, indent=2)
    
    def _save_trade(self, trade: CopyTrade):
        """Save a trade to disk."""
        with open(self.trades_file, 'a') as f:
            f.write(json.dumps(asdict(trade)) + '\n')
    
    def _log_followed_trade(self, original_trade: PolymarketTrade, trader: str):
        """Log a trade we're following."""
        with open(self.followed_file, 'a') as f:
            entry = {
                'timestamp': datetime.now().isoformat(),
                'trader': trader,
                'trade': asdict(original_trade)
            }
            f.write(json.dumps(entry) + '\n')
    
    def copy_trade(self, original_trade: PolymarketTrade, trader: str, max_size: float = 15.0) -> Optional[CopyTrade]:
        """
        Copy a trade from the followed wallet.
        
        Args:
            original_trade: The trade to copy
            trader: Name/address of trader
            max_size: Maximum position size
        
        Returns:
            CopyTrade if executed, None if skipped
        """
        # Log the followed trade regardless
        self._log_followed_trade(original_trade, trader)
        
        # Only copy BUY trades (opening positions)
        if original_trade.side != "BUY":
            return None
        
        # Calculate position size
        # Scale based on our balance vs typical Polymarket sizing
        # Assume original trader has ~$10k, we have $200 = 2% ratio
        scale_factor = 0.02
        
        copy_size = original_trade.value * scale_factor
        copy_size = min(copy_size, max_size, self.balance * 0.1)  # Max 10% of balance
        copy_size = max(copy_size, 2.0)  # Min $2
        
        if copy_size > self.balance:
            return None  # Can't afford
        
        # Create copy trade
        copy = CopyTrade(
            timestamp=datetime.now().isoformat(),
            original_trade=asdict(original_trade),
            trader=trader,
            side=original_trade.side,
            outcome=original_trade.outcome,
            market_title=original_trade.market_title,
            market_id=original_trade.market_id,
            original_shares=original_trade.shares,
            original_value=original_trade.value,
            copy_size=copy_size,
            copy_price=original_trade.price,
            status="open"
        )
        
        # Deduct from balance
        self.balance -= copy_size
        
        # Store position
        key = f"{original_trade.market_id}_{original_trade.outcome}"
        self.open_positions[key] = copy
        
        # Save
        self._save_trade(copy)
        self._save_performance()
        
        return copy
    
    def close_position(self, market_id: str, outcome: str, exit_price: float) -> Optional[CopyTrade]:
        """Close a position."""
        key = f"{market_id}_{outcome}"
        
        if key not in self.open_positions:
            return None
        
        trade = self.open_positions[key]
        
        # Calculate P&L
        # Shares bought = size / entry_price
        shares = trade.copy_size / trade.copy_price
        exit_value = shares * exit_price
        pnl = exit_value - trade.copy_size
        
        # Update trade
        trade.status = "closed"
        trade.pnl = pnl
        trade.close_timestamp = datetime.now().isoformat()
        
        # Update balance
        self.balance += exit_value
        
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        
        # Move to closed
        self.closed_trades.append(trade)
        del self.open_positions[key]
        
        # Save
        self._save_trade(trade)
        self._save_performance()
        
        return trade
    
    def get_stats(self) -> Dict:
        """Get performance statistics."""
        if not self.closed_trades:
            total_pnl = 0
            win_rate = 0
            wins = 0
            losses = 0
        else:
            wins = sum(1 for t in self.closed_trades if t.pnl and t.pnl > 0)
            losses = len(self.closed_trades) - wins
            total_pnl = sum(t.pnl for t in self.closed_trades if t.pnl)
            win_rate = wins / len(self.closed_trades)
        
        return {
            'balance': self.balance,
            'initial': self.initial_balance,
            'total_pnl': total_pnl,
            'roi': (self.balance - self.initial_balance) / self.initial_balance,
            'peak_balance': self.peak_balance,
            'drawdown': (self.peak_balance - self.balance) / self.peak_balance if self.peak_balance > 0 else 0,
            'total_trades': len(self.closed_trades),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'open_positions': len(self.open_positions)
        }


class CopyTradingSystem:
    """Main copy trading system."""
    
    # Target wallet
    TARGET_WALLET = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
    TARGET_USERNAME = "gabagool22"
    
    def __init__(self):
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        
        # Wallet tracker
        self.tracker = PolymarketWalletTracker(
            wallet_address=self.TARGET_WALLET,
            username=self.TARGET_USERNAME
        )
        
        # Virtual wallet
        self.wallet = CopyTradingVirtualWallet(initial_balance=200.0)
        
        self.running = False
        self.poll_interval = 30  # Check every 30 seconds
    
    async def start(self):
        """Start the copy trading system."""
        self.running = True
        
        self.logger.info("=" * 80)
        self.logger.info("🎯 COPY TRADING SYSTEM")
        self.logger.info("=" * 80)
        self.logger.info(f"Following: @{self.TARGET_USERNAME}")
        self.logger.info(f"Wallet: {self.TARGET_WALLET[:10]}...{self.TARGET_WALLET[-6:]}")
        self.logger.info(f"Starting Balance: ${self.wallet.balance:.2f}")
        self.logger.info("=" * 80)
        
        # Start tracker
        await self.tracker.start()
        
        # Register callback for new trades
        self.tracker.on_new_trade(self.on_trade_detected)
        
        # Initial fetch
        self.logger.info("Fetching initial positions...")
        positions = await self.tracker.fetch_positions()
        trades = await self.tracker.fetch_trade_history(limit=20)
        
        self.logger.info(f"Found {len(positions)} current positions")
        self.logger.info(f"Found {len(trades)} recent trades")
        
        if positions:
            self.logger.info("")
            self.logger.info("📊 CURRENT POSITIONS:")
            self.logger.info("-" * 80)
            for pos in positions[:10]:  # Show top 10
                self.logger.info(f"  • {pos.outcome}: {pos.market_title[:50]}...")
                self.logger.info(f"    Shares: {pos.shares:.2f} @ ${pos.avg_price:.3f} | Current: ${pos.current_price:.3f}")
        
        if trades:
            self.logger.info("")
            self.logger.info("📜 RECENT TRADES:")
            self.logger.info("-" * 80)
            for trade in trades[:5]:  # Show last 5
                self.logger.info(f"  • {trade.side} {trade.outcome}: {trade.market_title[:40]}...")
                self.logger.info(f"    {trade.shares:.2f} shares @ ${trade.price:.3f}")
        
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("✅ COPY TRADING ACTIVE - Monitoring for new trades...")
        self.logger.info("=" * 80)
        self.logger.info("")
        
        # Main loop
        await self.main_loop()
    
    async def stop(self):
        """Stop the system."""
        self.running = False
        self.logger.info("Stopping copy trading system...")
        
        await self.tracker.stop()
        
        # Print summary
        self.print_summary()
        
        self.logger.info("System stopped.")
    
    async def main_loop(self):
        """Main monitoring loop."""
        iteration = 0
        
        while self.running:
            iteration += 1
            
            try:
                # Check for new trades
                new_trades = await self.tracker.check_for_new_trades()
                
                if new_trades:
                    for trade in new_trades:
                        self.logger.info("")
                        self.logger.info("🆕 " + "=" * 76)
                        self.logger.info(f"   NEW TRADE DETECTED from @{self.TARGET_USERNAME}")
                        self.logger.info("=" * 80)
                        self.logger.info(f"   Action:   {trade.side} {trade.outcome}")
                        self.logger.info(f"   Market:   {trade.market_title[:60]}")
                        self.logger.info(f"   Shares:   {trade.shares:.2f}")
                        self.logger.info(f"   Price:    ${trade.price:.3f}")
                        self.logger.info(f"   Value:    ${trade.value:.2f}")
                        self.logger.info("=" * 80)
                
                # Print status every 2 minutes
                if iteration % 4 == 0:
                    stats = self.wallet.get_stats()
                    portfolio = self.tracker.get_portfolio_summary()
                    
                    self.logger.info("")
                    self.logger.info("─" * 80)
                    self.logger.info(f"👤 @{self.TARGET_USERNAME}: {portfolio['total_positions']} positions | "
                                    f"Value: ${portfolio['total_value']:.2f} | "
                                    f"P&L: ${portfolio['total_pnl']:.2f}")
                    self.logger.info(f"💰 Copy Wallet: ${stats['balance']:.2f} | "
                                    f"P&L: ${stats['total_pnl']:+.2f} ({stats['roi']:+.1%}) | "
                                    f"Open: {stats['open_positions']} | "
                                    f"Trades: {stats['total_trades']}")
                    self.logger.info("─" * 80)
                    self.logger.info("")
                
                await asyncio.sleep(self.poll_interval)
            
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}", exc_info=True)
                await asyncio.sleep(60)
    
    async def on_trade_detected(self, trade: PolymarketTrade):
        """Handle a newly detected trade."""
        # Copy the trade
        copy = self.wallet.copy_trade(trade, self.TARGET_USERNAME)
        
        if copy:
            self.logger.info("")
            self.logger.info("📋 " + "=" * 76)
            self.logger.info("   TRADE COPIED!")
            self.logger.info("=" * 80)
            self.logger.info(f"   Original: {trade.shares:.2f} shares @ ${trade.price:.3f} = ${trade.value:.2f}")
            self.logger.info(f"   Our Copy: ${copy.copy_size:.2f} @ ${copy.copy_price:.3f}")
            self.logger.info(f"   Market:   {copy.market_title[:60]}")
            self.logger.info(f"   Balance:  ${self.wallet.balance:.2f}")
            self.logger.info("=" * 80)
            self.logger.info("")
    
    def print_summary(self):
        """Print performance summary."""
        stats = self.wallet.get_stats()
        
        print()
        print("=" * 80)
        print(f"📊 COPY TRADING SUMMARY - @{self.TARGET_USERNAME}")
        print("=" * 80)
        print()
        print(f"Starting Balance:   ${stats['initial']:.2f}")
        print(f"Current Balance:    ${stats['balance']:.2f}")
        print(f"Total P&L:          ${stats['total_pnl']:+.2f}")
        print(f"ROI:                {stats['roi']:+.2%}")
        print(f"Peak Balance:       ${stats['peak_balance']:.2f}")
        print(f"Max Drawdown:       {stats['drawdown']:.2%}")
        print()
        print(f"Trades Copied:      {stats['total_trades']}")
        print(f"Wins:               {stats['wins']}")
        print(f"Losses:             {stats['losses']}")
        print(f"Win Rate:           {stats['win_rate']:.1%}")
        print(f"Open Positions:     {stats['open_positions']}")
        print()
        print("=" * 80)
        print()


async def main():
    """Main entry point."""
    system = CopyTradingSystem()
    
    def signal_handler(sig, frame):
        print("\n\nShutting down copy trading...")
        asyncio.create_task(system.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await system.start()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        await system.stop()


if __name__ == "__main__":
    asyncio.run(main())

