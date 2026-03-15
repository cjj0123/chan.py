import os
import sys
import json
import logging
import argparse
from typing import Dict, Any, List, Tuple

import pandas as pd
import numpy as np

try:
    import xgboost as xgb
except ImportError:
    xgb = None

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset
except ImportError:
    torch = None

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Chan import CChan
from ChanConfig import CChanConfig
from ML.FeatureExtractor import FeatureExtractor
from BacktestDataLoader import BacktestDataLoader
from Common.CEnum import KL_TYPE
from ML.MarketComponentResolver import MarketComponentResolver

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Model Definitions ---
if torch is not None:
    class MLPModel(nn.Module):
        def __init__(self, input_size):
            super(MLPModel, self).__init__()
            self.net = nn.Sequential(
                nn.Linear(input_size, 64),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
                nn.Sigmoid()
            )

        def forward(self, x):
            return self.net(x)
else:
    class MLPModel:
        def __init__(self, *args, **kwargs):
            raise ImportError("PyTorch is not installed. MLPModel is unavailable.")

# --- Trainer Class ---

class ModelTrainer:
    """
    模型训练器：支持多种模型 (XGBoost, LightGBM, MLP) 和多维度标签。
    支持全球市场样本采集与分片训练。
    """
    def __init__(self, 
                 watchlist: List[str] = None, 
                 start_date: str = "2021-01-01", 
                 end_date: str = "2025-12-31",
                 market: str = None):
        # 默认使用成分股解析器
        self.resolver = MarketComponentResolver()
        if watchlist is None:
            logger.info("📡 未指定观察列表，正在解析全球主要成分股...")
            all_targets = self.resolver.get_all_training_targets()
            self.watchlist = []
            for m, stocks in all_targets.items():
                self.watchlist.extend(stocks)
            logger.info(f"✅ 解析完成，共计 {len(self.watchlist)} 只目标股票")
        else:
            self.watchlist = watchlist
            
        self.start_date = start_date
        self.end_date = end_date
        self.market = market  # 市场标识，用于分片存储
        
        self.loader = BacktestDataLoader()
        self.extractor = FeatureExtractor()
        
        # P0: 市场专属模型分片 - 按市场隔离输出目录
        if market and market.upper() not in ('GLOBAL', ''):
            self.data_dir = os.path.join("stock_cache/ml_data", market.upper())
        else:
            self.data_dir = "stock_cache/ml_data"
        os.makedirs(self.data_dir, exist_ok=True)
        self.train_data_file = os.path.join(self.data_dir, "train_samples.csv")
        self.meta_file = os.path.join(self.data_dir, "feature_meta.json")
        self.model_prefix = os.path.join(self.data_dir, "model_")
        
        self.chan_config = CChanConfig({
            "trigger_step": True,
            "bi_strict": True,
            "bs_type": '1,2,3a,1p,2s,3b',
            "print_warning": False,
        })

    def collect_samples(self, target_watchlist: List[str] = None, start_date: str = None, end_date: str = None, freq: str = '30M'):
        """收集指定列表或默认列表的买点样本"""
        coins = target_watchlist if target_watchlist else self.watchlist
        s_date = start_date if start_date else self.start_date
        e_date = end_date if end_date else self.end_date
        
        logger.info(f"🚀 开始为 {len(coins)} 只股票收集 {freq} 买点样本 ({s_date} -> {e_date})...")
        samples = []

        for code in coins:
            try:
                # 针对全球采集，增加 5m 数据的支持（如果存在）
                klines = self.loader.load_kline_data(code, freq, s_date, e_date)
                if not klines or len(klines) < 100: continue
                
                logger.debug(f"🔍 扫描 {code} ({freq}) 样本中...")
                chan = CChan(code=code, data_src="CUSTOM", config=self.chan_config, lv_list=[KL_TYPE.K_5M if freq=='5M' else KL_TYPE.K_30M])
                
                # 批量触发以提高效率
                step = 100
                for i in range(0, len(klines), step):
                    chunk = klines[i : i + step]
                    try:
                        chan.trigger_load({KL_TYPE.K_5M if freq=='5M' else KL_TYPE.K_30M: chunk})
                    except Exception: continue
                    
                    bsp_list = chan.get_latest_bsp(number=0)
                    for bsp in bsp_list:
                        if not bsp.is_buy or not bsp.klu.klc: continue
                        
                        # 特征提取
                        idx_in_klines = bsp.klu.idx
                        if idx_in_klines >= len(klines): continue
                        
                        features = self.extractor.extract_bsp_features(chan, bsp)
                        labels = self._generate_labels(klines, idx_in_klines, bsp.klu.close, freq=freq)
                        if not labels: continue
                        
                        sample = {"code": code, "time": str(bsp.klu.time)}
                        sample.update(labels)
                        sample.update(features)
                        samples.append(sample)
                
                if len(samples) > 0:
                    df_current = pd.DataFrame(samples)
                    df_current.fillna(0, inplace=True)
                    if os.path.exists(self.train_data_file):
                        old_df = pd.read_csv(self.train_data_file)
                        df_current = pd.concat([old_df, df_current]).drop_duplicates(subset=["code", "time"])
                    df_current.to_csv(self.train_data_file, index=False)
                    
                    # Update metadata
                    label_cols = ["label_3p_15d", "label_5p_30d", "label_10p_60d"]
                    feature_names = [c for c in df_current.columns if c not in ["code", "time"] + label_cols]
                    feature_meta = {name: i for i, name in enumerate(feature_names)}
                    with open(self.meta_file, 'w', encoding='utf-8') as f:
                        json.dump(feature_meta, f, indent=4)
                    
                    logger.info(f"📊 已处理 {code}，当前累计 {len(df_current)} 个唯一样本。")
                    samples = [] # Clear the batch
                    
            except Exception as e:
                logger.error(f"❌ 处理 {code} 出错: {e}")

        logger.info(f"✅ 样本采集全部完成。")

    def _generate_labels(self, klines, start_idx, buy_price, freq='30M') -> Dict[str, int]:
        """为单个买点生成多个维度的标签"""
        scale = 6 if freq == '5M' else 1
        configs = [
            (0.03, int(15 * scale), "label_3p_15d"),
            (0.05, int(30 * scale), "label_5p_30d"),
            (0.10, int(60 * scale), "label_10p_60d")
        ]
        res = {}
        for target, period, name in configs:
            future = klines[start_idx+1 : start_idx+1+period]
            if not future: 
                res[name] = 0
                continue
            
            target_px = buy_price * (1 + target)
            stop_px = buy_price * (1 - 0.03) # 统一 3% 止损作为硬性过滤
            
            hit_target = False
            for fkl in future:
                if fkl.low <= stop_px: break
                if fkl.high >= target_px:
                    hit_target = True
                    break
            res[name] = 1 if hit_target else 0
        return res

    def train_all(self, target_label="label_3p_15d"):
        """顺序训练所有支持的模型"""
        logger.info(f"🛠 基于标签 {target_label} 开启全模型训练流程...")
        self.train_xgboost(target_label)
        self.train_lightgbm(target_label)
        self.train_mlp(target_label)

    def get_cal_score(self, y_true, y_prob, threshold=0.5) -> float:
        """
        计算交易向评估得分 (CalScore)。
        $CalScore = (NetProfit * WinRate) / (1 + MaxDrawdown)$
        """
        preds = (y_prob >= threshold).astype(int)
        if sum(preds) == 0: return 0.0
        
        # 模拟交易详情
        profits = []
        for yt, yp in zip(y_true, preds):
            if yp == 1:
                if yt == 1:
                    profits.append(0.03) # 达成 3% 目标
                else:
                    profits.append(-0.015) # 预估止损/冲高回落平均损失 (1.5%)
        
        if not profits: return 0.0
        
        net_profit = sum(profits)
        win_rate = sum([1 for p in profits if p > 0]) / len(profits)
        
        # 计算回撤 (基于累计收益曲线)
        cum_profit = np.cumsum(profits)
        peak = np.maximum.accumulate(cum_profit)
        drawdown = peak - cum_profit
        max_dd = np.max(drawdown) if len(drawdown) > 0 else 0
        
        score = (net_profit * win_rate) / (1 + max_dd)
        return float(score)

    def _get_train_test_data(self, target_label):
        if not os.path.exists(self.train_data_file):
            raise FileNotFoundError("训练数据文件不存在，请先运行 --collect")
            
        df = pd.read_csv(self.train_data_file)
        
        # P0 修复: 按时间严格排序，防止未来信息泄漏
        if 'time' in df.columns:
            df['_sort_time'] = pd.to_datetime(df['time'], errors='coerce')
            df = df.sort_values('_sort_time').reset_index(drop=True)
            df = df.drop(columns=['_sort_time'])
            logger.info(f"📅 样本已按时间排序 (Walk-Forward): {df['time'].iloc[0]} → {df['time'].iloc[-1]}")
        
        label_cols = [c for c in df.columns if c.startswith("label_")]
        X = df.drop(columns=label_cols + ["code", "time"])
        y = df[target_label]
        
        # P0 修复: 严格时序切分 (前 80% 训练，后 20% 测试，绝不打乱)
        split_idx = int(len(df) * 0.8)
        logger.info(f"📊 训练集: {split_idx} 样本 (历史), 测试集: {len(df)-split_idx} 样本 (未来)")
        return X.iloc[:split_idx], X.iloc[split_idx:], y.iloc[:split_idx], y.iloc[split_idx:]

    def train_xgboost(self, target_label="label_3p_15d", params=None, threshold=0.5, save=True):
        if xgb is None: return 0.0
        logger.info("🌲 Training XGBoost...")
        try:
            X_train, X_test, y_train, y_test = self._get_train_test_data(target_label)
            
            # 处理样本不平衡
            pos_ratio = sum(y_train) / len(y_train)
            scale_pos_weight = (1 - pos_ratio) / (pos_ratio + 1e-7)
            
            dtrain = xgb.DMatrix(X_train, label=y_train)
            dtest = xgb.DMatrix(X_test, label=y_test)
            
            if params is None:
                params = {
                    'objective': 'binary:logistic',
                    'eval_metric': ['auc', 'logloss'],
                    'scale_pos_weight': scale_pos_weight,
                    'max_depth': 4,
                    'eta': 0.05,
                    'subsample': 0.7,
                    'colsample_bytree': 0.7
                }
            
            model = xgb.train(
                params, dtrain, 
                num_boost_round=300, 
                evals=[(dtest, 'test')], 
                early_stopping_rounds=30, 
                verbose_eval=False
            )
            
            y_prob = model.predict(dtest)
            score = self.get_cal_score(y_test.values, y_prob, threshold=threshold)
            
            # P2: 多维度评估报告
            try:
                from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score
                y_pred = (y_prob >= threshold).astype(int)
                auc = roc_auc_score(y_test, y_prob)
                f1 = f1_score(y_test, y_pred)
                precision = precision_score(y_test, y_pred, zero_division=0)
                recall = recall_score(y_test, y_pred, zero_division=0)
                win_rate = precision  # 在交易语境下 precision ≈ 胜率
                trade_count = int(sum(y_pred))
                logger.info(f"📈 [XGB 评估] AUC: {auc:.4f} | F1: {f1:.4f} | 胜率: {win_rate:.2%} | 召回: {recall:.2%} | 触发次数: {trade_count}")
            except Exception:
                pass
            
            if save:
                model.save_model(f"{self.model_prefix}xgb.json")
                logger.info(f"✅ XGBoost 模型已保存: {self.model_prefix}xgb.json, CalScore: {score:.4f} (threshold={threshold:.2f})")
            return score
        except Exception as e:
            logger.error(f"XGBoost 训练失败: {e}")
            return 0.0

    def train_lightgbm(self, target_label="label_3p_15d", params=None, threshold=0.5, save=True):
        if lgb is None: 
            logger.warning("LightGBM not installed. Skipping.")
            return 0.0
        logger.info("🌿 Training LightGBM...")
        try:
            X_train, X_test, y_train, y_test = self._get_train_test_data(target_label)
            
            train_data = lgb.Dataset(X_train, label=y_train)
            test_data = lgb.Dataset(X_test, label=y_test, reference=train_data)
            
            if params is None:
                params = {
                    'objective': 'binary', 
                    'metric': 'auc', 
                    'boosting_type': 'gbdt',
                    'is_unbalance': True, 
                    'learning_rate': 0.03, 
                    'num_leaves': 31,
                    'feature_fraction': 0.7,
                    'bagging_fraction': 0.7,
                    'bagging_freq': 5,
                    'verbose': -1
                }
            
            model = lgb.train(
                params, train_data, 
                valid_sets=[test_data], 
                num_boost_round=500, 
                callbacks=[lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(period=0)]
            )
            
            y_prob = model.predict(X_test)
            score = self.get_cal_score(y_test.values, y_prob, threshold=threshold)
            
            if save:
                model.save_model(f"{self.model_prefix}lgb.txt")
                logger.info(f"✅ LightGBM 模型已保存: {self.model_prefix}lgb.txt, CalScore: {score:.4f} (threshold={threshold:.2f})")
            return score
        except Exception as e:
            logger.error(f"LightGBM 训练失败: {e}")
            return 0.0

    def train_mlp(self, target_label="label_3p_15d"):
        if torch is None:
            logger.warning("PyTorch not installed. Skipping.")
            return
        logger.info("🧠 Training MLP (PyTorch)...")
        try:
            X_train, X_test, y_train, y_test = self._get_train_test_data(target_label)
            
            # 标准化数据
            mean = X_train.mean()
            std = X_train.std() + 1e-7
            X_train_norm = (X_train - mean) / std
            X_test_norm = (X_test - mean) / std
            
            # 保存标准化参数用于推理
            norm_params = {"mean": mean.to_dict(), "std": std.to_dict()}
            with open(os.path.join(self.data_dir, "mlp_norm.json"), 'w') as f:
                json.dump(norm_params, f)

            device = torch.device("cpu") # Force CPU for small trial runs to avoid MPS hangs
            logger.info(f"MLP Device: {device}")
            
            model = MLPModel(X_train.shape[1]).to(device)
            criterion = nn.BCELoss()
            optimizer = optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-5)
            
            # 确保转换为 numpy 再转为 tensor
            X_tensor = torch.from_numpy(X_train_norm.values).float()
            y_tensor = torch.from_numpy(y_train if isinstance(y_train, np.ndarray) else y_train.values).float().unsqueeze(1)
            
            dataset = TensorDataset(X_tensor, y_tensor)
            train_loader = DataLoader(dataset, batch_size=min(64, len(dataset)), shuffle=True)
            
            logger.info(f"MLP Input Size: {X_train.shape[1]}, Training Samples: {len(X_train)}")

            for epoch in range(100):
                model.train()
                epoch_loss = 0
                for batch_x, batch_y in train_loader:
                    batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                    optimizer.zero_grad()
                    outputs = model(batch_x)
                    loss = criterion(outputs, batch_y)
                    loss.backward()
                    optimizer.step()
                    epoch_loss += loss.item()
                
                if epoch % 20 == 0:
                    logger.info(f"MLP Epoch {epoch}/100, Loss: {epoch_loss:.4f}")
            
            # 保存模型
            torch.save(model.state_dict(), os.path.join(self.data_dir, "model_mlp.pth"))
            logger.info(f"✅ MLP 模型已保存: {os.path.join(self.data_dir, 'model_mlp.pth')}")
        except Exception as e:
            logger.error(f"MLP 训练失败: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect", action="store_true", help="收集样本数据")
    parser.add_argument("--train", action="store_true", help="训练模型(全家桶)")
    parser.add_argument("--label", type=str, default="label_3p_15d", help="指定训练用的目标标签")
    parser.add_argument("--freq", type=str, default="30M", help="指定数据频率 (30M, 5M)")
    args = parser.parse_args()
    
    trainer = ModelTrainer()
    if args.collect: 
        trainer.collect_samples(freq=args.freq)
    if args.train: 
        trainer.train_all(target_label=args.label)
    if not args.collect and not args.train:
        parser.print_help()
