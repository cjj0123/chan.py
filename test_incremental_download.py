"""
测试增量下载功能
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
import pandas as pd
from Trade.db_util import CChanDB

def test_incremental_download():
    """测试增量下载功能"""
    # 创建测试股票列表
    stock_codes = ['HK.00700']  # 腾讯控股
    
    print("开始测试增量下载功能...")
    
    # 第一次下载 - 应该下载完整数据
    print("第一次下载（365天，但30m限制为60天）:")
    download_and_save_all_stocks_multi_timeframe(
        stock_codes,
        days=365,
        timeframes=['30m'],
        log_callback=print
    )
    
    # 检查数据库中的数据量
    db = CChanDB()
    df_30m = db.execute_query("SELECT COUNT(*) as count FROM kline_30m WHERE code = 'HK.00700'")
    count_30m = df_30m.iloc[0]['count'] if not df_30m.empty else 0
    print(f"第一次下载后30分钟数据条数: {count_30m}")
    
    # 第二次下载 - 应该只下载缺失的数据或跳过
    print("\n第二次下载（相同参数）:")
    download_and_save_all_stocks_multi_timeframe(
        stock_codes,
        days=365,
        timeframes=['30m'],
        log_callback=print
    )
    
    # 再次检查数据量
    df_30m_after = db.execute_query("SELECT COUNT(*) as count FROM kline_30m WHERE code = 'HK.00700'")
    count_30m_after = df_30m_after.iloc[0]['count'] if not df_30m_after.empty else 0
    print(f"第二次下载后30分钟数据条数: {count_30m_after}")
    
    if count_30m == count_30m_after:
        print("✅ 增量下载功能正常：第二次下载没有重复数据")
    else:
        print("⚠️  可能存在重复数据")
    
    print("测试完成!")

if __name__ == "__main__":
    test_incremental_download()