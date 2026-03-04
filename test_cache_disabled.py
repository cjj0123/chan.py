#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试缓存禁用功能
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

def test_cache_disabled():
    """测试缓存是否被正确禁用"""
    print("🔍 测试缓存禁用功能...")
    
    # 导入缓存模块
    from kline_raw_cache import kline_raw_cache
    
    print(f"📊 当前缓存持续时间: {kline_raw_cache.cache_duration} 秒")
    
    # 检查是否为0（表示禁用）
    if kline_raw_cache.cache_duration == 0:
        print("✅ 缓存已成功禁用")
        return True
    else:
        print(f"❌ 缓存未禁用，当前设置为 {kline_raw_cache.cache_duration} 秒")
        return False

def test_hk_trading_cache_setting():
    """测试港股交易系统中的缓存设置"""
    print("\n🔍 测试港股交易系统缓存设置...")
    
    try:
        from futu_hk_visual_trading_fixed import FutuHKVisualTrading
        print("✅ 成功导入FutuHKVisualTrading类")
        
        # 创建实例（不实际连接）
        # 我们只是想确认初始化代码中包含了禁用缓存的设置
        import inspect
        source = inspect.getsource(FutuHKVisualTrading.__init__)
        
        if "kline_raw_cache.cache_duration = 0" in source:
            print("✅ 在FutuHKVisualTrading.__init__中找到缓存禁用代码")
        else:
            print("❌ 在FutuHKVisualTrading.__init__中未找到缓存禁用代码")
            return False
            
        if "krc_module.kline_raw_cache.cache_duration = 0" in source:
            print("✅ 在FutuHKVisualTrading.__init__中找到全局缓存禁用代码")
        else:
            print("❌ 在FutuHKVisualTrading.__init__中未找到全局缓存禁用代码")
            return False
        
        return True
    except Exception as e:
        print(f"❌ 测试港股交易系统时出错: {e}")
        return False

def test_api_cache_bypass():
    """测试API层是否能正确绕过缓存"""
    print("\n🔍 测试API层缓存绕过功能...")
    
    try:
        import inspect
        import DataAPI.FutuAPICached
        source = inspect.getsource(DataAPI.FutuAPICached.CFutuAPICached.get_kl_data)
        
        if "cache_duration == 0" in source and "缓存已禁用" in source:
            print("✅ 在CFutuAPICached.get_kl_data中找到缓存禁用检查代码")
            return True
        else:
            print("❌ 在CFutuAPICached.get_kl_data中未找到缓存禁用检查代码")
            return False
    except Exception as e:
        print(f"❌ 测试API缓存绕过时出错: {e}")
        return False

if __name__ == "__main__":
    print("="*50)
    print("缓存禁用功能测试")
    print("="*50)
    
    results = []
    results.append(test_cache_disabled())
    results.append(test_hk_trading_cache_setting())
    results.append(test_api_cache_bypass())
    
    print("\n" + "="*50)
    print("测试总结:")
    passed = sum(results)
    total = len(results)
    print(f"通过: {passed}/{total}")
    
    if all(results):
        print("🎉 所有测试通过！缓存已成功禁用。")
        sys.exit(0)
    else:
        print("❌ 部分测试失败，请检查代码。")
        sys.exit(1)