import os
import sys
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

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
        self.market_models = {} # 为不同市场存储模型: {'US': {models}, 'HK': {models}, ...}
        self.market_features = {} # 为不同市场存储特征对齐元数据
        self.feature_meta = {}
        self.mlp_norms = {}
        self.market_thresholds = {} # {'US': thresholds, ...}
        
        self.model_dir = model_dir
        self.meta_path = meta_path
        self.policy = policy
        self.online_log_path = os.path.join(model_dir, "online_logs.csv")
        self._model_timestamps = {} # {'US': {m: ts}, ...}
        
        # Legacy/Consolidated attributes to prevent AttributeErrors
        self.models = {}
        self.thresholds = {"XGB": 0.5, "LGB": 0.5, "MLP": 0.5}
        self.mlp_norm = {} 
        
        # 加载特征元数据
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                self.feature_meta = json.load(f)
        
        # 预加载所有市场的模型
        self._load_all_market_models()
        
    def _load_all_market_models(self):
        """扫描目录加载所有可用市场的权重"""
        markets = ["US", "HK", "A", "CN", "GLOBAL"]
        for m in markets:
            m_dir = os.path.join(self.model_dir, m) if m != "GLOBAL" else self.model_dir
            if os.path.exists(m_dir):
                models, thresholds, norm, feat_meta, timestamps = self._load_model_set(m_dir)
                if models:
                    self.market_models[m] = models
                    self.market_thresholds[m] = thresholds
                    self.mlp_norms[m] = norm
                    if feat_meta:
                        self.market_features[m] = feat_meta
                    self._model_timestamps[m] = timestamps
                    logger.info(f"✅ SignalValidator: {m} market models loaded.")

    def _load_model_set(self, m_dir: str) -> Tuple[Dict, Dict, Dict, Dict, Dict]:
        """从特定目录加载一组模型"""
        models = {}
        thresholds = {"XGB": 0.5, "LGB": 0.5, "MLP": 0.5}
        norm = {}
        feat_meta = {}
        timestamps = {}
        
        try:
            # 1. XGBoost
            xgb_path = os.path.join(m_dir, "model_xgb.json")
            if xgb and os.path.exists(xgb_path):
                m = xgb.Booster()
                m.load_model(xgb_path)
                models['XGB'] = m
                timestamps['XGB'] = os.path.getmtime(xgb_path)

            # 2. LightGBM
            lgb_path = os.path.join(m_dir, "model_lgb.txt")
            if lgb and os.path.exists(lgb_path):
                models['LGB'] = lgb.Booster(model_file=lgb_path)
                timestamps['LGB'] = os.path.getmtime(lgb_path)

            # 3. MLP
            mlp_path = os.path.join(m_dir, "model_mlp.pth")
            norm_path = os.path.join(m_dir, "mlp_norm.json")
            if torch and os.path.exists(mlp_path) and os.path.exists(norm_path):
                from ML.ModelTrainer import MLPModel
                with open(norm_path, 'r') as f:
                    norm = json.load(f)
                input_size = len(self.feature_meta)
                m = MLPModel(input_size)
                m.load_state_dict(torch.load(mlp_path, map_location=torch.device('cpu')))
                m.eval()
                models['MLP'] = m
                timestamps['MLP'] = os.path.getmtime(mlp_path)
                
            # 4. 加载该市场的特征元数据 (如有)
            f_meta_path = os.path.join(m_dir, "feature_meta.json")
            if os.path.exists(f_meta_path):
                with open(f_meta_path, 'r', encoding='utf-8') as f:
                    feat_meta = json.load(f)
                    
            return models, thresholds, norm, feat_meta, timestamps
        except Exception as e:
            logger.error(f"Error loading model set from {m_dir}: {e}")
            return {}, {}, {}, {}, {}

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

            return len(self.market_models) > 0 or len(self.models) > 0
        except Exception as e:
            logger.error(f"❌ SignalValidator 模型加载异常: {e}")
            return False

    def check_and_reload(self):
        """检查所有市场的模型文件是否更新"""
        markets = ["US", "HK", "A", "CN", "GLOBAL"]
        for market in markets:
            timestamps = self._model_timestamps.get(market, {})
            m_dir = os.path.join(self.model_dir, market) if market != "GLOBAL" else self.model_dir
            if not os.path.exists(m_dir): continue
            
            model_files = {"XGB": "model_xgb.json", "LGB": "model_lgb.txt", "MLP": "model_mlp.pth"}
            needs_reload = False
            for m, f_name in model_files.items():
                p = os.path.join(m_dir, f_name)
                if os.path.exists(p):
                    if os.path.getmtime(p) > timestamps.get(m, 0):
                        needs_reload = True
                        break
                        
            if needs_reload:
                models, thresholds, norm, feat_meta, new_ts = self._load_model_set(m_dir)
                if models:
                    self.market_models[market] = models
                    self.market_thresholds[market] = thresholds
                    self.mlp_norms[market] = norm
                    if feat_meta:
                        self.market_features[market] = feat_meta
                    self._model_timestamps[market] = new_ts
                    logger.info(f"🔄 SignalValidator: Market {market} models reloaded.")

    def _get_market_prefix(self, code: str) -> str:
        """根据股票代码推断市场"""
        if code.startswith("US."): return "US"
        if code.startswith("HK."): return "HK"
        if code.startswith("SH.") or code.startswith("SZ."): return "A"
        return "GLOBAL"

    def validate_signal(self, chan: CChan, bsp: CBS_Point, threshold: float = 0.5) -> Dict[str, Any]:
        """
        通过多个模型的平均概率来验证信号。支持市场匹配。
        """
        code = chan.code
        market = self._get_market_prefix(code)
        is_sell = not bsp.is_buy
            
        # 寻找最匹配的模型集合
        models = self.market_models.get(market)
        thresholds = self.market_thresholds.get(market, {"XGB": 0.5, "LGB": 0.5, "MLP": 0.5})
        mlp_norm = self.mlp_norms.get(market, {})
        
        # 降级到全局模型
        if not models:
            models = self.market_models.get("GLOBAL")
            thresholds = self.market_thresholds.get("GLOBAL", thresholds)
            mlp_norm = self.mlp_norms.get("GLOBAL", mlp_norm)
            
        if not models:
            return {"is_valid": True, "prob": 1.0, "msg": f"No ML Models for {market}"}

        try:
            # 1. 提取特征
            features = self.extractor.extract_bsp_features(chan, bsp)
            
            # 2. 对齐特征名 (优先用该市场的特征对齐规则，降级到全局规则)
            market_meta = self.market_features.get(market, self.feature_meta)
            if not market_meta:
                market_meta = self.feature_meta  # 再次兜底
                
            feat_names = sorted(market_meta.items(), key=lambda x: x[1])
            feat_names = [f[0] for f in feat_names]
            row_data = {name: float(features.get(name, 0.0)) for name in feat_names}
            df_input = pd.DataFrame([row_data])
            
            probs = {}
            
            # 3. 各模型分别预测
            if 'XGB' in models:
                dtest = xgb.DMatrix(df_input)
                probs['XGB'] = float(models['XGB'].predict(dtest)[0])
                
            if 'LGB' in models:
                probs['LGB'] = float(models['LGB'].predict(df_input)[0])
                
            if 'MLP' in models:
                with torch.no_grad():
                    x = df_input.values[0]
                    mean_vec = np.array([mlp_norm.get('mean', {}).get(name, 0) for name in feat_names])
                    std_vec = np.array([mlp_norm.get('std', {}).get(name, 1e-7) for name in feat_names])
                    x_norm = (x - mean_vec) / std_vec
                    tensor_x = torch.FloatTensor(x_norm).unsqueeze(0)
                    probs['MLP'] = float(models['MLP'](tensor_x).item())
            
            # 3. 集成决策策略
            avg_prob = sum(probs.values()) / len(probs)
            
            if self.policy == self.POLICY_STRICT:
                is_valid = all(probs[m] >= thresholds.get(m, 0.5) for m in probs)
            elif self.policy == self.POLICY_WEIGHTED:
                weighted_threshold = sum(thresholds.values()) / len(thresholds)
                is_valid = avg_prob >= weighted_threshold
            else: # MAJORITY
                valid_count = sum(1 for m, p in probs.items() if p >= thresholds.get(m, 0.5))
                is_valid = valid_count >= (len(probs) / 2.0)
            
            if is_sell:
                is_valid = True

            # 4. 记录日志 (略过 market specific log 路径以保持简单)
            predict_dt = bsp.klu.time.to_str()
            self._log_online_features(code, predict_dt, features, avg_prob, probs)

            detail_str = ", ".join([f"{k}:{v:.2f}(>{thresholds.get(k,0.5):.2f})" for k, v in probs.items()])
            msg = f"ML [{market}] 验证 {'通过' if is_valid else '拦截'} (均值:{avg_prob:.2f} | [{detail_str}])"
            
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
