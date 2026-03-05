#!/usr/bin/env python3
"""
Test script to simulate GUI call to CChan with SQLiteAPI
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, KL_TYPE

def test_gui_simulation():
    """Simulate GUI call to CChan"""
    try:
        config = CChanConfig()
        code = "HK.02649"
        name = "Test Stock"
        
        begin_time = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        end_time = datetime.now().strftime("%Y-%m-%d")
        
        print(f"Testing with code: {code}, name: {name}")
        print(f"Time range: {begin_time} to {end_time}")
        
        chan = CChan(
            code=code,
            begin_time=begin_time,
            end_time=end_time,
            data_src="custom:SQLiteAPI.SQLiteAPI",  # 使用自定义数据源（SQLite）
            lv_list=[KL_TYPE.K_DAY],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        print("CChan initialized successfully")
        print(f"Number of K-lines: {len(chan[0])}")
        
        if len(chan[0]) == 0 or len(chan[0][-1]) == 0:
            print("No K-line data")
            return False
            
        last_klu = chan[0][-1][-1]
        last_time = last_klu.time
        last_date = datetime(last_time.year, last_time.month, last_time.day)
        days_diff = (datetime.now() - last_date).days
        print(f"Last K-line date: {last_date}, days ago: {days_diff}")
        
        if days_diff > 15:
            print("Stock suspended for more than 15 days")
            return False
            
        # Check for buy points
        bsp_list = chan.get_latest_bsp(number=0)
        cutoff_date = datetime.now() - timedelta(days=3)
        buy_points = [
            bsp for bsp in bsp_list
            if bsp.is_buy and datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day) >= cutoff_date
        ]
        
        print(f"Found {len(buy_points)} recent buy points")
        
        return True
        
    except Exception as e:
        print(f"Error in GUI simulation: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_gui_simulation()