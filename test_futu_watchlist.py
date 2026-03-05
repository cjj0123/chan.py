#!/usr/bin/env python3
"""
测试富途自选股列表获取功能
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_futu_watchlist_stocks
import pandas as pd

def test_futu_watchlist():
    print("正在测试富途自选股列表获取...")
    try:
        stock_list = get_futu_watchlist_stocks()
        print(f"获取到 {len(stock_list)} 只股票")
        print(f"股票列表前10只:")
        print(stock_list.head(10))
        
        # 统计各市场股票数量
        us_count = len(stock_list[stock_list['代码'].str.startswith('US.')])
        hk_count = len(stock_list[stock_list['代码'].str.startswith('HK.')])
        sh_count = len(stock_list[stock_list['代码'].str.startswith('SH.')])
        sz_count = len(stock_list[stock_list['代码'].str.startswith('SZ.')])
        
        print(f"\n市场分布:")
        print(f"美股: {us_count}")
        print(f"港股: {hk_count}")
        print(f"沪市: {sh_count}")
        print(f"深市: {sz_count}")
        print(f"总计: {us_count + hk_count + sh_count + sz_count}")
        
        return stock_list
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    test_futu_watchlist()