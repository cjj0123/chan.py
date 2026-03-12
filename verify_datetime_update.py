import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import sqlite3

# Add project root to path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
from Trade.db_util import CChanDB

def verify():
    code = "HK.00700"
    tf = "5m"
    table_name = f"kline_{tf}"
    db = CChanDB()
    
    # 1. Clean up existing data for test
    print(f"🧹 Cleaning up {code} in {table_name}...")
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(f"DELETE FROM {table_name} WHERE code = ?", (code,))
        conn.commit()
    
    # 2. Perform first update to a specific mid-day time
    # Note: Use a recent date that definitely has data
    base_date = "2026-03-06" # A recent Friday
    mid_day = f"{base_date} 11:30:00"
    
    print(f"🚀 Step 1: Updating {code} up to {mid_day}...")
    download_and_save_all_stocks_multi_timeframe(
        [code], 
        days=5, 
        timeframes=[tf],
        start_date=f"{base_date} 09:30:00",
        end_date=mid_day
    )
    
    # Check max date
    with sqlite3.connect(db.db_path) as conn:
        res = pd.read_sql_query(f"SELECT MAX(date) as max_date FROM {table_name} WHERE code = ?", conn, params=(code,))
        max_date_1 = res.iloc[0]['max_date']
        print(f"📊 Max date after Step 1: {max_date_1}")
        
    # 3. Perform second update to end of day
    end_day = f"{base_date} 16:00:00"
    print(f"\n🚀 Step 2: Updating {code} from {max_date_1} up to {end_day}...")
    download_and_save_all_stocks_multi_timeframe(
        [code], 
        days=5, 
        timeframes=[tf],
        start_date=f"{base_date} 09:30:00",
        end_date=end_day
    )
    
    # Check max date again
    with sqlite3.connect(db.db_path) as conn:
        res = pd.read_sql_query(f"SELECT MAX(date) as max_date FROM {table_name} WHERE code = ?", conn, params=(code,))
        max_date_2 = res.iloc[0]['max_date']
        print(f"📊 Max date after Step 2: {max_date_2}")
        
    if max_date_2 > max_date_1:
        print("\n✅ SUCCESS: Incremental intraday update worked!")
    else:
        print("\n❌ FAILURE: Max date did not advance.")

if __name__ == "__main__":
    verify()
