#!/usr/bin/env python3
"""
Live simulation test with virtual wallet.

This simulates real trading with the prediction engine, tracking:
- Virtual wallet balance
- Win rate and accuracy
- Profit/loss over time
- Prediction calibration
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime
import sys
from pathlib import Path
from collections import deque

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.data.brti_feed import BRTIFeed, PriceTick
from src.models.settlement_engine import SettlementEngine  
from src.models.probability_model import ProbabilityModel
from src.strategy.risk_manager import RiskManager
from src.logger import setup_logging, StructuredLogger

logger = StructuredLogger(__name__)


class VirtualWallet:
    """Virtual wallet for tracking trades and P&L."""
    
    def __init__(self, initial_balance=200.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.peak_balance = initial_balance
        self.trades = []
        self.open_positions = []
    
    def open_position(self, market_id, side, size, entry_price, p_true, edge):
        """Open a new position."""
        if size > self.balance:
            return None  # Can't afford
        
        position = {
            'market_id': market_id,
            'side': side,
            'size': size,
            'entry_price': entry_price,
            'p_true': p_true,
            'edge': edge,
            'open_time': datetime.now(),
            'status': 'open'
        }
        
        self.open_positions.append(position)
        # Deduct from balance (margin)
        self.balance -= size
        
        return position
    
    def close_position(self, position, outcome):
        """Close a position with the actual outcome."""
        position['close_time'] = datetime.now()
        position['outcome'] = outcome
        position['won'] = (position['side'] == outcome)
        
        # Calculate P&L
        if position['won']:
            # Win: get back stake + profit
            payout = position['size'] / position['entry_price']
            profit = payout - position['size']
            position['pnl'] = profit
            self.balance += payout
        else:
            # Loss: lose the stake
            position['pnl'] = -position['size']
            # Balance already deducted when opened
        
        position['status'] = 'closed'
        
        # Update peak
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        
        # Move to trades history
        self.trades.append(position)
        self.open_positions.remove(position)
        
        return position
    
    def get_stats(self):
        """Get wallet statistics."""
        if not self.trades:
            return {
                'balance': self.balance,
                'initial': self.initial_balance,
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'roi': 0,
                'drawdown': 0,
                'peak_balance': self.peak_balance
            }
        
        wins = sum(1 for t in self.trades if t['won'])
        total_pnl = sum(t['pnl'] for t in self.trades)
        roi = (self.balance - self.initial_balance) / self.initial_balance
        drawdown = (self.peak_balance - self.balance) / self.peak_balance if self.peak_balance > 0 else 0
        
        return {
            'balance': self.balance,
            'initial': self.initial_balance,
            'total_trades': len(self.trades),
            'wins': wins,
            'losses': len(self.trades) - wins,
            'win_rate': wins / len(self.trades),
            'total_pnl': total_pnl,
            'roi': roi,
            'drawdown': drawdown,
            'peak_balance': self.peak_balance
        }


async def run_live_simulation():
    """Run live simulation with virtual wallet."""
    
    print("=" * 80)
    print("LIVE SIMULATION - VIRTUAL WALLET TEST")
    print("=" * 80)
    print()
    print("This test simulates real trading with a $200 virtual wallet.")
    print("We'll use the prediction engine on historical data and track results.")
    print()
    
    # Setup logging
    setup_logging(level="WARNING", log_format="text", console_enabled=False)
    
    # Initialize virtual wallet
    wallet = VirtualWallet(initial_balance=200.0)
    print(f"💰 Virtual Wallet: ${wallet.balance:.2f}")
    print()
    
    # Load data
    print("📊 Loading Bitcoin price data...")
    try:
        df = pd.read_csv('data/btc_1min.csv')
        print(f"   ✓ Loaded {len(df):,} 1-minute data points")
        print(f"   ✓ Price range: ${df['price'].min():,.2f} - ${df['price'].max():,.2f}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        print("   Run: python generate_test_data.py")
        return
    print()
    
    # Initialize components
    print("🔧 Initializing prediction engine...")
    
    brti_feed = BRTIFeed(
        use_cf_benchmarks=False,
        fallback_exchanges=["coinbase"],
        update_interval=1.0,
        buffer_size=300
    )
    
    settlement_engine = SettlementEngine(
        brti_feed=brti_feed,
        convention="A",
        log_both=False
    )
    
    prob_model = ProbabilityModel(
        brti_feed=brti_feed,
        settlement_engine=settlement_engine,
        num_simulations=5000,  # Reduced for speed
        volatility_window=180,
        random_seed=42
    )
    
    print("   ✓ Components ready")
    print()
    
    # Simulation parameters
    interval_minutes = 15
    min_edge_threshold = 0.03  # 3% minimum edge
    max_position_size = 8.0    # $8 max per trade
    
    # Track results
    predictions = []
    
    print("🎮 Starting simulation...")
    print("=" * 80)
    print()
    
    # Simulate 15-minute intervals
    num_intervals = min(100, (len(df) - 100) // interval_minutes)
    
    for interval_num in range(num_intervals):
        # Get data window
        start_idx = interval_num * interval_minutes
        warmup_start = max(0, start_idx - 90)  # 90 minutes of warmup
        interval_end = start_idx + interval_minutes
        
        if interval_end >= len(df):
            break
        
        # Clear and populate buffer
        brti_feed.price_buffer.clear()
        
        warmup_data = df.iloc[warmup_start:start_idx]
        interval_data = df.iloc[start_idx:interval_end]
        
        # Add warmup data
        for _, row in warmup_data.iterrows():
            tick = PriceTick(
                timestamp=row['timestamp'],
                price=row['price'],
                source="simulation"
            )
            brti_feed.price_buffer.append(tick)
        
        # Baseline
        baseline = interval_data.iloc[0]['price']
        interval_start_time = interval_data.iloc[0]['timestamp']
        
        # Add interval data point by point (simulate real-time)
        for idx, row in interval_data.iterrows():
            tick = PriceTick(
                timestamp=row['timestamp'],
                price=row['price'],
                source="simulation"
            )
            brti_feed.price_buffer.append(tick)
        
        # Final price (settlement)
        final_price = interval_data.iloc[-1]['price']
        actual_outcome = "YES" if final_price > baseline else "NO"
        
        # Need at least 60 data points
        if len(brti_feed.price_buffer) < 60:
            continue
        
        # Get current state (as if we're X minutes into the interval)
        # Let's make prediction at 10 minutes in (5 minutes before settlement)
        prediction_point = start_idx + 10
        if prediction_point >= len(df):
            continue
        
        # Populate buffer up to prediction point
        brti_feed.price_buffer.clear()
        for _, row in df.iloc[max(0, prediction_point - 90):prediction_point].iterrows():
            tick = PriceTick(
                timestamp=row['timestamp'],
                price=row['price'],
                source="simulation"
            )
            brti_feed.price_buffer.append(tick)
        
        if len(brti_feed.price_buffer) < 60:
            continue
        
        # Make prediction
        settle_time = interval_data.iloc[-1]['timestamp']
        
        try:
            p_yes, p_no = prob_model.compute_probability(
                baseline=baseline,
                settle_timestamp=settle_time
            )
            
            if p_yes is None:
                continue
            
            # Determine prediction and confidence
            predicted_outcome = "YES" if p_yes > 0.5 else "NO"
            confidence = abs(p_yes - 0.5)
            
            # Simulate market price (assume market is at 50-50 initially)
            # In reality, this would come from Kalshi orderbook
            market_price_yes = 0.50 + np.random.normal(0, 0.05)  # Some noise
            market_price_yes = np.clip(market_price_yes, 0.01, 0.99)
            
            # Calculate edge
            edge_yes = p_yes - market_price_yes - 0.015  # After fees/costs
            edge_no = p_no - (1 - market_price_yes) - 0.015
            
            best_edge = max(edge_yes, edge_no)
            best_side = "YES" if edge_yes > edge_no else "NO"
            
            # Trading decision
            should_trade = best_edge >= min_edge_threshold and confidence > 0.05
            
            trade_executed = None
            
            if should_trade and wallet.balance >= max_position_size:
                # Calculate position size based on edge
                size = min(max_position_size, wallet.balance * 0.04)  # 4% of bankroll
                size = size * min(1.0, best_edge / 0.05)  # Scale with edge
                
                # Execute trade
                entry_price = market_price_yes if best_side == "YES" else (1 - market_price_yes)
                
                position = wallet.open_position(
                    market_id=f"INTERVAL-{interval_num}",
                    side=best_side,
                    size=size,
                    entry_price=entry_price,
                    p_true=p_yes if best_side == "YES" else p_no,
                    edge=best_edge
                )
                
                if position:
                    trade_executed = position
                    
                    # Close position immediately with actual outcome
                    wallet.close_position(position, actual_outcome)
            
            # Record prediction
            predictions.append({
                'interval': interval_num,
                'baseline': baseline,
                'final_price': final_price,
                'actual_outcome': actual_outcome,
                'p_yes': p_yes,
                'p_no': p_no,
                'predicted_outcome': predicted_outcome,
                'confidence': confidence,
                'correct': predicted_outcome == actual_outcome,
                'edge': best_edge,
                'traded': trade_executed is not None,
                'pnl': trade_executed['pnl'] if trade_executed else 0
            })
            
            # Print progress every 10 intervals
            if (interval_num + 1) % 10 == 0:
                stats = wallet.get_stats()
                print(f"Interval {interval_num + 1}/{num_intervals} | "
                      f"Balance: ${stats['balance']:.2f} | "
                      f"Trades: {stats['total_trades']} | "
                      f"Win Rate: {stats['win_rate']:.1%} | "
                      f"P&L: ${stats['total_pnl']:+.2f}")
            
        except Exception as e:
            logger.debug(f"Error in interval {interval_num}: {e}")
            continue
    
    print()
    print("=" * 80)
    print("📊 SIMULATION COMPLETE - RESULTS")
    print("=" * 80)
    print()
    
    # Final wallet stats
    stats = wallet.get_stats()
    
    print("💰 VIRTUAL WALLET PERFORMANCE")
    print("-" * 80)
    print(f"Starting Balance:    ${stats['initial']:.2f}")
    print(f"Final Balance:       ${stats['balance']:.2f}")
    print(f"Peak Balance:        ${stats['peak_balance']:.2f}")
    print(f"Total P&L:           ${stats['total_pnl']:+.2f}")
    print(f"ROI:                 {stats['roi']:+.2%}")
    print(f"Max Drawdown:        {stats['drawdown']:.2%}")
    print()
    
    print("📈 TRADING STATISTICS")
    print("-" * 80)
    print(f"Total Trades:        {stats['total_trades']}")
    print(f"Wins:                {stats['wins']}")
    print(f"Losses:              {stats['losses']}")
    print(f"Win Rate:            {stats['win_rate']:.2%}")
    
    if wallet.trades:
        avg_win = np.mean([t['pnl'] for t in wallet.trades if t['won']])
        avg_loss = np.mean([t['pnl'] for t in wallet.trades if not t['won']])
        avg_trade = np.mean([t['pnl'] for t in wallet.trades])
        
        print(f"Average Win:         ${avg_win:+.2f}")
        print(f"Average Loss:        ${avg_loss:+.2f}")
        print(f"Average Trade:       ${avg_trade:+.2f}")
    print()
    
    # Prediction accuracy
    if predictions:
        pred_df = pd.DataFrame(predictions)
        
        print("🎯 PREDICTION ACCURACY")
        print("-" * 80)
        print(f"Total Predictions:   {len(pred_df)}")
        print(f"Accuracy:            {pred_df['correct'].mean():.2%}")
        print(f"Avg Confidence:      {pred_df['confidence'].mean():.4f}")
        
        # Brier score
        brier_scores = []
        for _, row in pred_df.iterrows():
            actual = 1.0 if row['actual_outcome'] == "YES" else 0.0
            brier_scores.append((row['p_yes'] - actual) ** 2)
        
        brier_score = np.mean(brier_scores)
        print(f"Brier Score:         {brier_score:.4f} ({'GOOD' if brier_score < 0.20 else 'FAIR' if brier_score < 0.25 else 'POOR'})")
        print()
        
        # Breakdown by confidence
        print("📊 ACCURACY BY CONFIDENCE LEVEL")
        print("-" * 80)
        
        high_conf = pred_df[pred_df['confidence'] > 0.15]
        med_conf = pred_df[(pred_df['confidence'] > 0.05) & (pred_df['confidence'] <= 0.15)]
        low_conf = pred_df[pred_df['confidence'] <= 0.05]
        
        if len(high_conf) > 0:
            print(f"High (>0.15):        {len(high_conf):3d} predictions, {high_conf['correct'].mean():.1%} accurate")
        if len(med_conf) > 0:
            print(f"Medium (0.05-0.15):  {len(med_conf):3d} predictions, {med_conf['correct'].mean():.1%} accurate")
        if len(low_conf) > 0:
            print(f"Low (<0.05):         {len(low_conf):3d} predictions, {low_conf['correct'].mean():.1%} accurate")
        print()
        
        # Trade analysis
        traded = pred_df[pred_df['traded']]
        if len(traded) > 0:
            print("💼 TRADES EXECUTED")
            print("-" * 80)
            print(f"Signals Generated:   {len(pred_df)}")
            print(f"Trades Executed:     {len(traded)} ({len(traded)/len(pred_df):.1%} of opportunities)")
            print(f"Average Edge:        {traded['edge'].mean():.2%}")
            print(f"Trade Win Rate:      {traded['correct'].mean():.2%}")
            print()
    
    # Save detailed results
    if predictions:
        results_df = pd.DataFrame(predictions)
        results_df.to_csv('logs/virtual_wallet_test.csv', index=False)
        print(f"✓ Detailed results saved to: logs/virtual_wallet_test.csv")
    
    if wallet.trades:
        trades_df = pd.DataFrame(wallet.trades)
        trades_df.to_csv('logs/virtual_wallet_trades.csv', index=False)
        print(f"✓ Trade history saved to: logs/virtual_wallet_trades.csv")
    
    print()
    print("=" * 80)
    
    # Final verdict
    print()
    print("🎯 VERDICT")
    print("=" * 80)
    
    if stats['total_trades'] == 0:
        print("⚠️  No trades executed - edge threshold too high or insufficient opportunities")
    elif stats['roi'] > 0.10:
        print(f"🎉 EXCELLENT! +{stats['roi']:.1%} return - System is profitable!")
    elif stats['roi'] > 0:
        print(f"✅ PROFITABLE! +{stats['roi']:.1%} return - System has edge")
    elif stats['roi'] > -0.05:
        print(f"📊 BREAK-EVEN: {stats['roi']:+.1%} return - System needs tuning")
    else:
        print(f"❌ UNPROFITABLE: {stats['roi']:+.1%} return - System needs improvement")
    
    if predictions:
        accuracy = pred_df['correct'].mean()
        if accuracy > 0.60:
            print(f"🎯 STRONG PREDICTIONS: {accuracy:.1%} accuracy (well above 50%)")
        elif accuracy > 0.52:
            print(f"📈 GOOD PREDICTIONS: {accuracy:.1%} accuracy (above break-even)")
        elif accuracy > 0.48:
            print(f"📊 FAIR PREDICTIONS: {accuracy:.1%} accuracy (near 50-50)")
        else:
            print(f"⚠️  WEAK PREDICTIONS: {accuracy:.1%} accuracy (needs improvement)")
    
    print()


if __name__ == "__main__":
    asyncio.run(run_live_simulation())

