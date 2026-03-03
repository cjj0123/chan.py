#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试带图片附件的邮件发送
模拟实际的股票扫描报告场景
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 加载邮件配置
env_file = Path(__file__).parent / "email_config.env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ 已从 {env_file} 加载邮件配置")

from send_email_report import send_stock_report

# 查找实际的图表文件
charts_dir = Path(__file__).parent / "charts_cn"
chart_files = list(charts_dir.glob("*.png")) if charts_dir.exists() else []

print(f"\n📊 图表目录：{charts_dir}")
print(f"📁 找到的图表文件数量：{len(chart_files)}")

if chart_files:
    # 取前 2 个图表文件
    test_charts = [str(f) for f in chart_files[:2]]
    print(f"📎 测试用图表：{test_charts}")
    
    # 计算总大小
    total_size = sum(os.path.getsize(f) for f in test_charts)
    print(f"📦 图表总大小：{total_size / 1024:.1f} KB")
else:
    print("⚠️ 未找到图表文件，使用测试路径")
    test_charts = []

# 测试场景 1: 带真实图表的邮件
print("\n" + "="*60)
print("测试场景 1: 带真实图表的邮件")
print("="*60)

test_signals = [
    {
        'code': 'SH.603281',
        'stock_name': '源立科技',
        'is_buy': True,
        'bsp_type': 'b1',
        'score': 85,
        'current_price': 100.00,
        'visual_result': {
            'analysis': '30 分钟图显示清晰的底部背驰结构，5 分钟图提供区间套确认，买点质量高。'
        },
        'chart_paths': test_charts
    }
]

try:
    result = send_stock_report(test_signals, test_charts, subject="🧪 带图片测试邮件")
    if result:
        print("✅ 带图片邮件发送成功")
    else:
        print("❌ 带图片邮件发送失败（返回 False）")
except Exception as e:
    print(f"❌ 带图片邮件发送异常：{e}")
    import traceback
    traceback.print_exc()

# 测试场景 2: 模拟多个信号（大量图片）
print("\n" + "="*60)
print("测试场景 2: 模拟多个信号（大量图片）")
print("="*60)

if len(chart_files) >= 6:
    multi_charts = [str(f) for f in chart_files[:6]]
    multi_signals = [
        {
            'code': f'SH.60328{i}',
            'stock_name': f'测试股票{i}',
            'is_buy': i % 2 == 0,
            'bsp_type': 'b1',
            'score': 70 + i * 5,
            'current_price': 100.00 + i,
            'visual_result': {'analysis': f'测试分析{i}'},
            'chart_paths': [multi_charts[i*2], multi_charts[i*2+1]]
        }
        for i in range(3)
    ]
    
    total_size = sum(os.path.getsize(f) for f in multi_charts)
    print(f"📦 多图表总大小：{total_size / 1024:.1f} KB ({total_size / 1024 / 1024:.2f} MB)")
    
    try:
        result = send_stock_report(multi_signals, multi_charts, subject="🧪 多图片测试邮件")
        if result:
            print("✅ 多图片邮件发送成功")
        else:
            print("❌ 多图片邮件发送失败（返回 False）")
    except Exception as e:
        print(f"❌ 多图片邮件发送异常：{e}")
        import traceback
        traceback.print_exc()
else:
    print("⚠️ 图表文件不足 6 个，跳过此测试")

print("\n" + "="*60)
print("测试完成")
print("="*60)
