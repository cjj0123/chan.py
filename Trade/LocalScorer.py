#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地信号评分模块

该模块提供基于缠论核心元素的快速评分功能，用于在调用视觉AI之前进行初步筛选。
通过配置化的特征和权重，可以灵活调整评分策略。

设计原则：
- 轻量级：仅依赖缠论分析结果，不依赖外部API
- 可配置：所有特征权重和阈值都可通过配置文件调整
- 高效：计算速度快，适合大规模信号初筛
"""

import logging
from typing import Dict, Any, Optional
from pathlib import Path
import sys

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 导入配置
from config import TRADING_CONFIG

logger = logging.getLogger(__name__)

class LocalScorer:
    """
    本地信号评分器
    
    基于缠论分析结果计算本地评分，用于快速筛选高质量信号。
    """
    
    def __init__(self):
        """初始化本地评分器"""
        # 从配置中加载评分参数
        local_scoring_config = TRADING_CONFIG.get('local_scoring', {})
        
        # BS点类型基础分值
        self.bsp_type_scores = local_scoring_config.get('bsp_type_scores', {
            '1': 90,      # 一买/一卖
            '2': 80,      # 二买/二卖  
            '3a': 75,     # 三买A类
            '3b': 70,     # 三买B类
            '1p': 85,     # 类一买
            '2s': 75      # 类二卖
        })
        
        # 线段力度权重
        self.seg_strength_weight = local_scoring_config.get('seg_strength_weight', 0.2)
        self.min_seg_strength = local_scoring_config.get('min_seg_strength', 0.1)
        
        # MACD状态权重
        self.macd_weight = local_scoring_config.get('macd_weight', 0.15)
        self.min_macd_divergence = local_scoring_config.get('min_macd_divergence', 0.05)
        
        # 中枢状态权重
        self.zs_weight = local_scoring_config.get('zs_weight', 0.1)
        self.min_zs_thickness = local_scoring_config.get('min_zs_thickness', 0.02)
        
        # 评分阈值
        self.local_score_threshold = local_scoring_config.get('local_score_threshold', 60)
        
        # 最终评分范围
        self.max_score = 100
        self.min_score = 0
    
    def calculate_local_score(self, chan_analysis: Dict[str, Any]) -> int:
        """
        计算本地评分
        
        Args:
            chan_analysis: 缠论分析结果字典
            
        Returns:
            int: 0-100之间的评分
        """
        try:
            base_score = self._get_bsp_type_score(chan_analysis)
            if base_score == 0:
                return 0
            
            seg_bonus = self._calculate_segment_bonus(chan_analysis)
            macd_bonus = self._calculate_macd_bonus(chan_analysis)
            zs_bonus = self._calculate_zs_bonus(chan_analysis)
            
            total_score = base_score + seg_bonus + macd_bonus + zs_bonus
            final_score = max(self.min_score, min(self.max_score, int(total_score)))
            
            logger.debug(f"本地评分计算 - 基础分:{base_score}, 线段加成:{seg_bonus:.1f}, "
                        f"MACD加成:{macd_bonus:.1f}, 中枢加成:{zs_bonus:.1f}, 最终分:{final_score}")
            
            return final_score
            
        except Exception as e:
            logger.warning(f"计算本地评分时出错: {e}")
            return 0
    
    def _get_bsp_type_score(self, chan_analysis: Dict[str, Any]) -> int:
        """获取BS点类型基础分值"""
        bsp_info = chan_analysis.get('bsp_info', {})
        bsp_type = bsp_info.get('type', '')
        
        if not bsp_type:
            return 0
            
        score = self.bsp_type_scores.get(bsp_type, 0)
        logger.debug(f"BS点类型: {bsp_type}, 基础分值: {score}")
        return score
    
    def _calculate_segment_bonus(self, chan_analysis: Dict[str, Any]) -> float:
        """计算线段力度加成"""
        try:
            # 获取最后一线段信息
            seg_list = chan_analysis.get('seg_list', [])
            if not seg_list:
                return 0
                
            last_seg = seg_list[-1]
            seg_direction = last_seg.get('direction', 0)  # 1为上涨，-1为下跌
            seg_length = last_seg.get('length', 0)
            seg_slope = last_seg.get('slope', 0)
            
            if seg_length <= 0:
                return 0
                
            # 计算线段力度（长度 * 斜率绝对值）
            seg_strength = seg_length * abs(seg_slope)
            
            # 如果是买入信号，希望是下跌线段结束；如果是卖出信号，希望是上涨线段结束
            is_buy = chan_analysis.get('is_buy', False)
            expected_direction = -1 if is_buy else 1
            
            if seg_direction != expected_direction:
                return 0
                
            # 根据力度给予加成
            if seg_strength >= self.min_seg_strength:
                bonus = min(10, seg_strength * 20)  # 最多10分加成
                return bonus * self.seg_strength_weight
            else:
                return 0
                
        except Exception as e:
            logger.warning(f"计算线段力度加成时出错: {e}")
            return 0
    
    def _calculate_macd_bonus(self, chan_analysis: Dict[str, Any]) -> float:
        """计算MACD状态加成"""
        try:
            macd_info = chan_analysis.get('macd_info', {})
            divergence = macd_info.get('divergence', 0)
            hist_value = macd_info.get('hist', 0)
            
            if divergence <= 0:
                return 0
                
            # 背驰强度加成
            divergence_bonus = min(8, divergence * 100)  # 最多8分加成
            
            # MACD柱状图位置加成
            is_buy = chan_analysis.get('is_buy', False)
            if (is_buy and hist_value < 0) or (not is_buy and hist_value > 0):
                position_bonus = 2  # 位置正确额外2分
            else:
                position_bonus = 0
                
            total_bonus = divergence_bonus + position_bonus
            return total_bonus * self.macd_weight
            
        except Exception as e:
            logger.warning(f"计算MACD加成时出错: {e}")
            return 0
    
    def _calculate_zs_bonus(self, chan_analysis: Dict[str, Any]) -> float:
        """计算中枢状态加成"""
        try:
            zs_list = chan_analysis.get('zs_list', [])
            if not zs_list:
                return 0
                
            last_zs = zs_list[-1]
            zs_height = last_zs.get('height', 0)
            current_price = chan_analysis.get('current_price', 0)
            high = last_zs.get('high', 0)
            low = last_zs.get('low', 0)
            
            if zs_height <= 0:
                return 0
                
            # 中枢厚度加成
            thickness_ratio = zs_height / current_price if current_price > 0 else 0
            if thickness_ratio >= self.min_zs_thickness:
                thickness_bonus = min(5, thickness_ratio * 100)  # 最多5分加成
            else:
                thickness_bonus = 0
                
            # 突破/回落有效性加成
            is_buy = chan_analysis.get('is_buy', False)
            if (is_buy and current_price < low) or (not is_buy and current_price > high):
                validity_bonus = 3  # 有效性确认额外3分
            else:
                validity_bonus = 0
                
            total_bonus = thickness_bonus + validity_bonus
            return total_bonus * self.zs_weight
            
        except Exception as e:
            logger.warning(f"计算中枢加成时出错: {e}")
            return 0
    
    def should_proceed_to_visual_ai(self, local_score: int) -> bool:
        """
        判断是否应该继续进行视觉AI评分
        
        Args:
            local_score: 本地评分
            
        Returns:
            bool: True表示应该继续，False表示跳过
        """
        return local_score >= self.local_score_threshold

# 全局本地评分器实例
_local_scorer_instance = None

def get_local_scorer() -> LocalScorer:
    """
    获取全局本地评分器实例（单例模式）
    
    Returns:
        LocalScorer: 本地评分器实例
    """
    global _local_scorer_instance
    if _local_scorer_instance is None:
        _local_scorer_instance = LocalScorer()
    return _local_scorer_instance