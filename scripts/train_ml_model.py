#!/usr/bin/env python3
import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import List

# 添加项目根目录到路径
project_root = "/Users/jijunchen/Documents/Projects/Chanlun_Bot"
sys.path.insert(0, project_root)

from ML.ModelTrainer import ModelTrainer
from BacktestDataLoader import BacktestDataLoader

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TrainML")

def run_training_pipeline(market="HK", limit=20, tune=False):
    """
    运行完整的机器学习训练流水线：
    1. 自动从缓存识别指定市场的股票清单
    2. 收集样本（特征 + 标签）
    3. 训练 XGBoost 模型 (可选 Optuna 调优)
    """
    loader = BacktestDataLoader()
    all_codes = loader.get_all_codes()
    
    # 筛选市场
    market_upper = market.upper()
    if market_upper == 'A':
        watchlist = [c for c in all_codes if c.startswith('SH.') or c.startswith('SZ.')]
    elif market_upper == 'GLOBAL':
        watchlist = all_codes
    else:
        watchlist = [c for c in all_codes if c.startswith(market_upper + ".")]
    
    if not watchlist:
        logger.error(f"❌ 未找到市场 {market} 的缓存数据，请先运行数据下载脚本。")
        return
    
    # 限制股票数量，防止初次运行过久
    watchlist = watchlist[:limit]
    logger.info(f"🚀 开始为 {market} 市场训练，样本股票数量: {len(watchlist)}")
    
    # 初始化训练器
    trainer = ModelTrainer(
        watchlist=watchlist,
        start_date="2023-01-01",
        end_date=datetime.now().strftime("%Y-%m-%d"),
        market=market
    )
    
    # 第一阶段：收集样本
    logger.info("--- Stage 1: Collecting Samples ---")
    trainer.collect_samples()
    
    # 第二阶段：训练模型
    logger.info("--- Stage 2: Training Model ---")
    if tune:
        trainer.train_all_with_optuna()
    else:
        trainer.train_all()
    
    logger.info("✅ 训练流水线执行完毕，详情请查看日志输出。")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Chanlun ML Training Pipeline")
    parser.add_argument("--market", type=str, default="HK", help="Market to train for (HK/US/A)")
    parser.add_argument("--limit", type=int, default=100, help="Number of stocks to use for training")
    parser.add_argument("--tune", action="store_true", help="Enable P1 Optuna hyperparameter tuning")
    
    args = parser.parse_args()
    
    # 确保依赖环境
    try:
        import xgboost
        import pandas
    except ImportError as e:
        logger.error(f"缺少依赖: {e}. 请运行 pipeline install xgboost pandas")
        sys.exit(1)
        
    run_training_pipeline(market=args.market, limit=args.limit, tune=args.tune)
