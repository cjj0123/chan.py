#!/usr/bin/env python3
"""
测试缓存修复功能
"""

import sys
import os
# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from datetime import datetime
from Common.CEnum import KL_TYPE
from kline_raw_cache import kline_raw_cache

def test_cache_key_generation():
    """测试缓存键生成逻辑"""
    print("=== 测试缓存键生成逻辑 ===")
    
    # 测试5分钟K线
    code = "HK.00700"
    ktype_5m = KL_TYPE.K_5M
    start_time = "2026-02-01"
    end_time_1 = "2026-03-03 13:45:23"
    end_time_2 = "2026-03-03 13:45:45"
    
    key1 = kline_raw_cache._get_cache_key(code, ktype_5m, start_time, end_time_1)
    key2 = kline_raw_cache._get_cache_key(code, ktype_5m, start_time, end_time_2)
    
    print(f"5分钟K线 - 时间1: {end_time_1}")
    print(f"5分钟K线 - 时间2: {end_time_2}")
    print(f"5分钟K线 - 缓存键1: {key1}")
    print(f"5分钟K线 - 缓存键2: {key2}")
    print(f"5分钟K线 - 键是否相同: {key1 == key2}")
    
    # 测试30分钟K线
    ktype_30m = KL_TYPE.K_30M
    end_time_3 = "2026-03-03 13:45:23"
    end_time_4 = "2026-03-03 13:45:45"
    
    key3 = kline_raw_cache._get_cache_key(code, ktype_30m, start_time, end_time_3)
    key4 = kline_raw_cache._get_cache_key(code, ktype_30m, start_time, end_time_4)
    
    print(f"\n30分钟K线 - 时间1: {end_time_3}")
    print(f"30分钟K线 - 时间2: {end_time_4}")
    print(f"30分钟K线 - 缓存键1: {key3}")
    print(f"30分钟K线 - 缓存键2: {key4}")
    print(f"30分钟K线 - 键是否相同: {key3 == key4}")
    
    # 测试跨边界情况
    end_time_5 = "2026-03-03 13:29:59"  # 30分钟边界前
    end_time_6 = "2026-03-03 13:30:01"  # 30分钟边界后
    
    key5 = kline_raw_cache._get_cache_key(code, ktype_30m, start_time, end_time_5)
    key6 = kline_raw_cache._get_cache_key(code, ktype_30m, start_time, end_time_6)
    
    print(f"\n30分钟K线 - 边界测试时间1: {end_time_5}")
    print(f"30分钟K线 - 边界测试时间2: {end_time_6}")
    print(f"30分钟K线 - 缓存键1: {key5}")
    print(f"30分钟K线 - 缓存键2: {key6}")
    print(f"30分钟K线 - 键是否相同: {key5 == key6}")

def test_cchan_integration():
    """测试与CChan的集成"""
    print("\n=== 测试CChan集成 ===")
    
    try:
        from Chan import CChan
        from ChanConfig import CChanConfig
        from Common.CEnum import KL_TYPE, DATA_SRC
        
        # 使用默认配置
        chan_config = CChanConfig({})
        
        end_time = datetime.now()
        from datetime import timedelta
        start_time = end_time - timedelta(days=30)
        
        print(f"创建CChan实例...")
        chan_multi_level = CChan(
            code="HK.00700",
            begin_time=start_time.strftime("%Y-%m-%d"),
            end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
            data_src=DATA_SRC.FUTU,
            lv_list=[KL_TYPE.K_30M, KL_TYPE.K_5M],
            config=chan_config
        )
        
        print(f"原始级别列表: {[lv.name for lv in chan_multi_level.lv_list]}")
        
        # 检查每个级别的K线数量
        for lv in chan_multi_level.lv_list:
            kline_count = 0
            for _ in chan_multi_level[lv].klu_iter():
                kline_count += 1
            print(f"{lv.name}: {kline_count} 根K线")
            
        print("✅ CChan集成测试成功！")
        return True
        
    except Exception as e:
        print(f"❌ CChan集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_cache_key_generation()
    success = test_cchan_integration()
    
    if success:
        print("\n🎉 所有测试通过！缓存问题已修复。")
    else:
        print("\n❌ 测试失败，请检查错误信息。")