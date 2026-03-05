#!/usr/bin/env python3
"""
测试完整的BaoStock下载和数据提取流程
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from DataAPI.SQLiteAPI import _download_a_stock_data, _extract_kl_data
from DataAPI.BaoStockAPI import CBaoStock
from Common.CEnum import KL_TYPE, AUTYPE
import datetime

def test_complete_baostock_flow():
    """测试完整的BaoStock下载流程"""
    print("=== 测试完整BaoStock下载流程 ===")
    
    # 测试A股股票
    stock_code = "SH.600519"
    end_date = datetime.datetime.now().strftime("%Y-%m-%d")
    begin_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    
    print(f"测试股票: {stock_code}")
    print(f"日期范围: {begin_date} 到 {end_date}")
    
    try:
        # 直接测试BaoStock API
        print("\n1. 测试直接使用BaoStock API:")
        market, stock_num = stock_code.split(".")
        bao_code = f"sh.{stock_num}" if market == "SH" else f"sz.{stock_num}"
        
        CBaoStock.do_init()
        api = CBaoStock(bao_code, k_type=KL_TYPE.K_DAY, begin_date=begin_date, end_date=end_date, autype=AUTYPE.QFQ)
        
        # 尝试获取第一条数据
        kl_generator = api.get_kl_data()
        first_kl = next(kl_generator, None)
        if first_kl:
            print(f"   ✅ 成功创建KLine_Unit: time={first_kl.time}, close={first_kl.close}")
            print(f"   KLine_Unit属性: {dir(first_kl)}")
        else:
            print("   ❌ 无法获取KLine数据")
            return
        
        # 测试_extract_kl_data函数
        print("\n2. 测试_extract_kl_data函数:")
        kl_data = _extract_kl_data(api, stock_code)
        if kl_data and len(kl_data) > 0:
            print(f"   ✅ 成功提取 {len(kl_data)} 条数据")
            print(f"   第一条数据: {kl_data[0]}")
        else:
            print("   ❌ 无法提取数据")
            return
        
        # 测试_download_a_stock_data函数
        print("\n3. 测试_download_a_stock_data函数:")
        kl_data2, source = _download_a_stock_data(stock_code, begin_date, end_date)
        if kl_data2 and len(kl_data2) > 0:
            print(f"   ✅ 成功下载 {len(kl_data2)} 条数据 - 数据源: {source}")
            print(f"   第一条数据: {kl_data2[0]}")
        else:
            print("   ❌ 无法下载数据")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_complete_baostock_flow()