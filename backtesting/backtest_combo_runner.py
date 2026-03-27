#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Matrix comparison runner
"""

import os
import sys
import pandas as pd
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.UniversalBacktester import UniversalBacktester

def run_matrix():
    watchlist = ["HK.00700", "HK.00836"] # 示例标的
    configs = [
        {'name': '1. 基准配置 (无ML, 无保护)', 'use_ml': False, 'atr_stop_trail': 2.5, 'enable_quick_retreat': False, 'sell_freq': None},
        {'name': '2. AI 视觉防线 (仅ML过滤)', 'use_ml': True, 'atr_stop_trail': 2.5, 'enable_quick_retreat': False, 'sell_freq': None},
        {'name': '3. ML + 1.0 ATR 快速回撤', 'use_ml': True, 'atr_stop_trail': 2.5, 'enable_quick_retreat': True, 'sell_freq': None},
        {'name': '4. 终极逃顶流 (ML + 5M 缠论卖点)', 'use_ml': True, 'atr_stop_trail': 2.5, 'enable_quick_retreat': False, 'sell_freq': '5M'},
        {'name': '5. 极速逃顶流 (ML + 1M 缠论卖点)', 'use_ml': True, 'atr_stop_trail': 2.5, 'enable_quick_retreat': False, 'sell_freq': '1M'},
    ]

    report_lines = ["# 策略多维度回测对比矩阵\n"]
    report_lines.append("| 策略组别 | 期末权益 | 收益率% | 交易笔数 | 止损/逃顶触发次数 |")
    report_lines.append("|---|---|---|---|---|")

    for cfg in configs:
        print(f"🚀 运行 {cfg['name']}...")
        tester = UniversalBacktester(
            market='HK', start_date='2025-01-01', end_date='2025-05-30', watchlist=watchlist,
            use_ml=cfg['use_ml'], atr_stop_trail=cfg['atr_stop_trail'],
            enable_quick_retreat=cfg['enable_quick_retreat'], sell_freq=cfg['sell_freq']
        )
        res = tester.run()
        
        # 统计止损次数
        trades = tester.broker.trades
        stops_cnt = len([t for t in trades if t.get('action') == 'SELL_STOP'])
        
        report_lines.append(f"| {cfg['name']} | {res['final_portfolio_value']:.2f} | {res['total_return_pct']*100:.2f}% | {len(trades)} | {stops_cnt} |")

    with open('backtest_reports/matrix_comparison_report.md', 'w') as f:
        f.write("\n".join(report_lines))

    print("✅ 矩阵报告已生成于 backtest_reports/matrix_comparison_report.md")

if __name__ == '__main__':
    os.makedirs('backtest_reports', exist_ok=True)
    run_matrix()
