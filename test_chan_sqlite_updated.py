#!/usr/bin/env python3
"""
Test script for CChan with SQLiteAPI - updated with more data
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Chan import CChan
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE

def test_chan_with_sqlite():
    """Test CChan with SQLite data source"""
    print("Testing CChan with SQLite data source...")
    
    try:
        chan = CChan(
            code="HK.02649",
            begin_time="2024-01-01",
            end_time="2024-01-10",  # Load more data
            data_src="custom:SQLiteAPI.SQLiteAPI",  # 使用自定义数据源（SQLite）
            lv_list=[KL_TYPE.K_DAY],
            autype=AUTYPE.QFQ,
        )
        
        print(f"Successfully created CChan object for {chan.code}")
        print(f"Number of K-line levels: {len(chan.kl_datas)}")
        
        if len(chan[0]) > 0:
            print(f"Number of K-lines in level 0: {len(chan[0][-1])}")
            if len(chan[0][-1]) > 0:
                klu = chan[0][-1][-1]
                print(f"Last K-line: {klu.time} O:{klu.open} H:{klu.high} L:{klu.low} C:{klu.close}")
        else:
            print("No K-line data loaded")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_chan_with_sqlite()