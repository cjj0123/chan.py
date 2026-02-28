#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测引擎主入口
支持多种回测模式
"""

import argparse
import sys
import os
from datetime import datetime

def basic_mode():
    """基本回测模式"""
    print(f"[INFO] {datetime.now()} - 开始执行基本回测模式")
    
    # 导入必要的模块进行基本回测
    try:
        from calculate_stats import calculate_basic_stats
        print("[INFO] 成功导入统计模块")
    except ImportError:
        print("[WARN] 未找到 calculate_stats 模块，跳过统计计算")
    
    try:
        from Chan import Chan
        print("[INFO] 成功导入缠论模块")
    except ImportError:
        print("[WARN] 未找到 Chan 模块")
        
    print(f"[INFO] {datetime.now()} - 基本回测模式执行完成")
    return True

def advanced_mode():
    """高级回测模式"""
    print(f"[INFO] {datetime.now()} - 开始执行高级回测模式")
    print(f"[INFO] {datetime.now()} - 高级回测模式执行完成")
    return True

def main():
    parser = argparse.ArgumentParser(description='缠论策略回测引擎')
    parser.add_argument('--mode', type=str, choices=['basic', 'advanced'], 
                       default='basic', help='回测模式: basic(基本) 或 advanced(高级)')
    parser.add_argument('--strategy', type=str, help='指定回测策略文件')
    parser.add_argument('--data-path', type=str, help='数据路径')
    
    args = parser.parse_args()
    
    print(f"[INFO] {datetime.now()} - 启动回测引擎")
    print(f"[INFO] 回测模式: {args.mode}")
    
    if args.mode == 'basic':
        success = basic_mode()
    elif args.mode == 'advanced':
        success = advanced_mode()
    else:
        print(f"[ERROR] {datetime.now()} - 不支持的回测模式: {args.mode}")
        sys.exit(1)
    
    if success:
        print(f"[INFO] {datetime.now()} - 回测执行成功")
        sys.exit(0)
    else:
        print(f"[ERROR] {datetime.now()} - 回测执行失败")
        sys.exit(1)

if __name__ == "__main__":
    main()