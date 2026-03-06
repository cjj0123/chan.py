#!/usr/bin/env python3
"""
从Futu批量下载A股数据到本地数据库
"""

import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
import pandas as pd

# A股测试股票列表（您可以根据需要修改）
a_stocks = [
    'SH.600000',  # 浦发银行
    'SZ.000001',  # 平安银行  
    'SH.600519',  # 贵州茅台
    'SZ.000858',  # 五粮液
    'SH.601318',  # 中国平安
    'SH.600036',  # 招商银行
    'SZ.002415',  # 海康威视
    'SH.601012',  # 隆基绿能
]

def log_callback(msg):
    print(f"📝 {msg}")

if __name__ == "__main__":
    print("🚀 开始从Futu下载A股数据...")
    print(f"📊 准备下载 {len(a_stocks)} 只A股")
    print(f"   股票列表: {a_stocks}")
    
    try:
        download_and_save_all_stocks_multi_timeframe(
            a_stocks,
            days=365,  # 下载最近365天的数据
            timeframes=['day', '30m', '5m'],  # 支持日线、30分钟、5分钟
            log_callback=log_callback
        )
        print("🎉 A股数据下载完成！")
        
        # 验证数据
        from Trade.db_util import CChanDB
        db = CChanDB()
        count_5m = db.execute_query("SELECT COUNT(*) FROM kline_5m WHERE code LIKE 'SH.6%' OR code LIKE 'SZ.0%' OR code LIKE 'SZ.3%';")['COUNT(*)'].iloc[0]
        count_day = db.execute_query("SELECT COUNT(*) FROM kline_day WHERE code LIKE 'SH.6%' OR code LIKE 'SZ.0%' OR code LIKE 'SZ.3%';")['COUNT(*)'].iloc[0]
        
        print(f"✅ 数据验证:")
        print(f"   - 5分钟数据点: {count_5m}")
        print(f"   - 日线数据点: {count_day}")
        
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        import traceback
        traceback.print_exc()