#!/usr/bin/env python3
"""Generate synthetic 1-minute Bitcoin data for testing."""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

def generate_realistic_btc_data(days=7, start_price=92000):
    """Generate realistic 1-minute BTC price data using GBM.
    
    Args:
        days: Number of days to generate
        start_price: Starting BTC price
    """
    print(f"Generating {days} days of synthetic 1-minute Bitcoin data...")
    
    # Parameters for realistic BTC movement
    minutes_per_day = 1440
    total_minutes = days * minutes_per_day
    
    # BTC volatility (annual ~80%, convert to per-minute)
    annual_vol = 0.80
    minutes_per_year = 365.25 * 1440
    per_minute_vol = annual_vol / np.sqrt(minutes_per_year)
    
    # Drift (slight positive bias)
    annual_drift = 0.20
    per_minute_drift = annual_drift / minutes_per_year
    
    # Generate timestamps
    start_time = datetime.now() - timedelta(days=days)
    timestamps = [start_time + timedelta(minutes=i) for i in range(total_minutes)]
    timestamps_unix = [ts.timestamp() for ts in timestamps]
    
    # Generate price path using Geometric Brownian Motion
    np.random.seed(42)  # For reproducibility
    
    prices = [start_price]
    current_price = start_price
    
    for i in range(1, total_minutes):
        # Random return
        random_return = np.random.normal(per_minute_drift, per_minute_vol)
        
        # Apply return
        current_price = current_price * np.exp(random_return)
        
        # Add some mean reversion to keep it realistic
        if current_price > start_price * 1.15:
            current_price *= 0.999  # Slight pull down
        elif current_price < start_price * 0.85:
            current_price *= 1.001  # Slight pull up
        
        prices.append(current_price)
    
    # Create DataFrame
    df = pd.DataFrame({
        'timestamp': timestamps_unix,
        'price': prices
    })
    
    # Save
    output_file = 'data/btc_1min.csv'
    df.to_csv(output_file, index=False)
    
    print(f"\n✓ Generated {len(df):,} 1-minute price points")
    print(f"✓ Date range: {pd.to_datetime(df['timestamp'].min(), unit='s')} to {pd.to_datetime(df['timestamp'].max(), unit='s')}")
    print(f"✓ Price range: ${df['price'].min():,.2f} - ${df['price'].max():,.2f}")
    print(f"✓ Start price: ${df['price'].iloc[0]:,.2f}")
    print(f"✓ End price: ${df['price'].iloc[-1]:,.2f}")
    print(f"✓ Total return: {(df['price'].iloc[-1] / df['price'].iloc[0] - 1) * 100:+.2f}%")
    print(f"✓ Saved to: {output_file}")
    
    return True


if __name__ == "__main__":
    import os
    os.makedirs('data', exist_ok=True)
    
    success = generate_realistic_btc_data(days=7, start_price=92000)
    
    if success:
        print("\n" + "="*60)
        print("✅ Synthetic Bitcoin data ready for testing!")
        print("="*60)
        print("\nThis data simulates realistic BTC price movements.")
        print("You can now run the backtest demo:")
        print("  python run_backtest_demo.py")

