#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BacktestOptimizationSuite.py - 多市场策略参数智能寻优
- 覆盖 CN/HK/US 三大市场
- 自动寻找最佳 ATR 倍数与信号组合 (1buy, 2buy, 3buy, 1p, 2p)
- 以 收益风险比 (Profit/MaxDrawdown) 为核心优化目标
"""

import os
import sys
import json
import logging
import argparse
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.enhanced_backtester import EnhancedBacktestEngine, ParameterOptimizer
from DataAPI.FutuAPI import CFutuAPI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("OptimizationSuite")

# 三大市场基准测试股 (ETF 或 高流动性大盘股)
MARKET_BENCHMARKS = {
    'CN': ['SH.510300', 'SZ.159915', 'SH.601318', 'SZ.000858'],  # 沪深300, 创业板, 平安, 五粮液
    'HK': ['HK.00700', 'HK.02800', 'HK.03690', 'HK.09988'],       # 腾讯, 盈富基金, 美团, 阿里
    'US': ['US.AAPL', 'US.TSLA', 'US.NVDA', 'US.QQQ']             # 苹果, 特斯拉, 英伟达, 纳指100
}

# 待测试的信号组合 (bs_type) - 必须遵循 ['1', '2', '3a', '2s', '1p', '3b'] 规范
SIGNAL_COMBINATIONS = [
    '1,2,3a',                   # 标准 123 类买点
    '1,1p,2,2s,3a,3b',          # 全量买点 (包含盘整与次生)
    '1,1p',                      # 仅限 1 类及其盘整 (保守)
    '2,2s,3a,3b',               # 过滤 1 类 (倾向于中段入场)
    '1,2,3a,1p'                 # 标准 + 1p
]

# 待测试的 ATR 倍数
ATR_MULTIPLIERS = [1.5, 2.0, 2.5, 3.0]

class StrategyOptimizer:
    def __init__(self, start_date=None, end_date=None):
        self.start_date = start_date or (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        self.end_date = end_date or datetime.now().strftime('%Y-%m-%d')
        self.results_dir = "backtest_reports/optimization"
        os.makedirs(self.results_dir, exist_ok=True)

    def run_market_optimization(self, market: str):
        """为指定市场运行参数寻优"""
        market = market.upper()
        logger.info(f"🚀 开始为 {market} 市场寻找最优策略参数...")
        
        watchlist = MARKET_BENCHMARKS.get(market, [])
        if not watchlist:
            logger.error(f"❌ 未定义市场 {market} 的基准股票列表")
            return

        # 基础引擎配置
        base_engine_config = {
            'initial_funds': 200000.0,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'watchlist': watchlist,
            'market': market,
            'use_precise_costs': True,
            'use_ml': True
        }

        # 参数网格
        param_grid = {
            'bs_type': SIGNAL_COMBINATIONS,
            'atr_multiplier': ATR_MULTIPLIERS
        }

        # 实例化增强引擎
        engine = EnhancedBacktestEngine(**base_engine_config)
        
        # 定义回测执行逻辑
        def backtest_func(config_item):
            # 将 config_item 中的参数应用到回测运行中
            # Note: EnhancedBacktestEngine.run 接收 config_override
            res = engine.run(config_override=config_item)
            # 计算 收益回撤比 作为核心评分指标 (Calmar Ratio 变体)
            profit = res.get('total_return_pct', 0)
            max_dd = abs(res.get('max_drawdown_pct', 0.0001))
            score = profit / max_dd
            return {
                'total_return_pct': profit,
                'max_drawdown_pct': max_dd,
                'calmar_ratio': score,
                'trades_count': res.get('trades_count', 0),
                'win_rate': res.get('win_rate', 0)
            }

        # 运行优化器
        optimizer = ParameterOptimizer(base_config={'bs_type': '1buy,2buy,3buy', 'atr_multiplier': 2.5})
        results_df = optimizer.grid_search(param_grid, backtest_func, metric='calmar_ratio')

        # 保存并汇报结果
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        result_file = os.path.join(self.results_dir, f"best_params_{market}_{timestamp}.csv")
        results_df.to_csv(result_file, index=False)
        
        best_params = results_df.iloc[0].to_dict()
        logger.info(f"✅ {market} 寻优完成! 最优参数组合:")
        logger.info(f"   - 信号组: {best_params['bs_type']}")
        logger.info(f"   - ATR倍数: {best_params['atr_multiplier']}")
        logger.info(f"   - 风险盈亏比: {best_params['calmar_ratio']:.2f}")
        logger.info(f"   - 总收益: {best_params['total_return_pct']*100:.2f}%")
        
        return best_params

    def run_all(self):
        """全市场寻优"""
        all_results = {}
        for market in ['CN', 'HK', 'US']:
            try:
                best = self.run_market_optimization(market)
                all_results[market] = best
            except Exception as e:
                logger.error(f"❌ {market} 寻优崩溃: {e}")
            finally:
                # 释放 API 资源
                CFutuAPI.close_all()
        
        # 写入持久化成果
        summary_file = os.path.join(self.results_dir, "master_strategy_config.json")
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, indent=4, ensure_ascii=False)
        
        logger.info(f"🎉 全市场寻优结束。主配置已更新：{summary_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="缠论策略自动化参数寻优套件")
    parser.add_argument("--market", type=str, default="all", help="市场 (CN/HK/US/all)")
    parser.add_argument("--days", type=int, default=365, help="回测天数")
    args = parser.parse_args()

    start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
    suite = StrategyOptimizer(start_date=start_date)
    
    if args.market.lower() == "all":
        suite.run_all()
    else:
        suite.run_market_optimization(args.market.upper())
        CFutuAPI.close_all()
