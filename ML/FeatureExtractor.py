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
        
        # 1. 基础开仓K线特征
        klu = bsp.klu
        features["open_klu_rate"] = (klu.close - klu.open) / klu.open if klu.open > 0 else 0
        features["open_klu_amp"] = (klu.high - klu.low) / klu.low if klu.low > 0 else 0
        
        # 2. 从内置 features 属性中提取 (Chan.py 自带的特征提取器)
        chan_features = bsp.features
        if chan_features:
            for k, v in chan_features.items():
                if isinstance(v, (int, float, bool)):
                    features[f"chan_{k}"] = float(v)
        
        # 3. 补充技术指标特征
        # MACD
        if hasattr(klu, 'macd') and klu.macd is not None:
            macd_metric = klu.macd
            features["macd_dif"] = macd_metric.DIF
            features["macd_dea"] = macd_metric.DEA
            features["macd_hist"] = macd_metric.macd
            
        # RSI (确保归一化到 0-1)
        if hasattr(klu, 'rsi') and klu.rsi is not None:
            features["rsi"] = klu.rsi / 100.0
            
        # BOLL
        if hasattr(klu, 'boll') and klu.boll is not None:
            boll = klu.boll
            # 计算收盘价在布林带中的位置 (0-1之间)
            if (boll.UP - boll.DOWN) > 0:
                features["boll_pos"] = (klu.close - boll.DOWN) / (boll.UP - boll.DOWN)
            features["boll_width"] = (boll.UP - boll.DOWN) / boll.MID if boll.MID != 0 else 0

        # 4. 新增: 动量与趋势特征 (Phase 2)
        # Price ROC (10周期变动率)
        pre_10 = klu
        for _ in range(10):
            if pre_10.pre:
                pre_10 = pre_10.pre
            else:
                break
        if pre_10 != klu:
            features["roc_10"] = (klu.close - pre_10.close) / pre_10.close if pre_10.close > 0 else 0
        
        # 移动平均线距离 (MA20/MA60) (Phase 2: 重新实现以避免枚举错误)
        def get_ma(curr_klu, period):
            s = 0
            count = 0
            tmp = curr_klu
            for _ in range(period):
                s += tmp.close
                count += 1
                if tmp.pre:
                    tmp = tmp.pre
                else:
                    break
            return s / count if count > 0 else None

        ma20 = get_ma(klu, 20)
        ma60 = get_ma(klu, 60)
        if ma20:
            features["ma20_dist"] = (klu.close - ma20) / ma20
        if ma60:
            features["ma60_dist"] = (klu.close - ma60) / ma60

        # ATR 归一化波动率 (简易计算: 最近5根 K 线振幅均值 / 价格)
        amps = []
        curr = klu
        for _ in range(5):
            amps.append((curr.high - curr.low) / curr.low if curr.low > 0 else 0)
            if curr.pre:
                curr = curr.pre
            else:
                break
        features["volatility_atr"] = sum(amps) / len(amps) if amps else 0

        # 5. 成交量特征
        if klu.trade_info:
            vol = klu.trade_info.metric.get('volume')
            if vol is not None and klu.pre and klu.pre.trade_info:
                pre_vol = klu.pre.trade_info.metric.get('volume')
                if pre_vol and pre_vol > 0:
                    features["vol_ratio"] = vol / pre_vol

        # 6. 缠论几何与结构特征 (Phase 1 Expansion)
        try:
            cur_bi = bsp.bi
            # 6.1 笔动力学 (MACD Area/Peak/Slope)
            from Common.CEnum import MACD_ALGO
            features["bi_macd_area"] = cur_bi.cal_macd_metric(MACD_ALGO.AREA, is_reverse=False)
            features["bi_macd_peak"] = cur_bi.cal_macd_metric(MACD_ALGO.PEAK, is_reverse=False)
            features["bi_slope"] = cur_bi.cal_macd_metric(MACD_ALGO.SLOPE, is_reverse=False)
            features["bi_amp_norm"] = cur_bi.amp() / (cur_bi.get_begin_val() + 1e-7)
            
            if cur_bi.pre:
                pre_bi = cur_bi.pre
                # 动力学比例: 离开笔面积 / 进入笔面积 (背驰的核心量化)
                features["bi_macd_area_ratio"] = features["bi_macd_area"] / (pre_bi.cal_macd_metric(MACD_ALGO.AREA, is_reverse=True) + 1e-7)
                features["bi_amp_ratio"] = cur_bi.amp() / (pre_bi.amp() + 1e-7)
                # 笔内成交量比例
                cur_vol = cur_bi.cal_macd_metric(MACD_ALGO.VOLUMN, is_reverse=False)
                pre_vol = pre_bi.cal_macd_metric(MACD_ALGO.VOLUMN, is_reverse=True)
                features["bi_vol_ratio"] = cur_vol / (pre_vol + 1e-7)

            # 6.2 中枢结构特征 (ZS Relationships)
            # 获取当前笔所属的线段中的中枢信息
            parent_seg = cur_bi.parent_seg
            if parent_seg:
                features["seg_zs_cnt"] = parent_seg.get_multi_bi_zs_cnt()
                features["seg_bi_cnt"] = parent_seg.cal_bi_cnt()
                # 考察线段最后一个中枢（通常对三买、或者背驰后的买点最关键）
                last_zs = parent_seg.get_final_multi_bi_zs()
                if last_zs:
                    # 距离中枢的位置 (价格相对位置)
                    features["dist_to_zs_mid"] = (klu.close - last_zs.mid) / (last_zs.mid + 1e-7)
                    features["dist_to_zs_high"] = (klu.close - last_zs.high) / (last_zs.high + 1e-7)
                    features["dist_to_zs_low"] = (klu.close - last_zs.low) / (last_zs.low + 1e-7)
                    # 中枢宽度 (K线根数)
                    features["zs_klu_width"] = (last_zs.end.idx - last_zs.begin.idx)
                    # 中枢波动率
                    features["zs_amp"] = (last_zs.high - last_zs.low) / (last_zs.mid + 1e-7)
                    # 离开笔相对于进中枢笔的力度
                    if last_zs.bi_in and last_zs.bi_out:
                         in_area = last_zs.bi_in.cal_macd_metric(MACD_ALGO.AREA, is_reverse=False)
                         out_area = last_zs.bi_out.cal_macd_metric(MACD_ALGO.AREA, is_reverse=True)
                         features["zs_divergence_ratio"] = out_area / (in_area + 1e-7)

            # 6.3 多级别对开特征 (Multi-Level Alignment)
            # 缠论核心：三级递归。这里检查上一个级别的状态
            if len(chan) > 1:
                higher_level = chan[1]
                # 这里假设 higher_level 也有买卖点列表
                higher_bsp_list = higher_level.bs_point_lst.get_latest_bsp(number=1)
                if higher_bsp_list:
                    hbsp = higher_bsp_list[-1]
                    # 时间跨度：大级别买点确认后 N 小时内，小级别触发买点
                    time_diff = abs(klu.time.ts - hbsp.klu.time.ts)
                    if time_diff <= 3600 * 24: # 同步性检查：24小时内大级别有同步信号
                        features["higher_level_bsp_aligned"] = 1.0
                        features["higher_level_bsp_type"] = float(hbsp.type[0].value) if hbsp.type else 0.0
                    else:
                        features["higher_level_bsp_aligned"] = 0.0
                
                # 线段级别特征：当前买点是否在大级别线段的末端/反弹处
                if len(higher_level.seg_list) > 0:
                    hseg = higher_level.seg_list[-1]
                    features["higher_seg_dir"] = 1.0 if hseg.is_up() else -1.0
                    features["higher_seg_amp"] = hseg.amp() / hseg.get_begin_val()

        except Exception as e:
            # print(f"Feature EXTRACTION_FAIL: {e}")
            pass

        return features

    def features_to_libsvm(self, features: Dict[str, float], label: int, meta_map: Dict[str, int], update_meta: bool = True) -> str:
        """
        将特征字典转换为 libsvm 格式的字符串
        
        Args:
            features: 特征字典
            label: 样本标签
            meta_map: 特征名到特征索引的映射字典
            update_meta: 是否允许更新元数据（预测时不应更新）
            
        Returns:
            str: "1 0:0.5 1:2.3..." 格式的数据
        """
        indexed_feats = []
        for name, value in features.items():
            if value is None:
                value = 0.0
            if name not in meta_map:
                if not update_meta:
                    continue
                meta_map[name] = len(meta_map)
            idx = meta_map[name]
            indexed_feats.append((idx, value))
            
        indexed_feats.sort(key=lambda x: x[0])
        feat_str = " ".join([f"{idx}:{val:.6f}" for idx, val in indexed_feats])
        return f"{label} {feat_str}"
