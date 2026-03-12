import os
import sys
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional

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
except ImportError:
    torch = None

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Chan import CChan
from BuySellPoint.BS_Point import CBS_Point
from ML.FeatureExtractor import FeatureExtractor

logger = logging.getLogger(__name__)

class SignalValidator:
    """
    集成验证器：使用多种机器学习模型 (XGBoost, LightGBM, MLP) 进行联合评分。
    缠论 Phase 4: 一致性校验与集成策略集成。
    """
    
    # 定义集成策略
    POLICY_MAJORITY = "MAJORITY"  # 多数通过 (超过半数模型通过各自阈值)
    POLICY_STRICT   = "STRICT"    # 严格通过 (全部模型必须通过)
    POLICY_WEIGHTED = "WEIGHTED"  # 加权平均 (平均概率通过加权阈值)

    def __init__(self, 
                 model_dir: str = "stock_cache/ml_data",
                 meta_path: str = "stock_cache/ml_data/feature_meta.json",
                 policy: str = "MAJORITY"):
        self.extractor = FeatureExtractor()
        self.models = {}
        self.feature_meta = {}
        self.mlp_norm = {}
        self.thresholds = {"XGB": 0.5, "LGB": 0.5, "MLP": 0.5} # 默认阈值
        self.model_dir = model_dir
        self.policy = policy
        self.online_log_path = os.path.join(model_dir, "online_logs.csv")
        self._model_timestamps = {}
        
        self.is_loaded = self._load_all_models(model_dir, meta_path)
        if not self.is_loaded:
            logger.warning("⚠️ 机器学习模型加载失败或不完整，验证器将处于降级模式。")

    def _load_all_models(self, model_dir: str, meta_path: str) -> bool:
        if not os.path.exists(meta_path):
            return False
            
        try:
            # 0. 加载特征映射元数据
            with open(meta_path, 'r', encoding='utf-8') as f:
                self.feature_meta = json.load(f)
            
            # 记录文件时间戳，用于热加载
            model_files = {
                "XGB": "model_xgb.json",
                "LGB": "model_lgb.txt",
                "MLP": "model_mlp.pth"
            }
            for m, f_name in model_files.items():
                p = os.path.join(model_dir, f_name)
                if os.path.exists(p):
                    self._model_timestamps[m] = os.path.getmtime(p)

            # 1. 加载 XGBoost
            xgb_path = os.path.join(model_dir, "model_xgb.json")
            if xgb and os.path.exists(xgb_path):
                self.models['XGB'] = xgb.Booster()
                self.models['XGB'].load_model(xgb_path)
                logger.info("✅ SignalValidator: XGBoost model loaded.")

            # 2. 加载 LightGBM
            lgb_path = os.path.join(model_dir, "model_lgb.txt")
            if lgb and os.path.exists(lgb_path):
                self.models['LGB'] = lgb.Booster(model_file=lgb_path)
                logger.info("✅ SignalValidator: LightGBM model loaded.")

            # 3. 加载 MLP (PyTorch)
            mlp_path = os.path.join(model_dir, "model_mlp.pth")
            norm_path = os.path.join(model_dir, "mlp_norm.json")
            if torch and os.path.exists(mlp_path) and os.path.exists(norm_path):
                from ML.ModelTrainer import MLPModel
                with open(norm_path, 'r') as f:
                    self.mlp_norm = json.load(f)
                
                input_size = len(self.feature_meta)
                self.models['MLP'] = MLPModel(input_size)
                self.models['MLP'].load_state_dict(torch.load(mlp_path, map_location=torch.device('cpu')))
                self.models['MLP'].eval()
                logger.info("✅ SignalValidator: MLP model loaded.")
                
            # 4. 加载 Optuna 优化后的阈值
            for m_type in ["XGB", "LGB"]:
                param_path = os.path.join(model_dir, "optuna", f"best_params_{m_type.lower()}.json")
                if os.path.exists(param_path):
                    with open(param_path, 'r') as f:
                        data = json.load(f)
                        self.thresholds[m_type] = data["best_params"].get("threshold", 0.5)
                        logger.info(f"🎯 SignalValidator: {m_type} optimized threshold loaded: {self.thresholds[m_type]:.2f}")

            return len(self.models) > 0
        except Exception as e:
            logger.error(f"❌ SignalValidator 模型加载异常: {e}")
            return False

    def check_and_reload(self):
        """检查模型文件是否更新，如果更新则重新加载"""
        needs_reload = False
        model_files = {"XGB": "model_xgb.json", "LGB": "model_lgb.txt", "MLP": "model_mlp.pth"}
        for m, f_name in model_files.items():
            p = os.path.join(self.model_dir, f_name)
            if os.path.exists(p):
                mtime = os.path.getmtime(p)
                if mtime > self._model_timestamps.get(m, 0):
                    logger.info(f"🔄 SignalValidator: Model file {f_name} updated, reloading...")
                    needs_reload = True
                    break
        
        if needs_reload:
            self._load_all_models(self.model_dir, os.path.join(self.model_dir, "feature_meta.json"))

    def validate_signal(self, chan: CChan, bsp: CBS_Point, threshold: float = 0.5) -> Dict[str, Any]:
        """
        通过多个模型的平均概率来验证信号。
        """
        # 如果不是买点，默认不执行 ML 过滤
        if not bsp.is_buy:
            return {"is_valid": True, "prob": 1.0, "msg": "Not a Buy Signal"}
            
        if not self.is_loaded:
            return {"is_valid": True, "prob": 1.0, "msg": "ML Models Unloaded"}

        try:
            # 1. 提取特征
            features = self.extractor.extract_bsp_features(chan, bsp)
            row = self._prepare_feature_row(features)
            
            probs = {}
            
            # 2. 各模型分别预测
            # XGBoost
            if 'XGB' in self.models:
                dtest = xgb.DMatrix([row])
                probs['XGB'] = float(self.models['XGB'].predict(dtest)[0])
                
            # LightGBM
            if 'LGB' in self.models:
                probs['LGB'] = float(self.models['LGB'].predict([row])[0])
                
            # MLP
            if 'MLP' in self.models:
                with torch.no_grad():
                    # 特征标准化 (必须使用训练时的均值和标准差)
                    x = np.array(row)
                    feat_names = sorted(self.feature_meta.items(), key=lambda x: x[1])
                    feat_names = [f[0] for f in feat_names]
                    
                    mean_vec = np.array([self.mlp_norm['mean'].get(name, 0) for name in feat_names])
                    std_vec = np.array([self.mlp_norm['std'].get(name, 1e-7) for name in feat_names])
                    x_norm = (x - mean_vec) / std_vec
                    
                    tensor_x = torch.FloatTensor(x_norm).unsqueeze(0)
                    probs['MLP'] = float(self.models['MLP'](tensor_x).item())
            
            # 3. 集成决策策略
            avg_prob = sum(probs.values()) / len(probs)
            
            if self.policy == self.POLICY_STRICT:
                is_valid = all(probs[m] >= self.thresholds.get(m, 0.5) for m in probs)
            elif self.policy == self.POLICY_WEIGHTED:
                # 暂时使用平均阈值作为加权阈值参考
                weighted_threshold = sum(self.thresholds.values()) / len(self.thresholds)
                is_valid = avg_prob >= weighted_threshold
            else: # MAJORITY
                valid_count = sum(1 for m, p in probs.items() if p >= self.thresholds.get(m, 0.5))
                is_valid = valid_count >= (len(probs) / 2.0)
            
            # 4. 记录特征一致性日志
            self._log_online_features(chan.code, bsp.dt, features, avg_prob, probs)

            detail_str = ", ".join([f"{k}:{v:.2f}(>{self.thresholds.get(k,0.5):.2f})" for k, v in probs.items()])
            msg = f"ML 集成[{self.policy}]验证 {'通过' if is_valid else '拦截'} (均值:{avg_prob:.2f} | 详情:[{detail_str}])"
            
            return {
                "is_valid": bool(is_valid),
                "prob": float(avg_prob),
                "details": probs,
                "msg": msg
            }
            
        except Exception as e:
            logger.error(f"❌ SignalValidator 验证执行异常: {e}")
            return {"is_valid": True, "prob": 1.0, "msg": f"Exception in ML Validation: {e}"}

    def _prepare_feature_row(self, features: Dict[str, float]) -> List[float]:
        """将特征字典转换为按 meta_index 排序的列表"""
        max_idx = max(self.feature_meta.values()) if self.feature_meta else 0
        row = [0.0] * (max_idx + 1)
        for name, val in features.items():
            if name in self.feature_meta:
                idx = int(self.feature_meta[name])
                row[idx] = float(val) if val is not None else 0.0
        return row

    def _log_online_features(self, code, dt, features: Dict[str, float], prob: float, details: Dict[str, float]):
        """记录实盘预测时的特征，用于一致性分析"""
        try:
            log_data = {
                "code": code,
                "dt": dt,
                "prob": prob,
                **details,
                **features
            }
            df = pd.DataFrame([log_data])
            header = not os.path.exists(self.online_log_path)
            df.to_csv(self.online_log_path, mode='a', index=False, header=header)
        except Exception as e:
            logger.error(f"❌ Failed to log online features: {e}")
