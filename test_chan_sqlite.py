#!/usr/bin/env python3
"""
Test script for CChan with SQLiteAPI
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, KL_TYPE

def test_chan_with_sqlite():
    """Test CChan with SQLiteAPI"""
    try:
        config = CChanConfig()
        
        # Test with a sample stock code from the database
        chan = CChan(
            code="HK.02649",
            begin_time="2024-01-01",
            end_time="2024-01-10",
            data_src="custom:SQLiteAPI.SQLiteAPI",  # 使用自定义数据源（SQLite）
            lv_list=[KL_TYPE.K_DAY],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        print("CChan initialized successfully with SQLiteAPI")
        print(f"Number of K-lines: {len(chan[0])}")
        
        if len(chan[0]) > 0:
            # Get the first K-line unit from the first K-line
            first_klu = chan[0][0][-1]  # Get the last unit of the first K-line
            last_klu = chan[0][-1][-1]  # Get the last unit of the last K-line
            print(f"First K-line unit time: {first_klu.time}")
            print(f"Last K-line unit time: {last_klu.time}")
            
            # Try to get buy points
            bsp_list = chan.get_latest_bsp(number=0)
            print(f"Number of buy/sell points: {len(bsp_list)}")
        
        return True
    except Exception as e:
        print(f"Error testing CChan with SQLiteAPI: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_chan_with_sqlite()