#!/usr/bin/env python3
"""
测试修复后的BaoStock A股代码格式
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from DataAPI.SQLiteAPI import _download_a_stock_data
import datetime

def test_baostock_a_stock():
    """测试A股BaoStock下载功能"""
    print("=== 测试A股BaoStock下载 ===")
    
    # 测试A股股票
    test_stocks = ['SH.600519', 'SZ.000858']
    end_date = datetime.datetime.now().strftime("%Y-%m-%d")
    begin_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    
    for stock in test_stocks:
        print(f"\n测试股票: {stock}")
        try:
            kl_data, source = _download_a_stock_data(stock, begin_date, end_date)
            if kl_data and len(kl_data) > 0:
                print(f"✅ 成功下载 {stock} ({len(kl_data)} 条数据) - 数据源: {source}")
                print(f"   最新日期: {kl_data[-1]['time']}, 收盘价: {kl_data[-1]['close']}")
            else:
                print(f"⚠️  {stock} 无有效数据")
        except Exception as e:
            print(f"❌ 下载 {stock} 失败: {e}")

if __name__ == "__main__":
    test_baostock_a_stock()