#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
性能监控模块测试脚本
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).resolve().parent))

from Monitoring.PerformanceMonitor import get_performance_monitor

def test_performance_monitor():
    """测试性能监控模块"""
    print("🧪 测试性能监控模块...")
    
    # 获取性能监控器实例
    monitor = get_performance_monitor()
    
    # 测试记录扫描性能
    monitor.record_scan_performance(100, 10.0)  # 100只股票，10秒
    print("✅ 记录扫描性能完成")
    
    # 测试记录信号评分
    monitor.record_signal(85.5)
    monitor.record_signal(92.0)
    monitor.record_signal(78.3)
    print("✅ 记录信号评分完成")
    
    # 测试记录交易执行
    monitor.record_execution(True)
    monitor.record_execution(False)
    monitor.record_execution(True)
    print("✅ 记录交易执行完成")
    
    # 测试获取实时指标
    metrics = monitor.get_realtime_metrics()
    print(f"📊 实时指标: {metrics}")
    
    # 测试获取历史性能数据
    historical_data = monitor.get_historical_performance(hours=24)
    print(f"📈 历史数据时间段: {historical_data['period_start']} - {historical_data['period_end']}")
    print(f"   订单数量: {len(historical_data['orders'])}")
    print(f"   信号数量: {len(historical_data['signals'])}")
    
    print("✅ 性能监控模块测试完成！")

if __name__ == "__main__":
    test_performance_monitor()