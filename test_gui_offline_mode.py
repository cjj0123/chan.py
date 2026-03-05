#!/usr/bin/env python3
"""
Test script to simulate GUI offline mode behavior
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from datetime import datetime, timedelta
from Chan import CChan
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE
from ChanConfig import CChanConfig

def get_local_stock_list():
    """Simulate get_local_stock_list function"""
    from Trade.db_util import CChanDB
    db = CChanDB()
    query = "SELECT DISTINCT code FROM kline_day ORDER BY code"
    df_codes = db.execute_query(query)
    
    if df_codes.empty:
        return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])
        
    result_df = pd.DataFrame({
        '代码': df_codes['code'],
        '名称': [''] * len(df_codes),
        '最新价': [0.0] * len(df_codes),
        '涨跌幅': [0.0] * len(df_codes)
    })
    return result_df

def get_chan_config():
    """Simulate get_chan_config function"""
    return CChanConfig({
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

def test_gui_offline_mode():
    """Test GUI offline mode behavior"""
    print("Testing GUI offline mode behavior...")
    
    # Get stock list from local database
    stock_list = get_local_stock_list()
    print(f"Found {len(stock_list)} stocks in local database")
    
    if stock_list.empty:
        print("No stocks found in local database")
        return
        
    # Create config
    config = get_chan_config()
    
    # Use date range that matches our test data
    begin_time = "2024-01-01"
    end_time = "2024-01-10"
    
    success_count = 0
    fail_count = 0
    
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
            
            # Check if we have data
            if len(chan[0]) == 0 or len(chan[0][-1]) == 0:
                fail_count += 1
                print(f"  ⏭️ {code} {name}: 无K线数据")
                continue
                
            success_count += 1
            print(f"  ✅ {code} {name}: 成功加载 {len(chan[0][-1])} 条K线")
            
        except Exception as e:
            fail_count += 1
            print(f"  ❌ {code} {name}: {str(e)[:50]}")
            continue
            
    print(f"扫描完成: 成功 {success_count}, 失败 {fail_count}")

if __name__ == "__main__":
    test_gui_offline_mode()