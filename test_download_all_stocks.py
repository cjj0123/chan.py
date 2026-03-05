#!/usr/bin/env python3
"""
测试下载所有125只股票的功能
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_futu_watchlist_stocks
from DataAPI.SQLiteAPI import download_and_save_all_stocks

def test_download_all():
    print("正在测试下载所有125只股票...")
    try:
        # 获取富途自选股列表
        stock_list = get_futu_watchlist_stocks()
        print(f"获取到 {len(stock_list)} 只股票")
        
        if len(stock_list) == 0:
            print("❌ 未获取到任何股票")
            return
        
        # 测试下载前10只股票（避免测试时间过长）
        test_stocks = stock_list['代码'].tolist()[:10]
        print(f"测试下载前10只股票: {test_stocks}")
        
        # 执行下载
        download_and_save_all_stocks(test_stocks, days=30)  # 只下载30天数据加快测试
        
        print("✅ 下载测试完成")
        
    except Exception as e:
        print(f"❌ 下载测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_download_all()