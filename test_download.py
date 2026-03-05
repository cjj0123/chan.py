#!/usr/bin/env python3
"""
测试数据下载功能
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from App.ashare_bsp_scanner_gui import get_tradable_stocks
from DataAPI.SQLiteAPI import download_and_save_all_stocks

def main():
    print("获取股票列表...")
    stock_list = get_tradable_stocks()
    print(f"获取到 {len(stock_list)} 只股票")
    
    if len(stock_list) > 0:
        print("开始下载前3只A股的数据...")
        # 过滤出A股股票（以SZ.或SH.开头）
        a_stocks = stock_list[stock_list['代码'].str.startswith(('SZ.', 'SH.'))]
        if len(a_stocks) > 0:
            test_codes = a_stocks['代码'].tolist()[:3]
            print(f"选择的A股代码: {test_codes}")
            try:
                download_and_save_all_stocks(test_codes, days=30)
                print("数据下载完成！")
            except Exception as e:
                print(f"数据下载失败: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("没有找到A股股票")
    else:
        print("没有获取到股票列表")

if __name__ == "__main__":
    main()