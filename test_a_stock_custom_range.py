"""
测试A股自定义日期范围下载
"""
import sys
from pathlib import Path
import sqlite3

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
from Trade.db_util import CChanDB

def test_a_stock_custom_range():
    """测试A股自定义日期范围下载"""
    # 创建测试股票列表
    stock_codes = ['SH.600089']  # A股
    
    print("开始测试A股自定义日期范围下载功能...")
    
    # 清理现有数据
    db = CChanDB()
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("DELETE FROM kline_30m WHERE code = 'SH.600089'")
    
    # 下载自定义日期范围的30分钟数据
    print("下载2025-01-01到2025-12-31的A股30分钟数据...")
    download_and_save_all_stocks_multi_timeframe(
        stock_codes,
        timeframes=['30m'],
        start_date='2025-01-01',
        end_date='2025-12-31',
        log_callback=print
    )
    
    # 检查数据库中的数据量
    df_30m = db.execute_query("SELECT COUNT(*) as count FROM kline_30m WHERE code = 'SH.600089'")
    count_30m = df_30m.iloc[0]['count'] if not df_30m.empty else 0
    print(f"自定义日期范围30分钟数据条数: {count_30m}")
    
    # 获取日期范围
    if count_30m > 0:
        df_dates = db.execute_query("SELECT MIN(date) as min_date, MAX(date) as max_date FROM kline_30m WHERE code = 'SH.600089'")
        print(f"数据日期范围: {df_dates.iloc[0]['min_date']} 到 {df_dates.iloc[0]['max_date']}")
    
    print("测试完成!")

if __name__ == "__main__":
    test_a_stock_custom_range()