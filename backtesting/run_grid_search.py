#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论策略组合网格搜索寻优控制中心
"""

import os
import sys
import logging
from datetime import datetime

import pandas as pd

# 添加项目根目录到加载路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.enhanced_backtester import EnhancedBacktestEngine, ParameterOptimizer

def run_grid_pipeline(market: str = 'HK'):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("GridRunner")

    # 1. 甄选高样本股票池 (按市场划分)
    WATCHLIST_MAP = {
        'HK': [
            'HK.00700', 'HK.00388', 'HK.01299', 'HK.03690', 'HK.02269',
            'HK.01810', 'HK.09988', 'HK.02318', 'HK.00005', 'HK.01024'
        ],
        'CN': [
            'SZ.000651', 'SZ.000002', 'SH.600036', 'SH.600519', 'SZ.000858',
            'SH.601318', 'SZ.002415', 'SH.600030', 'SZ.300750', 'SH.600900'
        ],
        'US': [
            'US.AAPL', 'US.TSLA', 'US.MSFT', 'US.GOOGL', 'US.AMZN', 
            'US.NVDA', 'US.NFLX', 'US.META', 'US.AMD', 'US.BABA'
        ]
    }

    watchlist = WATCHLIST_MAP.get(market.upper(), WATCHLIST_MAP['HK'])
    logger.info(f"📍 目标市场: {market.upper()} | 选定股票池: {watchlist}")

    # 2. 基础回测配置
    base_config = {
        'initial_funds': 200000,
        'start_date': '2024-01-01',
        'end_date': '2026-03-15',
        'watchlist': watchlist,
        'use_hk_costs': market.upper() == 'HK',
        'use_ml': False
    }

    # 3. 爆破参数网格 (穷尽各种配置组合)
    param_grid = {
        # 允许触发的买卖点类型组合
        'allowed_bsp_types': [
            ['1买'], ['2买'], ['3买'],
            ['1买', '2买'], ['1买', '2买', '3买']
        ],
        'enable_stop_loss': [True, False],
        'atr_multiplier': [1.5, 2.0, 2.5],
        'hard_stop_pct': [0.07, 0.10]
    }

    # 4. 驱动网格爆破的包装函数
    def config_backtest_func(cfg_override):
        engine = EnhancedBacktestEngine(
            initial_funds=cfg_override.get('initial_funds', 200000),
            start_date=cfg_override.get('start_date'),
            end_date=cfg_override.get('end_date'),
            watchlist=cfg_override.get('watchlist'),
            use_hk_costs=cfg_override.get('use_hk_costs', True),
            use_ml=cfg_override.get('use_ml', False)
        )
        # engine.run 支持 config_override
        results = engine.run(config_override=cfg_override)
        return results

    # 5. 启动网格搜索
    optimizer = ParameterOptimizer(base_config)
    results_df = optimizer.grid_search(
        param_grid=param_grid,
        backtest_func=config_backtest_func,
        metric='total_return_pct'
    )

    # 6. 保存并输出对比结果
    output_dir = f"backtest_reports/grid_search_{market.lower()}"
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = os.path.join(output_dir, f"grid_results_{timestamp}.csv")
    results_df.to_csv(csv_path, index=False)
    logger.info(f"✅ 网格测试汇总结果已保存到：{csv_path}")

    best_params = optimizer.get_best_params(results_df)
    logger.info(f"🏆 {market.upper()} 市场 最优配置：\n{best_params}")

    return results_df

if __name__ == '__main__':
    # 遍历三个市场跑测网格
    for mk in ['HK', 'CN', 'US']:
        print(f"\n🌍 ================== 启动 {mk} 市场网格爆破 ==================\n")
        try:
            run_grid_pipeline(market=mk)
        except Exception as e:
            print(f"❌ {mk} 市场触发异常: {e}")

