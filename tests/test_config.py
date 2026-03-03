#!/usr/bin/env python3
"""
测试配置加载
"""
import sys
sys.path.append('.')

from config import TRADING_CONFIG

print(f"TRADING_CONFIG['min_visual_score']: {TRADING_CONFIG['min_visual_score']}")
print(f"Type: {type(TRADING_CONFIG['min_visual_score'])}")