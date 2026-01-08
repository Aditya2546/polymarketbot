#!/usr/bin/env python3
"""Download 1-minute Bitcoin data for proper backtesting."""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import json

def download_minute_data_binance(days=7):
    """Download 1-minute BTC data from Binance (free, no API key needed).
    
    Args:
        days: Number of days of history
    """
    print(f"Downloading {days} days of 1-minute Bitcoin data from Binance...")
    
    all_data = []
    symbol = "BTCUSDT"
    interval = "1m"
    
    # Binance allows 1000 candles per request
    # 1 day = 1440 minutes, so ~1.5 requests per day
    
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
    
    current_time = start_time
    
    while current_time < end_time:
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": current_time,
                "limit": 1000
            }
            
            print(f"  Fetching data from {datetime.fromtimestamp(current_time/1000)}...")
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if not data:
                    break
                
                # Extract timestamp and close price
                for candle in data:
                    timestamp_ms = candle[0]
                    close_price = float(candle[4])
                    
                    all_data.append({
                        'timestamp': timestamp_ms / 1000,  # Convert to seconds
                        'price': close_price
                    })
                
                # Move to next batch
                current_time = data[-1][0] + 60000  # Add 1 minute in ms
                
                # Rate limiting
                time.sleep(0.1)
                
            else:
                print(f"  Error: API returned status {response.status_code}")
                break
                
        except Exception as e:
            print(f"  Error: {e}")
            break
    
    if all_data:
        df = pd.DataFrame(all_data)
        
        # Remove duplicates
        df = df.drop_duplicates(subset=['timestamp'])
        df = df.sort_values('timestamp')
        
        # Save
        output_file = 'data/btc_1min.csv'
        df.to_csv(output_file, index=False)
        
        print(f"\n✓ Downloaded {len(df):,} 1-minute price points")
        print(f"✓ Date range: {pd.to_datetime(df['timestamp'].min(), unit='s')} to {pd.to_datetime(df['timestamp'].max(), unit='s')}")
        print(f"✓ Price range: ${df['price'].min():,.2f} - ${df['price'].max():,.2f}")
        print(f"✓ Saved to: {output_file}")
        
        return True
    else:
        print("\n✗ No data downloaded")
        return False


if __name__ == "__main__":
    import os
    os.makedirs('data', exist_ok=True)
    
    success = download_minute_data_binance(days=7)
    
    if success:
        print("\n" + "="*60)
        print("✅ High-resolution Bitcoin data ready!")
        print("="*60)
        print("\nYou can now run the backtest demo:")
        print("  python run_backtest_demo.py")
    else:
        print("\n" + "="*60)
        print("❌ Failed to download data")
        print("="*60)

