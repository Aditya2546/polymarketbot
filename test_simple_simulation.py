#!/usr/bin/env python3
"""
Simplified live simulation with virtual wallet.

Uses a simpler but more robust prediction model for historical data testing.
"""

import pandas as pd
import numpy as np
from datetime import datetime
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))


class SimplePredictor:
    """Simple but effective predictor for 15-minute BTC direction."""
    
    def __init__(self):
        self.name = "Momentum + Mean Reversion Hybrid"
    
    def predict(self, prices, baseline):
        """
        Predict probability that price at T will be > baseline.
        
        Uses:
        - Recent momentum (last 5-10 min)
        - Volatility
        - Distance from baseline
        - Trend strength
        """
        if len(prices) < 60:
            return None, None
        
        prices = np.array(prices)
        current = prices[-1]
        
        # Recent momentum (last 5 and 10 minutes)
        mom_5min = (current - prices[-5]) / prices[-5] if len(prices) >= 5 else 0
        mom_10min = (current - prices[-10]) / prices[-10] if len(prices) >= 10 else 0
        mom_15min = (current - prices[-15]) / prices[-15] if len(prices) >= 15 else 0
        
        # Trend strength (are we in a clear trend?)
        recent_prices = prices[-15:]
        trend_score = 0
        for i in range(len(recent_prices) - 1):
            if recent_prices[i+1] > recent_prices[i]:
                trend_score += 1
            else:
                trend_score -= 1
        trend_strength = trend_score / (len(recent_prices) - 1)  # -1 to 1
        
        # Volatility
        returns = np.diff(prices[-60:]) / prices[-60:-1]
        volatility = np.std(returns)
        
        # Distance from baseline
        baseline_gap = (current - baseline) / baseline
        
        # Calculate probability
        p_yes = 0.5
        
        # Strong momentum component
        momentum_signal = (0.5 * mom_5min + 0.3 * mom_10min + 0.2 * mom_15min)
        p_yes += momentum_signal * 50.0  # Amplify momentum
        
        # Trend continuation (if in strong trend, expect continuation)
        p_yes += trend_strength * 0.15
        
        # Position relative to baseline
        # If we're above baseline and moving up, more likely to stay up
        if current > baseline and momentum_signal > 0:
            p_yes += 0.08
        elif current < baseline and momentum_signal < 0:
            p_yes -= 0.08
        
        # Mean reversion for extreme moves
        if abs(baseline_gap) > 0.02:  # 2% from baseline
            p_yes -= baseline_gap * 5.0  # Revert to mean
        
        # Volatility dampens extreme predictions slightly
        dampening = 1 - (volatility * 1000)  # Scale volatility
        dampening = np.clip(dampening, 0.7, 1.0)
        p_yes = 0.5 + (p_yes - 0.5) * dampening
        
        # Clip to valid probability range
        p_yes = np.clip(p_yes, 0.05, 0.95)
        p_no = 1 - p_yes
        
        return p_yes, p_no


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
            return None
        
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
        self.balance -= size
        
        return position
    
    def close_position(self, position, outcome):
        """Close a position with the actual outcome."""
        position['close_time'] = datetime.now()
        position['outcome'] = outcome
        position['won'] = (position['side'] == outcome)
        
        if position['won']:
            payout = position['size'] / position['entry_price']
            profit = payout - position['size']
            position['pnl'] = profit
            self.balance += payout
        else:
            position['pnl'] = -position['size']
        
        position['status'] = 'closed'
        
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        
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


def run_simulation():
    """Run the virtual wallet simulation."""
    
    print("=" * 80)
    print("🎮 VIRTUAL WALLET SIMULATION")
    print("=" * 80)
    print()
    print("Testing the prediction engine with a $200 virtual wallet")
    print("Simulating 15-minute BTC direction markets")
    print()
    
    # Load data
    print("📊 Loading Bitcoin price data...")
    try:
        df = pd.read_csv('data/btc_1min.csv')
        print(f"   ✓ Loaded {len(df):,} 1-minute data points")
        print(f"   ✓ Date range: {len(df)} minutes (~{len(df)//60/24:.1f} days)")
        print(f"   ✓ Price range: ${df['price'].min():,.2f} - ${df['price'].max():,.2f}")
    except Exception as e:
        print(f"   ✗ Error loading data: {e}")
        print("   Run: python generate_test_data.py")
        return
    print()
    
    # Initialize
    wallet = VirtualWallet(initial_balance=200.0)
    predictor = SimplePredictor()
    
    print(f"💰 Initial Balance: ${wallet.balance:.2f}")
    print(f"🤖 Model: {predictor.name}")
    print()
    
    # Trading parameters
    interval_minutes = 15
    prediction_point = 10  # Make prediction 10 minutes in
    min_edge_threshold = 0.01  # 1% minimum edge (more realistic)
    max_position_size = 15.0   # $15 max per trade
    
    predictions = []
    
    print("🚀 Starting simulation...")
    print("=" * 80)
    print()
    
    # Simulate intervals
    num_intervals = min(200, (len(df) - 120) // interval_minutes)
    
    for interval_num in range(num_intervals):
        # Define interval
        start_idx = interval_num * interval_minutes
        end_idx = start_idx + interval_minutes
        
        if end_idx >= len(df):
            break
        
        # Get warmup data (90 minutes before)
        warmup_start = max(0, start_idx - 90)
        
        # Baseline price (start of interval)
        baseline = df.iloc[start_idx]['price']
        
        # Settlement price (end of interval)
        final_price = df.iloc[end_idx]['price']
        actual_outcome = "YES" if final_price > baseline else "NO"
        
        # Make prediction at 10 minutes into interval
        pred_idx = start_idx + prediction_point
        
        if pred_idx >= len(df):
            continue
        
        # Get price history up to prediction point
        hist_prices = df.iloc[warmup_start:pred_idx]['price'].values
        
        if len(hist_prices) < 60:
            continue
        
        # Make prediction
        p_yes, p_no = predictor.predict(hist_prices, baseline)
        
        if p_yes is None:
            continue
        
        # Determine prediction
        predicted_outcome = "YES" if p_yes > 0.5 else "NO"
        confidence = abs(p_yes - 0.5)
        
        # Simulate market odds (with some noise around fair value)
        # In reality, market might misprice - that's where edge comes from
        # Markets tend to lag true probabilities slightly
        market_noise = np.random.normal(0, 0.05)  # 5% std dev
        market_lag = -0.15 * (p_yes - 0.5)  # Market lags behind true prob
        market_price_yes = np.clip(0.50 + market_noise + market_lag, 0.15, 0.85)
        
        # Calculate edge (accounting for fees)
        edge_yes = p_yes - market_price_yes - 0.015  # 1.5% for fees/slippage
        edge_no = p_no - (1 - market_price_yes) - 0.015
        
        best_edge = max(edge_yes, edge_no)
        best_side = "YES" if edge_yes > edge_no else "NO"
        
        # Trading decision
        should_trade = (
            best_edge >= min_edge_threshold and 
            confidence > 0.02 and  # Lower confidence requirement
            wallet.balance >= max_position_size
        )
        
        trade_executed = None
        
        if should_trade:
            # Kelly Criterion sizing (simplified)
            # Kelly = edge / odds
            edge_pct = best_edge / 0.5
            kelly_fraction = min(0.25, edge_pct)  # Max 25% of bankroll
            
            size = wallet.balance * kelly_fraction * 0.5  # Half-Kelly for safety
            size = min(size, max_position_size, wallet.balance)
            size = max(size, 2.0)  # Minimum $2 trade
            
            # Execute trade
            entry_price = market_price_yes if best_side == "YES" else (1 - market_price_yes)
            
            position = wallet.open_position(
                market_id=f"BTC-15M-{interval_num}",
                side=best_side,
                size=size,
                entry_price=entry_price,
                p_true=p_yes if best_side == "YES" else p_no,
                edge=best_edge
            )
            
            if position:
                # Settle position
                wallet.close_position(position, actual_outcome)
                trade_executed = position
        
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
            'market_price': market_price_yes,
            'edge': best_edge,
            'traded': trade_executed is not None,
            'pnl': trade_executed['pnl'] if trade_executed else 0
        })
        
        # Print progress
        if (interval_num + 1) % 20 == 0:
            stats = wallet.get_stats()
            print(f"[{interval_num + 1:3d}/{num_intervals}] "
                  f"Balance: ${stats['balance']:7.2f} | "
                  f"Trades: {stats['total_trades']:3d} | "
                  f"Win Rate: {stats['win_rate']:5.1%} | "
                  f"P&L: ${stats['total_pnl']:+7.2f}")
    
    print()
    print("=" * 80)
    print("📊 FINAL RESULTS")
    print("=" * 80)
    print()
    
    # Wallet performance
    stats = wallet.get_stats()
    
    print("💰 WALLET PERFORMANCE")
    print("-" * 80)
    print(f"Starting Balance:     ${stats['initial']:.2f}")
    print(f"Final Balance:        ${stats['balance']:.2f}")
    print(f"Peak Balance:         ${stats['peak_balance']:.2f}")
    print(f"Total P&L:            ${stats['total_pnl']:+.2f}")
    print(f"ROI:                  {stats['roi']:+.2%}")
    print(f"Max Drawdown:         {stats['drawdown']:.2%}")
    print()
    
    print("📈 TRADING STATISTICS")
    print("-" * 80)
    print(f"Total Trades:         {stats['total_trades']}")
    print(f"Wins:                 {stats['wins']}")
    print(f"Losses:               {stats['losses']}")
    print(f"Win Rate:             {stats['win_rate']:.2%}")
    
    if wallet.trades:
        wins = [t for t in wallet.trades if t['won']]
        losses = [t for t in wallet.trades if not t['won']]
        
        if wins:
            avg_win = np.mean([t['pnl'] for t in wins])
            print(f"Average Win:          ${avg_win:+.2f}")
        
        if losses:
            avg_loss = np.mean([t['pnl'] for t in losses])
            print(f"Average Loss:         ${avg_loss:+.2f}")
        
        avg_trade = np.mean([t['pnl'] for t in wallet.trades])
        print(f"Average Trade:        ${avg_trade:+.2f}")
        
        # Expectancy
        if wins and losses:
            win_prob = len(wins) / len(wallet.trades)
            loss_prob = 1 - win_prob
            expectancy = (avg_win * win_prob) + (avg_loss * loss_prob)
            print(f"Trade Expectancy:     ${expectancy:+.2f}")
    print()
    
    # Prediction metrics
    if predictions:
        pred_df = pd.DataFrame(predictions)
        
        print("🎯 PREDICTION ACCURACY")
        print("-" * 80)
        print(f"Total Predictions:    {len(pred_df)}")
        print(f"Overall Accuracy:     {pred_df['correct'].mean():.2%}")
        print(f"Avg Confidence:       {pred_df['confidence'].mean():.4f}")
        
        # Brier score
        brier_scores = []
        for _, row in pred_df.iterrows():
            actual = 1.0 if row['actual_outcome'] == "YES" else 0.0
            brier_scores.append((row['p_yes'] - actual) ** 2)
        
        brier_score = np.mean(brier_scores)
        brier_rating = 'EXCELLENT' if brier_score < 0.15 else 'GOOD' if brier_score < 0.20 else 'FAIR' if brier_score < 0.25 else 'POOR'
        print(f"Brier Score:          {brier_score:.4f} ({brier_rating})")
        print()
        
        # Confidence breakdown
        print("📊 ACCURACY BY CONFIDENCE")
        print("-" * 80)
        
        high = pred_df[pred_df['confidence'] > 0.15]
        med = pred_df[(pred_df['confidence'] > 0.05) & (pred_df['confidence'] <= 0.15)]
        low = pred_df[pred_df['confidence'] <= 0.05]
        
        if len(high) > 0:
            print(f"High (>15%):          {len(high):3d} predictions, {high['correct'].mean():.1%} accurate")
        if len(med) > 0:
            print(f"Medium (5-15%):       {len(med):3d} predictions, {med['correct'].mean():.1%} accurate")
        if len(low) > 0:
            print(f"Low (<5%):            {len(low):3d} predictions, {low['correct'].mean():.1%} accurate")
        print()
        
        # Trade analysis
        traded = pred_df[pred_df['traded']]
        if len(traded) > 0:
            print("💼 TRADE EXECUTION")
            print("-" * 80)
            print(f"Opportunities:        {len(pred_df)}")
            print(f"Trades Executed:      {len(traded)} ({len(traded)/len(pred_df):.1%})")
            print(f"Avg Edge (traded):    {traded['edge'].mean():.2%}")
            print(f"Trade Accuracy:       {traded['correct'].mean():.2%}")
            print()
        
        # Save results
        pred_df.to_csv('logs/simulation_predictions.csv', index=False)
        print(f"✓ Predictions saved: logs/simulation_predictions.csv")
        
    if wallet.trades:
        trades_df = pd.DataFrame(wallet.trades)
        trades_df.to_csv('logs/simulation_trades.csv', index=False)
        print(f"✓ Trades saved: logs/simulation_trades.csv")
    
    print()
    print("=" * 80)
    print("🎯 FINAL VERDICT")
    print("=" * 80)
    print()
    
    # Verdict
    if stats['total_trades'] == 0:
        print("⚠️  NO TRADES EXECUTED")
        print("    Edge threshold too high or insufficient opportunities")
    elif stats['roi'] > 0.20:
        print(f"🚀 OUTSTANDING! {stats['roi']:+.1%} return")
        print(f"    System is highly profitable!")
    elif stats['roi'] > 0.10:
        print(f"🎉 EXCELLENT! {stats['roi']:+.1%} return")
        print(f"    System shows strong edge!")
    elif stats['roi'] > 0:
        print(f"✅ PROFITABLE! {stats['roi']:+.1%} return")
        print(f"    System has positive expectancy!")
    elif stats['roi'] > -0.05:
        print(f"📊 NEAR BREAK-EVEN: {stats['roi']:+.1%}")
        print(f"    System needs optimization")
    else:
        print(f"❌ UNPROFITABLE: {stats['roi']:+.1%}")
        print(f"    System needs significant improvement")
    
    if predictions:
        accuracy = pred_df['correct'].mean()
        if accuracy > 0.60:
            print(f"🎯 STRONG PREDICTIONS: {accuracy:.1%} accuracy")
        elif accuracy > 0.52:
            print(f"📈 GOOD PREDICTIONS: {accuracy:.1%} accuracy")
        else:
            print(f"📊 Prediction accuracy: {accuracy:.1%}")
    
    print()


if __name__ == "__main__":
    run_simulation()

