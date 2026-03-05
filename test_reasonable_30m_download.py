"""
测试合理的30分钟数据下载（60天）
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
import pandas as pd
from Trade.db_util import CChanDB

def test_reasonable_30m_download():
    """测试合理的30分钟数据下载"""
    # 创建测试股票列表
    stock_codes = ['HK.00700']  # 腾讯控股
    
    print("开始测试60天的30分钟数据下载...")
    
    # 下载60天的30分钟数据
    download_and_save_all_stocks_multi_timeframe(
        stock_codes,
        days=365,  # 用户设置365天，但30m会被限制为60天
        timeframes=['30m'],
        log_callback=print
    )
    
    # 检查数据库中的数据量
    db = CChanDB()
    
    # 检查30分钟数据
    df_30m = db.execute_query("SELECT COUNT(*) as count FROM kline_30m WHERE code = 'HK.00700'")
    count_30m = df_30m.iloc[0]['count'] if not df_30m.empty else 0
    print(f"30分钟数据条数: {count_30m}")
    
    # 获取最早和最晚的日期
    if count_30m > 0:
        df_30m_dates = db.execute_query("SELECT MIN(date) as min_date, MAX(date) as max_date FROM kline_30m WHERE code = 'HK.00700'")
        print(f"30分钟数据日期范围: {df_30m_dates.iloc[0]['min_date']} 到 {df_30m_dates.iloc[0]['max_date']}")
    
    print("测试完成!")

if __name__ == "__main__":
    test_reasonable_30m_download()