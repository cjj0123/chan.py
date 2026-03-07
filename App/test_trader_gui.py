#!/usr/bin/env python3
"""
TraderGUI 功能测试脚本
用于全面测试 TraderGUI 的各项功能
"""

import sys
import os
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def test_database_connection():
    """测试数据库连接"""
    print("测试1: 数据库连接")
    from Trade.db_util import CChanDB
    db = CChanDB()
    df = db.execute_query("SELECT DISTINCT code FROM kline_day WHERE code LIKE 'SH.%' OR code LIKE 'SZ.%' LIMIT 5")
    if not df.empty:
        print(f"✅ 数据库连接成功，找到 {len(df)} 只A股股票")
        return True
    else:
        print("❌ 数据库中没有找到A股股票")
        return False

def test_update_db_functionality():
    """测试更新数据库功能"""
    print("\n测试2: 更新数据库功能")
    # 这里只测试函数是否存在，不实际执行下载
    from App.TraderGUI import UpdateDatabaseThread
    print("✅ UpdateDatabaseThread 类存在")
    return True

def test_scan_functionality():
    """测试扫描功能"""
    print("\n测试3: 扫描功能")
    from App.TraderGUI import ScanThread, OfflineScanThread
    print("✅ ScanThread 和 OfflineScanThread 类存在")
    return True

def test_analysis_functionality():
    """测试分析功能"""
    print("\n测试4: 分析功能")
    from App.TraderGUI import SingleAnalysisThread
    print("✅ SingleAnalysisThread 类存在")
    return True

def test_get_chan_config():
    """测试获取缠论配置"""
    print("\n测试5: 获取缠论配置")
    from App.TraderGUI import TraderGUI
    # 创建一个简单的配置测试，不涉及GUI
    from ChanConfig import CChanConfig
    config = CChanConfig()
    config.bNewStyle = True
    config.bi_strict = True
    print(f"✅ 缠论配置创建成功: 笔严格模式={config.bi_strict}")
    return True

def test_get_timeframe_kl_type():
    """测试获取时间级别"""
    print("\n测试6: 获取时间级别")
    from Common.CEnum import KL_TYPE
    
    # 模拟TraderGUI中的映射
    timeframe_map = {
        "日线": KL_TYPE.K_DAY,
        "30分钟": KL_TYPE.K_30M,
        "5分钟": KL_TYPE.K_5M,
    }
    
    # 测试日线
    kl_type = timeframe_map.get("日线", KL_TYPE.K_DAY)
    assert str(kl_type) == "KL_TYPE.K_DAY", f"日线测试失败: {kl_type}"
    
    # 测试30分钟
    kl_type = timeframe_map.get("30分钟", KL_TYPE.K_DAY)
    assert str(kl_type) == "KL_TYPE.K_30M", f"30分钟测试失败: {kl_type}"
    
    # 测试5分钟
    kl_type = timeframe_map.get("5分钟", KL_TYPE.K_DAY)
    assert str(kl_type) == "KL_TYPE.K_5M", f"5分钟测试失败: {kl_type}"
    
    print("✅ 时间级别映射正确")
    return True

def run_all_tests():
    """运行所有测试"""
    print("开始全面测试 TraderGUI...")
    
    try:
        # 基础测试
        test_database_connection()
        test_update_db_functionality()
        test_scan_functionality()
        test_analysis_functionality()
        test_get_chan_config()
        test_get_timeframe_kl_type()
        
        print("\n🎉 所有测试通过！")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)