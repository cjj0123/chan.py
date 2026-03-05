#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from DataAPI.AkshareAPI import CAkshare
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD

def test_us_stock():
    """测试美股数据获取"""
    print("测试美股 AAPL...")
    try:
        api = CAkshare('us.AAPL', k_type=KL_TYPE.K_DAY, begin_date='2025-01-01', end_date='2026-03-05', autype=AUTYPE.QFQ)
        count = 0
        for kl in api.get_kl_data():
            count += 1
            if count <= 3:  # 只打印前3根K线
                volume = kl.trade_info.metric.get(DATA_FIELD.FIELD_VOLUME, 0)
                print(f"K线 {count}: {kl.time} O:{kl.open} H:{kl.high} L:{kl.low} C:{kl.close} V:{volume}")
        print(f"成功获取 {count} 根K线")
        return count > 0
    except Exception as e:
        print(f"美股测试失败: {e}")
        return False

def test_hk_stock():
    """测试港股数据获取"""
    print("\n测试港股 00700...")
    try:
        api = CAkshare('hk.00700', k_type=KL_TYPE.K_DAY, begin_date='2025-01-01', end_date='2026-03-05', autype=AUTYPE.QFQ)
        count = 0
        for kl in api.get_kl_data():
            count += 1
            if count <= 3:
                volume = kl.trade_info.metric.get(DATA_FIELD.FIELD_VOLUME, 0)
                print(f"K线 {count}: {kl.time} O:{kl.open} H:{kl.high} L:{kl.low} C:{kl.close} V:{volume}")
        print(f"成功获取 {count} 根K线")
        return count > 0
    except Exception as e:
        print(f"港股测试失败: {e}")
        return False

def test_a_stock():
    """测试A股数据获取"""
    print("\n测试A股 600519...")
    try:
        api = CAkshare('600519', k_type=KL_TYPE.K_DAY, begin_date='2025-01-01', end_date='2026-03-05', autype=AUTYPE.QFQ)
        count = 0
        for kl in api.get_kl_data():
            count += 1
            if count <= 3:
                volume = kl.trade_info.metric.get(DATA_FIELD.FIELD_VOLUME, 0)
                print(f"K线 {count}: {kl.time} O:{kl.open} H:{kl.high} L:{kl.low} C:{kl.close} V:{volume}")
        print(f"成功获取 {count} 根K线")
        return count > 0
    except Exception as e:
        print(f"A股测试失败: {e}")
        return False

if __name__ == "__main__":
    print("=== AKShare API 修复测试 v2 ===")
    
    success_count = 0
    total_tests = 3
    
    if test_a_stock():
        success_count += 1
        
    if test_hk_stock():
        success_count += 1
        
    if test_us_stock():
        success_count += 1
    
    print(f"\n=== 测试结果: {success_count}/{total_tests} 通过 ===")
    
    if success_count == total_tests:
        print("✅ 所有测试通过！AKShare API 修复成功。")
    else:
        print("❌ 部分测试失败，请检查错误信息。")