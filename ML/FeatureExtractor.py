import os
import sys
from typing import Dict, Any

from Chan import CChan
from BuySellPoint.BS_Point import CBS_Point

class FeatureExtractor:
    """
    用于在产生缠论买卖点(BSP)时提取量化特征，供机器学习模型（如XGBoost）使用。
    参考 upstream: `strategy_demo5.py`
    """

    def __init__(self):
        pass

    def extract_bsp_features(self, chan: CChan, bsp: CBS_Point) -> Dict[str, float]:
        """
        提取特定买卖点发生时的特征
        
        Args:
            chan: 包含上下文的 CChan 对象
            bsp: 触发的买卖点对象
            
        Returns:
            Dict[str, float]: 特征字典
        """
        features = {}
        
        # 1. 基础开仓K线特征 (来自原版特征抽象)
        klu = bsp.klu
        features["open_klu_rate"] = (klu.close - klu.open) / klu.open if klu.open > 0 else 0
        features["open_klu_amp"] = (klu.high - klu.low) / klu.low if klu.low > 0 else 0
        
        # 2. 从内置 features 属性中提取 (Chan.py 自带的特征提取器)
        chan_features = bsp.features
        if chan_features:
            for k, v in chan_features.items():
                if isinstance(v, (int, float, bool)):
                    features[f"chan_{k}"] = float(v)
        
        # 3. 补充 MACD 特征 (如果可用)
        if getattr(klu, 'macd', None):
            macd_metric = klu.macd
            features["macd_hist"] = macd_metric.macd if hasattr(macd_metric, 'macd') else 0
            features["macd_dif"] = macd_metric.dif if hasattr(macd_metric, 'dif') else 0
            features["macd_dea"] = macd_metric.dea if hasattr(macd_metric, 'dea') else 0
            
        # 4. 补充段落或笔的动量特征
        # 获取最新的线段
        cur_chan_list = chan.get_bsp_iterator() # 仅为演示，实际可能需要直接访问 chan[0]
        try:
             # 安全获取最后一个元素的级别
             lv_chan = chan[0]
             if len(lv_chan.seg_list) > 1:
                 last_seg = lv_chan.seg_list[-1]
                 prev_seg = lv_chan.seg_list[-2]
                 features["seg_amp_ratio"] = (last_seg.high - last_seg.low) / (prev_seg.high - prev_seg.low + 1e-5)
             
             if len(lv_chan.bi_list) > 1:
                 last_bi = lv_chan.bi_list[-1]
                 prev_bi = lv_chan.bi_list[-2]
                 features["bi_amp_ratio"] = (last_bi.high - last_bi.low) / (prev_bi.high - prev_bi.low + 1e-5)
        except Exception:
             pass

        return features

    def features_to_libsvm(self, features: Dict[str, float], label: int, meta_map: Dict[str, int]) -> str:
        """
        将特征字典转换为 libsvm 格式的字符串
        
        Args:
            features: 特征字典
            label: 样本标签 (1: 盈利, 0: 亏损/无效)
            meta_map: 特征名到特征索引的映射字典
            
        Returns:
            str: "1 0:0.5 1:2.3..." 格式的数据
        """
        indexed_feats = []
        for name, value in features.items():
            if name not in meta_map:
                meta_map[name] = len(meta_map)
            idx = meta_map[name]
            indexed_feats.append((idx, value))
            
        indexed_feats.sort(key=lambda x: x[0])
        feat_str = " ".join([f"{idx}:{val:.6f}" for idx, val in indexed_feats])
        return f"{label} {feat_str}"
