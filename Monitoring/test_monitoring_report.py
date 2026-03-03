#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试监控报告功能
"""

import os
import sys

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Monitoring.metrics import CMetricsCalculator
from Monitoring.reporter import CReporter


def test_metrics_calculator():
    """测试指标计算器"""
    print("测试指标计算器...")
    calculator = CMetricsCalculator()
    
    # 测试性能指标计算
    metrics = calculator.calculate_performance_metrics(days=7)
    print("性能指标:")
    for key, value in metrics.items():
        print(f"  {key}: {value}")
    
    # 测试持仓查询
    positions = calculator.get_current_positions()
    print(f"\n当前持仓数量: {len(positions)}")
    if not positions.empty:
        print("持仓详情:")
        print(positions.head())
    
    # 测试订单查询
    orders = calculator.get_recent_orders(days=1)
    print(f"\n近期订单数量: {len(orders)}")
    if not orders.empty:
        print("订单详情:")
        print(orders.head())
    
    print("指标计算器测试完成!\n")


def test_reporter():
    """测试报告生成器"""
    print("测试报告生成器...")
    reporter = CReporter()
    
    # 测试报告生成（不实际发送邮件）
    calculator = CMetricsCalculator()
    metrics = calculator.calculate_performance_metrics(days=7)
    positions = calculator.get_current_positions()
    orders = calculator.get_recent_orders(days=1)
    
    html_report = reporter._generate_html_report(metrics, positions, orders)
    print(f"HTML报告长度: {len(html_report)} 字符")
    print("报告预览 (前200字符):")
    print(html_report[:200] + "...")
    
    print("报告生成器测试完成!\n")


def test_daily_report():
    """测试每日报告发送（模拟）"""
    print("测试每日报告发送...")
    reporter = CReporter()
    
    # 这里会尝试发送报告，但由于邮件配置可能不完整，可能会跳过发送
    success = reporter.send_daily_report(days=7)
    print(f"每日报告发送结果: {'成功' if success else '失败'}")
    print("每日报告测试完成!\n")


if __name__ == "__main__":
    print("=" * 60)
    print("监控报告功能测试")
    print("=" * 60)
    
    try:
        test_metrics_calculator()
        test_reporter()
        test_daily_report()
        
        print("=" * 60)
        print("所有测试完成!")
        print("=" * 60)
        
    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()