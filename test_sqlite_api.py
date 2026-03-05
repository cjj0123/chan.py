#!/usr/bin/env python3
"""
Test script for SQLiteAPI
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import SQLiteAPI
from Common.CEnum import AUTYPE, KL_TYPE

def test_sqlite_api():
    """Test SQLiteAPI functionality"""
    try:
        # Test with a sample stock code from the database
        api = SQLiteAPI("HK.02649", k_type=KL_TYPE.K_DAY, autype=AUTYPE.QFQ)
        print("SQLiteAPI initialized successfully")
        
        # Try to get data
        data = list(api.get_kl_data())
        print(f"Retrieved {len(data)} K-line units")
        
        if data:
            print(f"First K-line unit: {data[0]}")
            print(f"Time: {data[0].time}")
            print(f"Open: {data[0].open}, High: {data[0].high}, Low: {data[0].low}, Close: {data[0].close}")
        
        return True
    except Exception as e:
        print(f"Error testing SQLiteAPI: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_sqlite_api()