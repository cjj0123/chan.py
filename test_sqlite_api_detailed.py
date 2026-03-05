#!/usr/bin/env python3
"""
Detailed test script for SQLiteAPI
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import SQLiteAPI, create_item_dict_from_db
from Common.CEnum import AUTYPE, KL_TYPE
from Trade.db_util import CChanDB

def test_sqlite_api_detailed():
    """Test SQLiteAPI with detailed debugging"""
    print("Testing SQLiteAPI with detailed debugging...")
    
    # Test the database query directly
    db = CChanDB()
    sql = "SELECT * FROM kline_day WHERE code = 'HK.02649' ORDER BY date"
    df = db.execute_query(sql)
    print(f"Database query result: {len(df)} rows")
    if not df.empty:
        print(f"First row: {df.iloc[0].to_dict()}")
        
        # Test create_item_dict_from_db directly
        row = df.iloc[0]
        item_dict = create_item_dict_from_db(row, AUTYPE.QFQ)
        print(f"Created item dict: {item_dict}")
        
        # Test the full API
        api = SQLiteAPI("HK.02649", k_type=KL_TYPE.K_DAY, begin_date="2024-01-01", end_date="2024-01-01", autype=AUTYPE.QFQ)
        kl_data = list(api.get_kl_data())
        print(f"Full API returned {len(kl_data)} K-line units")
        if kl_data:
            klu = kl_data[0]
            print(f"KLU time: {klu.time}")
            print(f"KLU open: {klu.open}")
            print(f"KLU high: {klu.high}")
            print(f"KLU low: {klu.low}")
            print(f"KLU close: {klu.close}")
            print(f"KLU volume: {klu.volume}")
            
    else:
        print("No data found in database")

if __name__ == "__main__":
    test_sqlite_api_detailed()