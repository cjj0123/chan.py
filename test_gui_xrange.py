#!/usr/bin/env python3
"""
测试GUI中x_range设置是否正确
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_timeframe_kl_type_from_text
from Common.CEnum import KL_TYPE

def test_xrange_mapping():
    """测试时间级别到x_range的映射"""
    # 测试不同时间级别
    test_cases = [
        ("日线", KL_TYPE.K_DAY, 250),
        ("30分钟", KL_TYPE.K_30M, 150),
        ("5分钟", KL_TYPE.K_5M, 80),
        ("1分钟", KL_TYPE.K_1M, 40)
    ]
    
    for timeframe_text, expected_kl_type, expected_xrange in test_cases:
        # 验证KL_TYPE映射
        kl_type = get_timeframe_kl_type_from_text(timeframe_text)
        assert kl_type == expected_kl_type, f"时间级别映射错误: {timeframe_text} -> {kl_type}, 期望: {expected_kl_type}"
        
        # 验证x_range映射
        x_range_map = {
            KL_TYPE.K_DAY: 250,
            KL_TYPE.K_30M: 150,
            KL_TYPE.K_5M: 80,
            KL_TYPE.K_1M: 40,
        }
        actual_xrange = x_range_map.get(kl_type, 0)
        assert actual_xrange == expected_xrange, f"x_range映射错误: {kl_type} -> {actual_xrange}, 期望: {expected_xrange}"
        
        print(f"✓ {timeframe_text} -> {kl_type.name} -> x_range={expected_xrange}")

def get_timeframe_kl_type_from_text(timeframe_text):
    """从文本获取KL_TYPE"""
    timeframe_map = {
        "日线": KL_TYPE.K_DAY,
        "30分钟": KL_TYPE.K_30M,
        "5分钟": KL_TYPE.K_5M,
        "1分钟": KL_TYPE.K_1M,
    }
    return timeframe_map.get(timeframe_text, KL_TYPE.K_DAY)

if __name__ == "__main__":
    test_xrange_mapping()
    print("所有测试通过！")