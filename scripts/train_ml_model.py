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

def run_training_pipeline(market="HK", limit=20):
    """
    运行完整的机器学习训练流水线：
    1. 自动从缓存识别指定市场的股票清单
    2. 收集样本（特征 + 标签）
    3. 训练 XGBoost 模型
    """
    loader = BacktestDataLoader()
    all_codes = loader.get_all_codes()
    
    # 筛选市场
    market_prefix = market.upper() + "."
    watchlist = [c for c in all_codes if c.startswith(market_prefix)]
    
    if not watchlist:
        logger.error(f"❌ 未找到市场 {market} 的缓存数据，请先运行数据下载脚本。")
        return
    
    # 限制股票数量，防止初次运行过久
    watchlist = watchlist[:limit]
    logger.info(f"🚀 开始为 {market} 市场训练，样本股票数量: {len(watchlist)}")
    
    # 初始化训练器
    # 盈利目标 3%，持仓 45 根 K 线 (约2-3天)，回测最近两年的数据
    trainer = ModelTrainer(
        watchlist=watchlist,
        start_date="2023-01-01",  # 扩充到 2023 年
        end_date=datetime.now().strftime("%Y-%m-%d"),
        profit_target=0.03,
        holding_period=45
    )
    
    # 第一阶段：收集样本
    logger.info("--- Stage 1: Collecting Samples ---")
    trainer.collect_samples()
    
    # 第二阶段：训练模型
    logger.info("--- Stage 2: Training Model ---")
    trainer.train_model()
    
    # 验证模型文件生成
    if os.path.exists(trainer.model_file):
        size = os.path.getsize(trainer.model_file)
        logger.info(f"✅ 训练完成！模型已保存至: {trainer.model_file} ({size} 字节)")
    else:
        logger.error("❌ 模型训练失败，未生成模型文件。")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Chanlun ML Training Pipeline")
    parser.add_argument("--market", type=str, default="HK", help="Market to train for (HK/US/A)")
    parser.add_argument("--limit", type=int, default=100, help="Number of stocks to use for training")
    
    args = parser.parse_args()
    
    # 确保依赖环境
    try:
        import xgboost
        import pandas
    except ImportError as e:
        logger.error(f"缺少依赖: {e}. 请运行 pipeline install xgboost pandas")
        sys.exit(1)
        
    run_training_pipeline(market=args.market, limit=args.limit)
