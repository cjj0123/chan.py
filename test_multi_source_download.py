#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from DataAPI.SQLiteAPI import download_and_save_all_stocks

def test_multi_source_download():
    """测试多数据源下载功能"""
    # 测试不同市场的股票
    test_stocks = [
        "US.AAPL",      # 美股
        "HK.00700",     # 港股  
        "SH.600519",    # A股
        "SZ.000858"     # A股
    ]
    
    print("=== 多数据源下载测试 ===")
    print(f"测试股票: {test_stocks}")
    print()
    
    try:
        download_and_save_all_stocks(test_stocks, days=30)
        print("\n✅ 多数据源下载测试完成")
    except Exception as e:
        print(f"\n❌ 多数据源下载测试失败: {e}")

if __name__ == "__main__":
    test_multi_source_download()