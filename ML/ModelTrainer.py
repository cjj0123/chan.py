import os
import sys
import json
import logging
import argparse
from typing import Dict, Any, List

import pandas as pd
try:
    import xgboost as xgb
except ImportError:
    xgb = None

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Chan import CChan
from ChanConfig import CChanConfig
from ML.FeatureExtractor import FeatureExtractor
from BacktestDataLoader import BacktestDataLoader

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


class ModelTrainer:
    """
    通过历史回测收集信号特征，并训练 XGBoost 二分类模型。
    Label 规则：信号发出后的 N 根 K 线内，最高价达到过目标涨幅 (如 3%) 视为 1，否则视为 0。
    """
    def __init__(self, 
                 watchlist: List[str] = ["HK.00700"], 
                 start_date: str = "2024-01-01", 
                 end_date: str = "2025-12-31",
                 profit_target: float = 0.03,
                 holding_period: int = 15):
        self.watchlist = watchlist
        self.start_date = start_date
        self.end_date = end_date
        self.profit_target = profit_target
        self.holding_period = holding_period
        
        self.loader = BacktestDataLoader()
        self.extractor = FeatureExtractor()
        
        self.data_dir = "stock_cache/ml_data"
        os.makedirs(self.data_dir, exist_ok=True)
        self.libsvm_file = os.path.join(self.data_dir, "train_features.libsvm")
        self.meta_file = os.path.join(self.data_dir, "feature_meta.json")
        self.model_file = os.path.join(self.data_dir, "xgboost_model.json")
        
        self.chan_config = CChanConfig({
            "trigger_step": True,
            "bi_strict": True,
            "bs_type": '1,2,3a,1p,2s,3b',
            "print_warning": False,
        })

    def collect_samples(self):
        """收集历史买点特征作为样本集"""
        if xgb is None:
            logger.error("未安装 xgboost，无法收集并训练模型。运行 `pip install xgboost`。")
            return

        logger.info(f"开始为 {len(self.watchlist)} 只股票收集买点样本...")
        bsp_samples = []
        feature_meta = {}

        for code in self.watchlist:
            # 获取股票历史数据
            try:
                klines = self.loader.get_stock_data(code, '30M', self.start_date, self.end_date)
            except Exception as e:
                logger.error(f"无法获取 {code} 数据: {e}")
                continue
                
            if klines is None or klines.empty:
                logger.warning(f"跳过 {code}：获取的数据为空")
                continue
                
            logger.info(f"正在扫描 {code} 的 {len(klines)} 根 K 线寻找买点并评估...")
            
            # 使用 step_load 以便获取实时的特征
            chan = CChan(code=code, data_src="CUSTOM", config=self.chan_config)
            klu_dict_list = klines.to_dict('records')
            
            # 一边计算缠论，一边记录买点和未来的 K 线以便打标签
            for i, row in enumerate(klu_dict_list):
                try:
                    chan.trigger_load(row)
                except Exception as e:
                    continue
                
                # 获取最新一根K线的缠论计算快照
                # 判断在当前时刻是否刚出现了新的买点
                bsp_list = chan.get_bsp()
                if not bsp_list:
                    continue
                    
                last_bsp = bsp_list[-1]
                # 确保是买点而且是刚刚触发的！
                klc_idx = last_bsp.klu.klc.idx
                current_klc_idx = chan[0][-1].idx
                
                # 如果这个买点就是在最近的1-2根K线确认的
                if last_bsp.is_buy and (current_klc_idx - klc_idx) == 1:
                    features = self.extractor.extract_bsp_features(chan, last_bsp)
                    
                    # 偷看未来 N 根K线，以判断是否盈利
                    future_klines = klu_dict_list[i+1 : i+1+self.holding_period]
                    if not future_klines:
                        continue
                        
                    buy_price = row['close']
                    target_price = buy_price * (1 + self.profit_target)
                    hit_target = False
                    
                    for fkl in future_klines:
                        if fkl['high'] >= target_price:
                            hit_target = True
                            break
                    
                    label = 1 if hit_target else 0
                    
                    # 转换为 libsvm 格式
                    libsvm_str = self.extractor.features_to_libsvm(features, label, feature_meta)
                    bsp_samples.append(libsvm_str)
                    
        # 保存特征字典映射
        with open(self.meta_file, 'w', encoding='utf-8') as f:
            json.dump(feature_meta, f, indent=4)
            
        # 保存样本到 libsvm 文件
        with open(self.libsvm_file, 'w', encoding='utf-8') as f:
            for s in bsp_samples:
                f.write(s + "\n")
                
        logger.info(f"✅ 样本收集完成。共提取了 {len(bsp_samples)} 个买点样本。Meta 保存在 {self.meta_file}")
        
    def train_model(self):
        """训练 XGBoost 模型"""
        if xgb is None:
            return
            
        if not os.path.exists(self.libsvm_file) or os.path.getsize(self.libsvm_file) == 0:
            logger.error("缺少训练样本 libsvm 文件！")
            return
            
        logger.info("开始训练 XGBoost 模型...")
        dtrain = xgb.DMatrix(f"{self.libsvm_file}?format=libsvm")
        
        params = {
            'max_depth': 3,
            'eta': 0.1,
            'objective': 'binary:logistic',
            'eval_metric': 'auc'
        }
        
        model = xgb.train(
            params,
            dtrain=dtrain,
            num_boost_round=50,
            verbose_eval=True
        )
        
        model.save_model(self.model_file)
        logger.info(f"🎉 XGBoost 模型训练完毕并保存至 {self.model_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成机器学习样本并训练验证模型")
    parser.add_argument("--collect", action="store_true", help="收集数据")
    parser.add_argument("--train", action="store_true", help="训练模型")
    
    args = parser.parse_args()
    
    trainer = ModelTrainer()
    if args.collect:
        trainer.collect_samples()
    if args.train:
        trainer.train_model()
    if not args.collect and not args.train:
        logger.info("未指定动作。请使用 --collect 或 --train")
