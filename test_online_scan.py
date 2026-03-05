#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_futu_watchlist_stocks
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_SRC

def test_single_stock_analysis(code):
    """测试单个股票的缠论分析"""
    print(f"测试股票 {code} 的缠论分析...")
    try:
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
            "zs_algo": "normal"
        })
        
        chan = CChan(
            code=code,
            begin_time="2025-01-01",
            end_time="2026-03-05",
            data_src=DATA_SRC.AKSHARE,
            lv_list=[KL_TYPE.K_DAY],
            config=config,
            autype=AUTYPE.QFQ
        )
        
        buy_points = chan.get_bsp()
        print(f"股票 {code} 找到 {len(buy_points)} 个买点")
        return True
        
    except Exception as e:
        print(f"股票 {code} 分析失败: {e}")
        return False

def main():
    # 获取富途自选股
    stock_list = get_futu_watchlist_stocks()
    print(f"获取到 {len(stock_list)} 只富途自选股")
    
    # 测试前几个股票
    test_count = 0
    success_count = 0
    
    for idx, row in stock_list.iterrows():
        code = row['代码']
        if test_count >= 3:  # 只测试前3个
            break
            
        # 跳过可能有问题的股票
        if 'US.' not in code and 'HK.' not in code and 'SZ.' not in code and 'SH.' not in code:
            continue
            
        test_count += 1
        print(f"\n--- 测试第 {test_count} 只股票 ---")
        
        if test_single_stock_analysis(code):
            success_count += 1
    
    print(f"\n=== 在线扫描测试结果: {success_count}/{test_count} 成功 ===")
    
    if success_count > 0:
        print("✅ 在线扫描功能基本正常！")
    else:
        print("❌ 在线扫描仍有问题")

if __name__ == "__main__":
    main()