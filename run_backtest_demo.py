#!/usr/bin/env python3
"""
Demo backtest script to test the prediction engine.

This simulates 15-minute intervals and tests how well the probability model
predicts outcomes.
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.data.brti_feed import BRTIFeed, PriceTick
from src.models.settlement_engine import SettlementEngine  
from src.models.probability_model import ProbabilityModel
from src.strategy.risk_manager import RiskManager
from src.logger import setup_logging, StructuredLogger

logger = StructuredLogger(__name__)


async def run_backtest_demo():
    """Run a demonstration backtest."""
    
    print("=" * 70)
    print("KALSHI 15-MINUTE BTC DIRECTION ASSISTANT - BACKTEST DEMO")
    print("=" * 70)
    print()
    
    # Setup logging
    setup_logging(level="INFO", log_format="text", console_enabled=True)
    
    # Load historical data
    print("📊 Loading historical Bitcoin data...")
    try:
        # Try to load 1-minute data first
        try:
            df = pd.read_csv('data/btc_1min.csv')
            print(f"   ✓ Loaded 1-minute data: {len(df):,} data points")
        except:
            df = pd.read_csv('data/btc_historical.csv')
            print(f"   ✓ Loaded hourly data: {len(df):,} data points")
        
        print(f"   ✓ Date range: {pd.to_datetime(df['timestamp'].min(), unit='s')} to {pd.to_datetime(df['timestamp'].max(), unit='s')}")
        print(f"   ✓ Price range: ${df['price'].min():,.2f} - ${df['price'].max():,.2f}")
        print()
    except Exception as e:
        print(f"   ✗ Error loading data: {e}")
        print("   Run: python generate_test_data.py")
        return
    
    # Initialize components
    print("🔧 Initializing prediction engine...")
    
    # Create mock BRTI feed with historical data
    brti_feed = BRTIFeed(
        use_cf_benchmarks=False,
        fallback_exchanges=["coinbase"],
        update_interval=1.0,
        buffer_size=300
    )
    
    # Settlement engine
    settlement_engine = SettlementEngine(
        brti_feed=brti_feed,
        convention="A",
        log_both=True
    )
    
    # Probability model
    prob_model = ProbabilityModel(
        brti_feed=brti_feed,
        settlement_engine=settlement_engine,
        num_simulations=5000,  # Reduced for speed
        volatility_window=180,
        random_seed=42
    )
    
    # Risk manager
    risk_manager = RiskManager(
        initial_bankroll_usd=200.0,
        max_risk_per_trade_usd=8.0,
        max_open_exposure_usd=24.0,
        daily_loss_limit_usd=20.0
    )
    
    print("   ✓ Components initialized")
    print()
    
    # Simulate 15-minute intervals
    print("🎲 Simulating 15-minute intervals...")
    print()
    
    results = []
    interval_duration = 15 * 60  # 15 minutes in seconds
    
    # Calculate how many 15-minute intervals we can test
    # Need at least 60 data points (for avg60 calculation) + 15 for the interval
    min_points_needed = 75
    points_per_interval = 15  # 15 minutes of 1-minute data
    
    num_intervals = min(50, (len(df) - 60) // points_per_interval)  # Test up to 50 intervals
    
    for i in range(num_intervals):
        print(f"📍 Interval {i+1}/{num_intervals}")
        print("-" * 70)
        
        # Get data: 60 points before + 15 points for interval
        start_idx = i * points_per_interval
        warmup_start = max(0, start_idx - 60)
        interval_end = start_idx + points_per_interval
        
        if interval_end >= len(df):
            break
        
        # Warmup data (for avg60 calculation)
        warmup_data = df.iloc[warmup_start:start_idx]
        
        # Interval data
        interval_data = df.iloc[start_idx:interval_end]
        
        if len(interval_data) < 2:
            print("   ⚠ Insufficient data for this interval\n")
            continue
        
        # Clear buffer and repopulate with warmup + interval data
        brti_feed.price_buffer.clear()
        
        # Add warmup data
        for _, row in warmup_data.iterrows():
            tick = PriceTick(
                timestamp=row['timestamp'],
                price=row['price'],
                source="historical"
            )
            brti_feed.price_buffer.append(tick)
        
        # Baseline = price at interval start
        baseline = interval_data.iloc[0]['price']
        interval_start_time = interval_data.iloc[0]['timestamp']
        
        # Add interval data point by point
        for _, row in interval_data.iterrows():
            tick = PriceTick(
                timestamp=row['timestamp'],
                price=row['price'],
                source="historical"
            )
            brti_feed.price_buffer.append(tick)
        
        # Actual final price (for settlement)
        final_price = interval_data.iloc[-1]['price']
        actual_outcome = "YES" if final_price > baseline else "NO"
        
        print(f"   Baseline: ${baseline:,.2f}")
        print(f"   Final Price: ${final_price:,.2f}")
        print(f"   Actual Outcome: {actual_outcome}")
        
        # Update settlement engine
        # Use manual avg60 calculation since we have all the data
        if len(brti_feed.price_buffer) >= 60:
            # Get last 60 prices for avg60
            last_60 = list(brti_feed.price_buffer)[-60:]
            avg60 = np.mean([tick.price for tick in last_60])
            print(f"   Avg60: ${avg60:,.2f}")
        else:
            print(f"   ⚠ Only {len(brti_feed.price_buffer)} points (need 60)\n")
            continue
        
        # Compute probability prediction
        # (This would normally be done continuously, we're doing it at the end for demo)
        settle_time = interval_data.iloc[-1]['timestamp']
        
        try:
            p_yes, p_no = prob_model.compute_probability(
                baseline=baseline,
                settle_timestamp=settle_time
            )
            
            if p_yes is None:
                print("   ⚠ Could not compute probability\n")
                continue
            
            predicted_outcome = "YES" if p_yes > 0.5 else "NO"
            confidence = abs(p_yes - 0.5)
            
            print(f"   Predicted P(YES): {p_yes:.4f}")
            print(f"   Predicted P(NO): {p_no:.4f}")
            print(f"   Predicted Outcome: {predicted_outcome}")
            print(f"   Confidence: {confidence:.4f}")
            
            # Check if prediction was correct
            correct = (predicted_outcome == actual_outcome)
            print(f"   Result: {'✓ CORRECT' if correct else '✗ WRONG'}")
            
            # Compute calibration error (Brier score component)
            brier = (p_yes - (1.0 if actual_outcome == "YES" else 0.0)) ** 2
            
            results.append({
                'interval': i + 1,
                'baseline': baseline,
                'final_price': final_price,
                'actual_outcome': actual_outcome,
                'p_yes': p_yes,
                'p_no': p_no,
                'predicted_outcome': predicted_outcome,
                'confidence': confidence,
                'correct': correct,
                'brier': brier
            })
            
        except Exception as e:
            print(f"   ✗ Error in prediction: {e}")
        
        print()
    
    # Compute overall statistics
    if results:
        print("=" * 70)
        print("📊 BACKTEST RESULTS")
        print("=" * 70)
        print()
        
        results_df = pd.DataFrame(results)
        
        accuracy = results_df['correct'].mean()
        avg_confidence = results_df['confidence'].mean()
        brier_score = results_df['brier'].mean()
        
        print(f"Total Intervals: {len(results)}")
        print(f"Accuracy: {accuracy:.1%}")
        print(f"Average Confidence: {avg_confidence:.4f}")
        print(f"Brier Score: {brier_score:.4f} (lower is better, <0.20 is good)")
        print()
        
        # Show prediction distribution
        print("Prediction Distribution:")
        print(f"  YES predictions: {(results_df['predicted_outcome'] == 'YES').sum()}")
        print(f"  NO predictions: {(results_df['predicted_outcome'] == 'NO').sum()}")
        print()
        
        print("Actual Outcome Distribution:")
        print(f"  YES outcomes: {(results_df['actual_outcome'] == 'YES').sum()}")
        print(f"  NO outcomes: {(results_df['actual_outcome'] == 'NO').sum()}")
        print()
        
        # Calibration by confidence bucket
        print("Calibration Analysis:")
        high_conf = results_df[results_df['confidence'] > 0.1]
        if len(high_conf) > 0:
            print(f"  High confidence (>0.1): {len(high_conf)} predictions, {high_conf['correct'].mean():.1%} accurate")
        
        low_conf = results_df[results_df['confidence'] <= 0.1]
        if len(low_conf) > 0:
            print(f"  Low confidence (<=0.1): {len(low_conf)} predictions, {low_conf['correct'].mean():.1%} accurate")
        print()
        
        # Save results
        results_df.to_csv('logs/backtest_demo_results.csv', index=False)
        print(f"✓ Results saved to: logs/backtest_demo_results.csv")
        print()
        
        print("=" * 70)
        print("✅ BACKTEST COMPLETE")
        print("=" * 70)
        print()
        print("Key Insights:")
        print(f"  • Model achieved {accuracy:.1%} accuracy on {len(results)} intervals")
        print(f"  • Brier score of {brier_score:.4f} indicates {'good' if brier_score < 0.20 else 'fair' if brier_score < 0.25 else 'poor'} calibration")
        print(f"  • Average confidence: {avg_confidence:.4f} ({'high' if avg_confidence > 0.2 else 'moderate' if avg_confidence > 0.1 else 'low'})")
        print()
        
        if accuracy > 0.55:
            print("🎉 Model shows predictive power (>55% accuracy)!")
        elif accuracy > 0.50:
            print("📈 Model shows slight edge (>50% accuracy)")
        else:
            print("⚠️  Model needs improvement (<50% accuracy)")
        print()
        
    else:
        print("=" * 70)
        print("⚠️  NO RESULTS")
        print("=" * 70)
        print("Not enough data to run backtest. Try downloading more data.")
        print()


if __name__ == "__main__":
    asyncio.run(run_backtest_demo())

