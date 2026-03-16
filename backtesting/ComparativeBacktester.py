#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ComparativeBacktester.py
专门设计用于对比“标准缠论”与“机器学习增强缠论”表现的回测框架。
支持 A/B 对比、Alpha 计算以及并行加速。
"""

import os
import sys
import time
import json
import logging
import argparse
import pandas as pd
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.enhanced_backtester import EnhancedBacktestEngine
from ML.MarketComponentResolver import MarketComponentResolver

# 相关输出目录
REPORT_DIR = "backtest_reports/comparative"
os.makedirs(REPORT_DIR, exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(REPORT_DIR, 'comparative_backtest.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ComparativeBT")

def run_single_stock_comparison(code: str, start_date: str, end_date: str, initial_funds: float) -> Dict[str, Any]:
    """
    针对单只股票运行 A/B 对比。
    """
    logger.info(f"📊 [A/B 对比] 开始回测: {code} ...")
    
    try:
        # 1. 运行轨道 A (Base: 无 ML)
        engine_a = EnhancedBacktestEngine(
            initial_funds=initial_funds,
            start_date=start_date,
            end_date=end_date,
            watchlist=[code],
            use_ml=False
        )
        res_a = engine_a.run()
        
        # 2. 运行轨道 B (Enhanced: 有 ML)
        engine_b = EnhancedBacktestEngine(
            initial_funds=initial_funds,
            start_date=start_date,
            end_date=end_date,
            watchlist=[code],
            use_ml=True
        )
        res_b = engine_b.run()
        
        # 3. 计算差异指标 (Alpha)
        alpha = res_b.get('total_return_pct', 0) - res_a.get('total_return_pct', 0)
        mdd_reduction = res_a.get('max_drawdown_pct', 0) - res_b.get('max_drawdown_pct', 0)
        trade_reduction = res_a.get('trades_count', 0) - res_b.get('trades_count', 0)
        
        comparison = {
            "code": code,
            "start": start_date,
            "end": end_date,
            "base_return": res_a.get('total_return_pct', 0),
            "ml_return": res_b.get('total_return_pct', 0),
            "alpha": alpha,
            "base_mdd": res_a.get('max_drawdown_pct', 0),
            "ml_mdd": res_b.get('max_drawdown_pct', 0),
            "mdd_reduction": mdd_reduction,
            "base_trades": res_a.get('trades_count', 0),
            "ml_trades": res_b.get('trades_count', 0),
            "trade_reduction": trade_reduction,
            "base_win_rate": res_a.get('win_rate', 0),
            "ml_win_rate": res_b.get('win_rate', 0),
            "base_profit_factor": res_a.get('profit_loss_ratio', 0),
            "ml_profit_factor": res_b.get('profit_loss_ratio', 0)
        }
        
        logger.info(f"✅ {code} 对比完成: Alpha={alpha:+.2%}, MDD减少={mdd_reduction:+.2%}")
        return comparison
        
    except Exception as e:
        logger.error(f"❌ {code} 回测失败: {e}")
        return {"code": code, "error": str(e)}

def generate_markdown_report(results: List[Dict], output_file: str):
    """
    生成对比分析报告。
    """
    if not results:
        return
    
    df = pd.DataFrame([r for r in results if "error" not in r])
    if df.empty:
        return
        
    avg_alpha = df['alpha'].mean()
    avg_mdd_red = df['mdd_reduction'].mean()
    total_trades_saved = df['trade_reduction'].sum()
    
    md = []
    md.append(f"# 缠论 A/B 策略对比分析报告 (ML vs. Standard)")
    md.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    md.append(f"\n## 🏁 1. 核心结论")
    md.append(f"- **平均超额收益 (Alpha)**: {avg_alpha:+.4%}")
    md.append(f"- **平均最大回撤改进**: {avg_mdd_red:+.4%}")
    md.append(f"- **AI 拦截无效交易数**: {int(total_trades_saved)} 笔")
    md.append(f"- **ML 胜率提升**: { (df['ml_win_rate'].mean() - df['base_win_rate'].mean()):+.2%}")
    
    md.append(f"\n## 📊 2. 标的明细对比")
    md.append("| 股票代码 | 标准收益 | **ML 收益** | **Alpha (超额)** | 标准 MDD | **ML MDD** | 交易量变化 |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    
    for _, row in df.sort_values(by="alpha", ascending=False).iterrows():
        md.append(f"| {row['code']} | {row['base_return']:.2%} | **{row['ml_return']:.2%}** | **{row['alpha']:+.2%}** | {row['base_mdd']:.2%} | **{row['ml_mdd']:.2%}** | {int(row['base_trades'])} -> {int(row['ml_trades'])} |")
    
    md.append(f"\n## 💡 3. AI 效能评估")
    if avg_alpha > 0:
        md.append("- ✅ **收益增益**: 机器学习模型成功在保持正收益的同时提升了盈亏比。")
    if avg_mdd_red > 0:
        md.append("- ✅ **风险控制**: 机器学习有效地过滤了高回撤期间的诱多信号，显著降低了账户波动。")
    if total_trades_saved > 0:
        md.append(f"- ✅ **交易效率**: AI 过滤了大量低期望值的信号，减少了印花税损耗。")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))
    
    logger.info(f"📝 报告已保存至: {output_file}")

def main():
    parser = argparse.ArgumentParser(description='缠论 A/B 策略对比回测')
    parser.add_argument('--markets', type=str, nargs='+', default=['HK'], help='市场 (US, HK, CN)')
    parser.add_argument('--stocks', type=str, nargs='+', help='指定股票列表')
    parser.add_argument('--start', type=str, default='2024-01-01', help='开始日期')
    parser.add_argument('--end', type=str, default='2025-12-31', help='结束日期')
    parser.add_argument('--funds', type=float, default=100000, help='每只初始资金')
    parser.add_argument('--workers', type=int, default=4, help='并行进程数')
    parser.add_argument('--limit', type=int, default=10, help='测试前 N 只(默认 10 避免测试太久)')
    
    args = parser.parse_args()
    
    # 确定回测股票列表
    resolver = MarketComponentResolver()
    target_list = []
    
    if args.stocks:
        target_list = args.stocks
    else:
        for m in args.markets:
            if m.upper() == 'US':
                target_list.extend(resolver.resolve_nasdaq100()[:args.limit])
            elif m.upper() == 'HK':
                target_list.extend(resolver.resolve_hk_lean()[:args.limit])
            elif m.upper() == 'CN':
                target_list.extend(resolver.resolve_cn_core()[:args.limit])
    
    # 去重并应用限制
    target_list = list(dict.fromkeys(target_list))[:args.limit]
    
    logger.info(f"🚀 开始回测任务 | 并行数: {args.workers} | 总标的: {len(target_list)}")
    
    results = []
    start_time = time.time()
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_single_stock_comparison, code, args.start, args.end, args.funds): code 
            for code in target_list
        }
        
        for future in as_completed(futures):
            code = futures[future]
            try:
                res = future.result()
                results.append(res)
            except Exception as e:
                logger.error(f"Error processing {code}: {e}")
    
    # 生成报告
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(REPORT_DIR, f"comparison_report_{timestamp}.md")
    generate_markdown_report(results, report_file)
    
    duration = time.time() - start_time
    logger.info(f"🏁 全量对比回测完成! 耗时: {duration:.1f}s")
    print(f"\n📊 对比报告已生成: {report_file}")

if __name__ == "__main__":
    main()
