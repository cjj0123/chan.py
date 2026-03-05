#!/usr/bin/env python3
"""
Test script to simulate OfflineScanThread behavior
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from datetime import datetime, timedelta
from Chan import CChan
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE
from ChanConfig import CChanConfig

def test_offline_scan():
    """Test offline scan behavior"""
    print("Testing offline scan behavior...")
    
    # Create a stock list similar to what get_local_stock_list() returns
    stock_list = pd.DataFrame({
        '代码': ['HK.02649', 'SZ.300772', 'SH.603281'],
        '名称': ['Test Stock 1', 'Test Stock 2', 'Test Stock 3'],
        '最新价': [0.0, 0.0, 0.0],
        '涨跌幅': [0.0, 0.0, 0.0]
    })
    
    # Create config similar to get_chan_config()
    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": "1,1p,2,2s,3a,3b",
        "print_warning": False,
        "zs_algo": "normal",
    })
    
    days = 365
    begin_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_time = datetime.now().strftime("%Y-%m-%d")
    
    for idx, row in stock_list.iterrows():
        code = row['代码']
        name = row['名称']
        print(f"Processing {code} {name}...")
        
        try:
            chan = CChan(
                code=code,
                begin_time=begin_time,
                end_time=end_time,
                data_src="custom:SQLiteAPI.SQLiteAPI",  # 使用自定义数据源（SQLite）
                lv_list=[KL_TYPE.K_DAY],
                config=config,
                autype=AUTYPE.QFQ,
            )
            
            print(f"  Successfully created CChan for {code}")
            if len(chan[0]) > 0 and len(chan[0][-1]) > 0:
                last_klu = chan[0][-1][-1]
                print(f"  Last K-line: {last_klu.time} O:{last_klu.open} H:{last_klu.high} L:{last_klu.low} C:{last_klu.close}")
            else:
                print(f"  No K-line data for {code}")
                
        except Exception as e:
            print(f"  Error processing {code}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_offline_scan()