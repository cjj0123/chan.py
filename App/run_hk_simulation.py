#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import asyncio
from PyQt6.QtWidgets import QApplication


# 将项目根目录加入模块搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from App.HKTradingController import HKTradingController
from config import TRADING_CONFIG

def main():
    # 必须初始化 QApplication 支撑 QObject 定时器和信号板
    app = QApplication(sys.argv)
    
    print("==================================================")
    print("🚀 启动港股模拟盘全自动扫描与交易服务 (Headless)")
    print("==================================================")
    print(f"🔹 模式: SIMULATION (Dry Run = {TRADING_CONFIG.get('hk_dry_run')})")
    print(f"🔹 止损开关: {TRADING_CONFIG.get('enable_stop_loss')}")
    print(f"🔹 5M 校验: {TRADING_CONFIG.get('enable_resonance_5m')}")
    print(f"🔹 监控板块: {TRADING_CONFIG.get('hk_watchlist_group')}")
    print("==================================================\n")
    
    controller = HKTradingController()
    
    # run_scan_and_trade 会开启 asyncio 事件循环并无限 poll
    controller.run_scan_and_trade()

if __name__ == "__main__":
    main()
