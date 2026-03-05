"""
测试多时间级别数据下载（保持与日线相同的逻辑）
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe

def main():
    # 测试不同市场的股票
    test_stocks = [
        'HK.00700',  # 港股 - 应该优先使用Futu
        'SZ.000001', # A股 - 应该优先使用BaoStock
        'US.AAPL'    # 美股 - 应该使用AKShare
    ]
    
    print("开始下载多时间级别数据（保持与日线相同的逻辑）...")
    download_and_save_all_stocks_multi_timeframe(
        stock_codes=test_stocks,
        days=365,
        timeframes=['30m'],  # 只测试30分钟线
        log_callback=print
    )
    print("下载完成！")

if __name__ == "__main__":
    main()