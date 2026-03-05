"""
下载测试数据到本地数据库（多时间级别）
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe

def main():
    # 测试股票代码
    test_stocks = ['HK.00700']  # 腾讯控股
    
    print("开始下载多时间级别数据...")
    download_and_save_all_stocks_multi_timeframe(
        stock_codes=test_stocks,
        days=365,
        timeframes=['day', '30m', '5m', '1m'],
        log_callback=print
    )
    print("下载完成！")

if __name__ == "__main__":
    main()