#!/usr/bin/env python3
"""
Phase 1 功能测试脚本
测试DataManager、多级缓存和并发扫描功能
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from DataAPI.DataManager import get_data_manager
from App.ConcurrentScanner import get_concurrent_scanner
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE


def test_data_manager():
    """测试DataManager功能"""
    print("🧪 测试 DataManager...")
    
    data_manager = get_data_manager()
    
    # 测试获取K线数据
    stock_code = "HK.00966"
    end_date = datetime.now().strftime("%Y-%m-%d")
    begin_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    kline_data = data_manager.get_kline_data(
        stock_code, KL_TYPE.K_DAY, begin_date, end_date
    )
    
    print(f"✅ 获取 {stock_code} K线数据: {len(kline_data)} 条记录")
    
    # 测试获取当前价格
    current_price = data_manager.get_current_price(stock_code)
    print(f"✅ 当前价格: {current_price}")
    
    # 测试批量获取
    batch_result = data_manager.batch_get_kline_data(
        ["HK.00966", "HK.00916"], KL_TYPE.K_DAY, begin_date, end_date
    )
    print(f"✅ 批量获取结果: {len(batch_result)} 只股票")


def test_concurrent_scanner():
    """测试并发扫描功能"""
    print("\n🧪 测试 ConcurrentScanner...")
    
    # 创建缠论配置（使用最基本的参数）
    config = CChanConfig({
        "bi_strict": True,
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0
    })
    
    scanner = get_concurrent_scanner(max_workers=4, mode="thread")
    
    # 测试小规模并发扫描
    test_stocks = ["HK.00966", "HK.00916", "HK.00100"]
    
    results = scanner.scan_stocks_concurrent(
        test_stocks, config, KL_TYPE.K_DAY, 30
    )
    
    stats = scanner.get_performance_stats(results)
    
    print(f"✅ 扫描完成: {results['success_count']}/{results['total']} 成功")
    print(f"📊 性能统计: {stats}")


def test_cache_functionality():
    """测试缓存功能"""
    print("\n🧪 测试缓存功能...")
    
    data_manager = get_data_manager()
    
    stock_code = "HK.00966"
    end_date = datetime.now().strftime("%Y-%m-%d")
    begin_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    
    # 第一次调用（应该较慢）
    import time
    start_time = time.time()
    data1 = data_manager.get_kline_data(stock_code, KL_TYPE.K_DAY, begin_date, end_date)
    first_call_time = time.time() - start_time
    
    # 第二次调用（应该很快，因为有缓存）
    start_time = time.time()
    data2 = data_manager.get_kline_data(stock_code, KL_TYPE.K_DAY, begin_date, end_date)
    second_call_time = time.time() - start_time
    
    print(f"✅ 第一次调用耗时: {first_call_time:.3f}秒")
    print(f"✅ 第二次调用耗时: {second_call_time:.3f}秒")
    print(f"✅ 缓存命中率: {'是' if second_call_time < first_call_time * 0.1 else '否'}")
    
    # 验证数据一致性
    assert len(data1) == len(data2), "缓存数据长度不一致"
    assert data1[0].close == data2[0].close, "缓存数据内容不一致"
    print("✅ 缓存数据一致性验证通过")


def main():
    """主测试函数"""
    print("🚀 开始 Phase 1 功能测试...\n")
    
    try:
        test_data_manager()
        test_concurrent_scanner()
        test_cache_functionality()
        
        print("\n🎉 所有测试通过！Phase 1 功能验证完成。")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()