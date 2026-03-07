#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 HKTradingController 的修复情况
"""

import sys
import os
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from App.HKTradingController import HKTradingController

def test_controller_initialization():
    """测试控制器初始化"""
    try:
        controller = HKTradingController()
        print("✅ HKTradingController 初始化成功")
        return True
    except Exception as e:
        print(f"❌ HKTradingController 初始化失败: {e}")
        return False

def test_method_signatures():
    """测试方法签名和返回值"""
    try:
        controller = HKTradingController()
        
        # 测试 get_available_funds
        funds = controller.get_available_funds()
        print(f"✅ get_available_funds 返回: {funds} (类型: {type(funds)})")
        
        # 测试 get_watchlist_codes
        watchlist = controller.get_watchlist_codes()
        print(f"✅ get_watchlist_codes 返回: {len(watchlist)} 个股票 (类型: {type(watchlist)})")
        
        # 测试 _execute_trades 方法签名
        import inspect
        sig = inspect.signature(controller._execute_trades)
        print(f"✅ _execute_trades 签名: {sig}")
        
        # 检查返回值数量
        result = controller._execute_trades([], 100000.0)
        print(f"✅ _execute_trades 返回值数量: {len(result)}")
        print(f"✅ _execute_trades 返回值: {result}")
        
        return True
    except Exception as e:
        print(f"❌ 方法测试失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试 HKTradingController 修复情况...")
    
    if test_controller_initialization():
        if test_method_signatures():
            print("\n✅ 所有测试通过！修复成功！")
        else:
            print("\n❌ 方法测试失败")
    else:
        print("\n❌ 控制器初始化失败")