#!/usr/bin/env python3
"""
测试完整的125只股票工作流程：
1. 从Futu获取125只自选股
2. 下载并保存到本地数据库
3. 从本地数据库读取并进行离线扫描
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_futu_watchlist_stocks
from DataAPI.SQLiteAPI import download_and_save_all_stocks
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
import pandas as pd

def test_complete_workflow():
    """测试完整工作流程"""
    print("=== 测试完整125只股票工作流程 ===")
    
    # 1. 获取Futu自选股列表
    print("\n1. 获取Futu自选股列表...")
    stock_list = get_futu_watchlist_stocks()
    print(f"   ✅ 获取到 {len(stock_list)} 只股票")
    
    # 只测试前5只股票以节省时间
    test_stocks = stock_list.head(5)['代码'].tolist()
    print(f"   📋 测试股票: {test_stocks}")
    
    # 2. 下载并保存到本地数据库
    print("\n2. 下载并保存到本地数据库...")
    try:
        download_and_save_all_stocks(test_stocks, days=30)
        print("   ✅ 数据库更新完成")
    except Exception as e:
        print(f"   ❌ 数据库更新失败: {e}")
        return
    
    # 3. 从本地数据库读取并进行离线扫描
    print("\n3. 从本地数据库读取并进行离线扫描...")
    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": "1,1p,2,2s,3a,3b",
        "print_warning": False,
        "zs_algo": "normal",
    })
    
    success_count = 0
    fail_count = 0
    
    for code in test_stocks:
        print(f"\n   📈 扫描股票: {code}")
        try:
            from Common.CEnum import KL_TYPE
            from Common.CEnum import AUTYPE
            chan = CChan(
                code=code,
                begin_time="2026-02-01",
                end_time="2026-03-05",
                data_src="custom:SQLiteAPI.SQLiteAPI",
                lv_list=[KL_TYPE.K_DAY],
                config=config,
                autype=AUTYPE.QFQ
            )
            
            buy_points = [
                {"code": code, "time": bs.time, "price": bs.price, "type": str(bs.type)}
                for bs in chan.get_bsp()
            ]
            
            if buy_points:
                print(f"      ✅ 发现 {len(buy_points)} 个买点")
                success_count += 1
            else:
                print(f"      ⚠️  未发现买点")
                success_count += 1
                
        except Exception as e:
            print(f"      ❌ 扫描失败: {e}")
            fail_count += 1
    
    print(f"\n✅ 扫描完成! 成功: {success_count}, 失败: {fail_count}")
    print("\n=== 完整工作流程测试结束 ===")

if __name__ == "__main__":
    test_complete_workflow()