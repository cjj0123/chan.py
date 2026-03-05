#!/usr/bin/env python3
"""
Test script with minimal data to see if it causes IndexError
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, KL_TYPE
import pandas as pd

def create_test_data():
    """Create test data with more entries"""
    data = []
    for i in range(50):  # Create 50 days of data
        date = f"2024-01-{i+1:02d}"
        if i+1 > 31:  # Handle month overflow
            date = f"2024-02-{i-30:02d}"
        data.append({
            'code': 'TEST.001',
            'date': date,
            'open': 10.0 + i * 0.1,
            'high': 10.5 + i * 0.1,
            'low': 9.5 + i * 0.1,
            'close': 10.2 + i * 0.1,
            'volume': 1000000,
            'turnover': 10000000,
            'turnrate': 1.0
        })
    return data

def test_with_more_data():
    """Test with more data"""
    try:
        # First, save test data to database
        from Trade.db_util import CChanDB
        import sqlite3
        
        db = CChanDB()
        test_data = create_test_data()
        df = pd.DataFrame(test_data)
        
        with sqlite3.connect(db.db_path) as conn:
            df.to_sql('kline_day', conn, if_exists='replace', index=False)
        
        print(f"Saved {len(test_data)} test records to database")
        
        # Now test CChan
        config = CChanConfig()
        chan = CChan(
            code="TEST.001",
            begin_time="2024-01-01",
            end_time="2024-02-20",
            data_src="custom:SQLiteAPI.SQLiteAPI",
            lv_list=[KL_TYPE.K_DAY],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        print("CChan initialized successfully with more data")
        print(f"Number of K-lines: {len(chan[0])}")
        
        # Try to get buy points
        bsp_list = chan.get_latest_bsp(number=0)
        print(f"Number of buy/sell points: {len(bsp_list)}")
        
        return True
        
    except Exception as e:
        print(f"Error with more data: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_with_more_data()