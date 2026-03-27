#!/usr/bin/env python3
"""
自动下载富途自选股数据脚本
- 补齐所有自选股自2024年1月1日以来的日线、30分、5分、1分数据
- 可用于每日盘后自动下载当日数据
"""

import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))

from datetime import datetime, timedelta
import pandas as pd
from Common.StockUtils import get_futu_watchlist_stocks
from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe

def get_watchlist_stocks_with_fallback():
    """
    获取自选股列表，如果富途失败则使用测试股票列表
    """
    print("正在获取富途自选股列表...")
    stock_list = get_futu_watchlist_stocks()
    
    if stock_list.empty:
        print("⚠️  富途自选股获取失败，使用默认股票列表")
        # 使用默认的测试股票
        default_stocks = ['US.AAPL', 'US.MSFT', 'HK.00700', 'SH.600000', 'SZ.000001']
        stock_list = pd.DataFrame({
            '代码': default_stocks,
            '名称': ['苹果', '微软', '腾讯', '浦发银行', '平安银行'],
            '最新价': [0.0] * len(default_stocks),
            '涨跌幅': [0.0] * len(default_stocks)
        })
    
    return stock_list

def download_historical_data(start_date="2024-01-01", end_date=None):
    """
    下载历史数据
    
    Args:
        start_date: 开始日期，默认为2024-01-01
        end_date: 结束日期，默认为今天
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"📅 准备下载自选股数据: {start_date} 到 {end_date}")
    
    # 获取自选股列表
    stock_list = get_watchlist_stocks_with_fallback()
    stock_codes = stock_list['代码'].tolist()
    
    print(f"📊 共有 {len(stock_codes)} 只股票需要下载")
    print(f"前10只股票: {stock_codes[:10]}")
    
    # 统计各市场股票数量
    us_count = len([code for code in stock_codes if code.startswith('US.')])
    hk_count = len([code for code in stock_codes if code.startswith('HK.')])
    sh_count = len([code for code in stock_codes if code.startswith('SH.')])
    sz_count = len([code for code in stock_codes if code.startswith('SZ.')])
    
    print(f"\n📈 市场分布:")
    print(f"  美股: {us_count} 只")
    print(f"  港股: {hk_count} 只") 
    print(f"  沪市: {sh_count} 只")
    print(f"  深市: {sz_count} 只")
    
    # 定义要下载的时间级别
    timeframes = ['day', '30m', '5m', '1m']
    
    def log_callback(msg):
        print(msg)
    
    # 执行下载
    print(f"\n🚀 开始下载数据...")
    download_and_save_all_stocks_multi_timeframe(
        stock_codes=stock_codes,
        days=1095,  # 3年数据，确保有足够历史数据用于缠论分析
        timeframes=timeframes,
        log_callback=log_callback,
        start_date=start_date,
        end_date=end_date
    )
    
    print(f"\n✅ 数据下载完成！")

def download_today_data():
    """
    下载今日数据（用于每日盘后执行）
    """
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"📅 准备下载今日数据: {today}")
    download_historical_data(start_date=today, end_date=today)

def main():
    """
    主函数
    支持两种模式：
    1. python auto_download_watchlist_data.py          # 补齐2024-01-01至今的历史数据
    2. python auto_download_watchlist_data.py today   # 只下载今日数据
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='自动下载富途自选股数据')
    parser.add_argument('mode', nargs='?', default='historical', 
                       choices=['historical', 'today'],
                       help='下载模式: historical(历史数据) 或 today(今日数据)')
    
    args = parser.parse_args()
    
    if args.mode == 'today':
        print("=== 下载今日数据 ===")
        download_today_data()
    else:
        print("=== 补齐历史数据 (2024-01-01 至今) ===")
        download_historical_data()

if __name__ == "__main__":
    main()