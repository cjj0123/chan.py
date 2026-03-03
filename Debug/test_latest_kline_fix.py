#!/usr/bin/env python3
"""
测试5分钟K线最新数据问题的修复
"""

import sys
import os
# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from datetime import datetime
from Common.CEnum import KL_TYPE
from kline_raw_cache import kline_raw_cache

def test_latest_kline_cache_key():
    """测试最新K线缓存键生成逻辑"""
    print("=== 测试最新K线缓存键生成逻辑 ===")
    
    code = "HK.00700"
    ktype_5m = KL_TYPE.K_5M
    start_time = "2026-02-01"
    
    # 测试接近5分钟边界的情况
    test_cases = [
        ("2026-03-03 13:43:30", "距离13:45还有90秒，应该使用13:45"),
        ("2026-03-03 13:44:00", "距离13:45还有60秒，应该使用13:45"),
        ("2026-03-03 13:44:30", "距离13:45还有30秒，应该使用13:45"),
        ("2026-03-03 13:44:59", "距离13:45还有1秒，应该使用13:45"),
        ("2026-03-03 13:45:01", "刚过13:45，应该使用13:45"),
        ("2026-03-03 13:46:00", "距离13:50还有4分钟，应该使用13:45"),
        ("2026-03-03 13:48:30", "距离13:50还有90秒，应该使用13:50"),
    ]
    
    for end_time, description in test_cases:
        key = kline_raw_cache._get_cache_key(code, ktype_5m, start_time, end_time)
        print(f"时间: {end_time} - {description}")
        print(f"缓存键: {key}")
        print()
    
    # 测试跨小时情况
    print("=== 测试跨小时情况 ===")
    cross_hour_cases = [
        ("2026-03-03 13:58:30", "距离14:00还有90秒，应该使用14:00"),
        ("2026-03-03 13:59:30", "距离14:00还有30秒，应该使用14:00"),
    ]
    
    for end_time, description in cross_hour_cases:
        key = kline_raw_cache._get_cache_key(code, ktype_5m, start_time, end_time)
        print(f"时间: {end_time} - {description}")
        print(f"缓存键: {key}")
        print()

if __name__ == "__main__":
    test_latest_kline_cache_key()
    print("✅ 测试完成！")