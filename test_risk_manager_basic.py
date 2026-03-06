#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理模块基本测试脚本
"""

import sys
import os
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

def test_basic_functionality():
    """测试基本功能"""
    print("=== 风险管理模块基本测试 ===")
    
    try:
        from Trade.RiskManager import RiskManager
        print("✓ 成功导入RiskManager")
        
        # 创建一个简单的测试实例
        risk_manager = RiskManager()
        print("✓ 成功创建RiskManager实例")
        
        # 测试基本方法
        status = risk_manager.get_risk_status()
        print(f"✓ 获取风险状态成功: {status}")
        
        print("\n=== 基本测试完成 ===")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_basic_functionality()