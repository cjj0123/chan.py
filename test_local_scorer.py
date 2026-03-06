#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地评分模块测试脚本
"""

import sys
import os
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Trade.LocalScorer import get_local_scorer

def test_local_scorer():
    """测试本地评分器功能"""
    print("=== 本地评分模块测试 ===")
    
    # 初始化本地评分器
    local_scorer = get_local_scorer()
    print("✓ 成功创建LocalScorer实例")
    
    # 测试1: 模拟一买信号
    print("\n1. 测试一买信号...")
    chan_analysis_1b = {
        'bsp_info': {'type': '1'},
        'is_buy': True,
        'seg_list': [{'direction': -1, 'length': 10, 'slope': -0.05}],
        'macd_info': {'divergence': 0.1, 'hist': -0.02},
        'zs_list': [{'height': 2.0, 'high': 52.0, 'low': 48.0}],
        'current_price': 50.0
    }
    score_1b = local_scorer.calculate_local_score(chan_analysis_1b)
    print(f"一买信号评分: {score_1b}")
    
    # 测试2: 模拟二买信号
    print("\n2. 测试二买信号...")
    chan_analysis_2b = {
        'bsp_info': {'type': '2'},
        'is_buy': True,
        'seg_list': [{'direction': -1, 'length': 8, 'slope': -0.03}],
        'macd_info': {'divergence': 0.08, 'hist': -0.01},
        'zs_list': [{'height': 1.5, 'high': 51.5, 'low': 49.0}],
        'current_price': 50.0
    }
    score_2b = local_scorer.calculate_local_score(chan_analysis_2b)
    print(f"二买信号评分: {score_2b}")
    
    # 测试3: 测试评分阈值判断
    print("\n3. 测试评分阈值判断...")
    should_proceed_1b = local_scorer.should_proceed_to_visual_ai(score_1b)
    should_proceed_2b = local_scorer.should_proceed_to_visual_ai(score_2b)
    should_proceed_low = local_scorer.should_proceed_to_visual_ai(50)
    
    print(f"一买信号({score_1b})是否继续: {should_proceed_1b}")
    print(f"二买信号({score_2b})是否继续: {should_proceed_2b}")
    print(f"低分信号(50)是否继续: {should_proceed_low}")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    test_local_scorer()