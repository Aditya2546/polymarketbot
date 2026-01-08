#!/usr/bin/env python3
"""Download historical Bitcoin price data for backtesting."""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time

def download_btc_data(days=30):
    """Download BTC price data from public API.
    
    Args:
        days: Number of days of history to download
    """
    print(f"Downloading {days} days of Bitcoin price data...")
    
    # Use CoinGecko public API (no key required)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # CoinGecko market chart endpoint (1-minute granularity for recent data)
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"
    
    params = {
        "vs_currency": "usd",
        "from": int(start_date.timestamp()),
        "to": int(end_date.timestamp())
    }
    
    try:
        print("Fetching from CoinGecko API...")
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            prices = data['prices']
            
            # Convert to DataFrame
            df = pd.DataFrame(prices, columns=['timestamp_ms', 'price'])
            df['timestamp'] = df['timestamp_ms'] / 1000  # Convert to seconds
            df = df[['timestamp', 'price']]
            
            # Save to CSV
            output_file = 'data/btc_historical.csv'
            df.to_csv(output_file, index=False)
            
            print(f"✓ Downloaded {len(df):,} price points")
            print(f"✓ Date range: {pd.to_datetime(df['timestamp'].min(), unit='s')} to {pd.to_datetime(df['timestamp'].max(), unit='s')}")
            print(f"✓ Saved to: {output_file}")
            print(f"✓ Price range: ${df['price'].min():,.2f} - ${df['price'].max():,.2f}")
            
            return True
            
        else:
            print(f"✗ Error: API returned status {response.status_code}")
            print(f"  Response: {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"✗ Error downloading data: {e}")
        return False

if __name__ == "__main__":
    import os
    os.makedirs('data', exist_ok=True)
    
    success = download_btc_data(days=30)
    
    if success:
        print("\n" + "="*60)
        print("✅ Bitcoin data ready for backtesting!")
        print("="*60)
        print("\nYou can now run backtests with:")
        print("  python main.py --mode backtest --start 2024-12-01 --end 2025-01-07")
    else:
        print("\n" + "="*60)
        print("❌ Failed to download data")
        print("="*60)
        print("\nAlternative: Manually download BTC data and save as data/btc_historical.csv")
        print("Required format: CSV with 'timestamp' and 'price' columns")

