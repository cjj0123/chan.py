#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理模块测试脚本
"""

import sys
import os
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Trade.RiskManager import RiskManager
from Trade.db_util import CChanDB

def test_risk_manager():
    """测试风险管理器功能"""
    print("=== 风险管理模块测试 ===")
    
    # 初始化数据库和风险管理器
    db = CChanDB("test_risk_manager.db")
    risk_manager = RiskManager("test_risk_manager.db")
    
    # 测试1: 熔断机制
    print("\n1. 测试熔断机制...")
    is_circuit_breaker_active = risk_manager.check_circuit_breaker()
    print(f"熔断状态: {is_circuit_breaker_active}")
    
    # 测试2: 仓位计算
    print("\n2. 测试仓位计算...")
    available_funds = 100000.0
    current_price = 50.0
    signal_score = 85
    position_size = risk_manager.calculate_position_size(
        code="HK.00700",
        available_funds=available_funds,
        current_price=current_price,
        signal_score=signal_score
    )
    print(f"建议仓位: {position_size}股")
    
    # 测试3: 交易频率限制
    print("\n3. 测试交易频率限制...")
    can_trade = risk_manager.can_execute_trade("HK.00700", signal_score)
    print(f"可以交易: {can_trade}")
    
    # 测试4: 记录交易
    print("\n4. 测试记录交易...")
    risk_manager.record_trade("HK.00700", "BUY", 100, 50.0, 85)
    risk_manager.record_trade("HK.00700", "SELL", 100, 55.0, 90, pnl=500.0)
    
    # 测试5: 获取风险状态
    print("\n5. 获取风险状态...")
    risk_status = risk_manager.get_risk_status()
    print(f"风险状态: {risk_status}")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    test_risk_manager()