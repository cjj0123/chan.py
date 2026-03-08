import os
import sys
import json
import logging
from typing import Dict, Any

try:
    import xgboost as xgb
except ImportError:
    xgb = None

from Chan import CChan
from BuySellPoint.BS_Point import CBS_Point
from ML.FeatureExtractor import FeatureExtractor

logger = logging.getLogger(__name__)

class SignalValidator:
    """
    使用预先训练好的 XGBoost 机器学习模型来验证策略产生的买卖点 (BSP)。
    能够计算该信号在历史特征空间中获得预期收益的成功概率。
    """
    
    def __init__(self, model_path: str = "stock_cache/ml_data/xgboost_model.json", 
                 meta_path: str = "stock_cache/ml_data/feature_meta.json"):
        self.extractor = FeatureExtractor()
        self.model = None
        self.feature_meta = {}
        
        self.is_loaded = self._load_model(model_path, meta_path)
        if not self.is_loaded:
            logger.warning("机器学习模型或特征元数据加载失败，验证器将默认返回通过。")

    def _load_model(self, model_path: str, meta_path: str) -> bool:
        if xgb is None:
            logger.warning("未安装 xgboost 模块。")
            return False
            
        if not os.path.exists(model_path) or not os.path.exists(meta_path):
            logger.warning(f"找不到模型文件: {model_path} 或 {meta_path}")
            return False
            
        try:
            # 加载特征映射表
            with open(meta_path, 'r', encoding='utf-8') as f:
                self.feature_meta = json.load(f)
                
            # 加载 XGBoost 模型
            self.model = xgb.Booster()
            self.model.load_model(model_path)
            logger.info(f"✅ XGBoost 模型加载成功，特征维度: {len(self.feature_meta)}")
            return True
        except Exception as e:
            logger.error(f"加载模型异常: {e}")
            return False

    def validate_signal(self, chan: CChan, bsp: CBS_Point, threshold: float = 0.5) -> Dict[str, Any]:
        """
        验证单个买卖点信号的可靠性。
        Args:
            chan: CChan 环境
            bsp: 买卖点对象
            threshold: 概率判定阈值
            
        Returns:
            Dict: 包含 'is_valid', 'prob' 的字典结果
        """
        # 如果模型未成功加载，或者不是买点，默认放行
        if not self.is_loaded or self.model is None or not bsp.is_buy:
            return {"is_valid": True, "prob": 1.0, "msg": "Model Unloaded or Not a Buy Signal"}
            
        try:
            # 1. 提取信号当时的特征
            features = self.extractor.extract_bsp_features(chan, bsp)
            
            # 2. 转换为模型预测所需要的特征向量格式 (LibSVM 单行 或 DMatrix)
            # 因为只有1条数据，直接构造 2D list 或者 dict
            
            # 初始化一个全零的字典来保证特征次序对齐
            feat_dict = {str(v): 0.0 for k, v in self.feature_meta.items()}
            
            # 填入实际提取到的特征值
            for name, val in features.items():
                if name in self.feature_meta:
                    idx_str = str(self.feature_meta[name])
                    feat_dict[idx_str] = float(val)
                    
            # 转换为 XGBoost DMatrix 格式进行预测
            # xgb 推断单行数据最简单的方式是写入 tmp libsvm 然后读，或者直接塞给 DMatrix，这里用字典的方式：
            # 需要拼凑出一条 libsvm 字符串：`0 0:val 1:val ...`
            feat_list = []
            for name, idx in self.feature_meta.items():
                val = features.get(name, 0.0)
                feat_list.append((idx, val))
            
            feat_list.sort(key=lambda x: x[0])
            feat_str = " ".join([f"{idx}:{val:.6f}" for idx, val in feat_list])
            libsvm_line = f"0 {feat_str}\n" 
            
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.libsvm') as tmp:
                tmp.write(libsvm_line)
                tmp_path = tmp.name
                
            dtest = xgb.DMatrix(f"{tmp_path}?format=libsvm")
            predict_prob = self.model.predict(dtest)[0]
            
            os.remove(tmp_path)
            
            is_valid = predict_prob >= threshold
            msg = f"ML 验证通过 (Prob: {predict_prob:.2f} >= {threshold})" if is_valid else f"ML 过滤拦截 (Prob: {predict_prob:.2f} < {threshold})"
            
            return {
                "is_valid": bool(is_valid),
                "prob": float(predict_prob),
                "msg": msg
            }
            
        except Exception as e:
            logger.error(f"XGBoost 验证执行时发生异常: {e}")
            return {"is_valid": True, "prob": 1.0, "msg": f"Exception Occurred: {e}"}
