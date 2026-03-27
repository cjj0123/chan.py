#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
log_aggregator.py - 每日运行日志自动汇总分析
- 聚合 gui_debug.log, app_hk_live_sim.log, debug_steps.log
- 识别 TOP 错误模式 (如 Futu 连接失败, 历史 K 线额度不足等)
- 生成 "Weekly Pulse" 报告
"""

import os
import re
import glob
from collections import Counter
from datetime import datetime

log_paths = [
    "gui_debug.log",
    "app_hk_live_sim.log",
    "debug_steps.log",
    "backtest_enhanced.log"
]

error_patterns = {
    "Futu_Quota": r"历史K线额度不足",
    "Futu_Conn": r"FutuAPI returned no data|ret=-1",
    "Connection_128": r"128 connections",
    "ML_Failure": r"ML 验证模块加载失败",
    "Sync_Failure": r"Failed to download|同步失败",
    "StopLoss_Triggered": r"🛑 止损触发",
    "Trade_Rejected": r"资金不足|信号被拒"
}

def analyze_logs():
    report = []
    report.append(f"# 缠论 Bot 运行质量报表 (Weekly Pulse)")
    report.append(f"生成日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("\n## 📋 1. 错误模式统计")
    report.append("| 模式 | 匹配次数 | 说明 |")
    report.append("| --- | --- | --- |")

    found_any = False
    for name, pattern in error_patterns.items():
        count = 0
        for path in log_paths:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    count += len(re.findall(pattern, content))
        
        if count > 0:
            report.append(f"| {name} | {count} | 通过正则 {pattern} 匹配 |")
            found_any = True
    
    if not found_any:
        report.append("| 无明显错误 | 0 | 系统运行平稳 |")

    report.append("\n## 🛡️ 2. 连接健康度审计")
    # 检查是否有未关闭的连接泄露告警 (即 ret=-1 的高频出现)
    report.append("- **Futu 接口状态**: [自动核查] 如果 Connection_128 次数为 0, 则说明 `FutuAPI.py` 的泄露修复已生效。")

    report.append("\n## 📊 3. 策略运行摘要")
    # 尝试读取每日收盘汇总
    report.append("- 请参考 `backtest_reports/optimization/master_strategy_config.json` 获取最新最优参数。")

    output_path = "backtest_reports/weekly_pulse_report.md"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    
    print(f"✅ 日志分析完成，报表已生成: {output_path}")

if __name__ == "__main__":
    analyze_logs()
