"""
测试扩展时间框架数据下载功能
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
import pandas as pd
from Trade.db_util import CChanDB

def test_extended_timeframe_download():
    """测试扩展时间框架数据下载"""
    # 创建测试股票列表
    stock_codes = ['HK.00700']  # 腾讯控股
    
    print("开始测试365天的30分钟和5分钟数据下载...")
    
    # 下载365天的30分钟和5分钟数据
    download_and_save_all_stocks_multi_timeframe(
        stock_codes,
        days=365,
        timeframes=['30m', '5m'],
        log_callback=print
    )
    
    # 检查数据库中的数据量
    db = CChanDB()
    
    # 检查30分钟数据
    df_30m = db.execute_query("SELECT COUNT(*) as count FROM kline_30m WHERE code = 'HK.00700'")
    count_30m = df_30m.iloc[0]['count'] if not df_30m.empty else 0
    print(f"30分钟数据条数: {count_30m}")
    
    # 检查5分钟数据  
    df_5m = db.execute_query("SELECT COUNT(*) as count FROM kline_5m WHERE code = 'HK.00700'")
    count_5m = df_5m.iloc[0]['count'] if not df_5m.empty else 0
    print(f"5分钟数据条数: {count_5m}")
    
    # 获取最早和最晚的日期
    if count_30m > 0:
        df_30m_dates = db.execute_query("SELECT MIN(date) as min_date, MAX(date) as max_date FROM kline_30m WHERE code = 'HK.00700'")
        print(f"30分钟数据日期范围: {df_30m_dates.iloc[0]['min_date']} 到 {df_30m_dates.iloc[0]['max_date']}")
    
    if count_5m > 0:
        df_5m_dates = db.execute_query("SELECT MIN(date) as min_date, MAX(date) as max_date FROM kline_5m WHERE code = 'HK.00700'")
        print(f"5分钟数据日期范围: {df_5m_dates.iloc[0]['min_date']} 到 {df_5m_dates.iloc[0]['max_date']}")
    
    print("测试完成!")

if __name__ == "__main__":
    test_extended_timeframe_download()