#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货港股视觉交易系统 - 修复版 (批量信号处理)
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from futu import *
from visual_judge import VisualJudge

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('futu_hk_trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FutuHKVisualTrading:
    def __init__(self, 
                 hk_watchlist_group: str = "港股",
                 min_visual_score: int = 70,
                 max_position_ratio: float = 0.2,
                 dry_run: bool = True):
        """
        初始化港股视觉交易系统
        
        Args:
            hk_watchlist_group: 自选股组名
            min_visual_score: 最小视觉评分阈值
            max_position_ratio: 单票最大仓位比例
            dry_run: 是否为模拟盘模式
        """
        self.hk_watchlist_group = hk_watchlist_group
        self.min_visual_score = min_visual_score
        self.max_position_ratio = max_position_ratio
        self.dry_run = dry_run
        
        # 创建图表目录
        self.charts_dir = "charts"
        os.makedirs(self.charts_dir, exist_ok=True)
        
        # 初始化富途连接
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
        
        # 交易环境
        self.trd_env = TrdEnv.SIMULATE if dry_run else TrdEnv.REAL
        
        # 缠论配置 - 启用MACD计算
        self.chan_config = CChanConfig({
            "bi_strict": False,
            "one_bi_zs": True,
            "bs_type": '1,1p,2,2s,3a,3b',
            "macd": {"fast": 12, "slow": 26, "signal": 9}  # 启用MACD计算
        })
        
        # 视觉评分器
        self.visual_judge = VisualJudge(use_mock=False)
        
        logger.info(f"初始化完成 - 模拟盘: {dry_run}, 评分阈值: {min_visual_score}")
    
    def close_connections(self):
        """关闭富途连接"""
        if hasattr(self, 'quote_ctx'):
            self.quote_ctx.close()
        if hasattr(self, 'trd_ctx'):
            self.trd_ctx.close()
    
    def get_watchlist_codes(self) -> List[str]:
        """
        获取港股自选股列表
        
        Returns:
            股票代码列表
        """
        try:
            ret, data = self.quote_ctx.get_user_security(self.hk_watchlist_group)
            if ret == RET_OK:
                codes = data['code'].tolist()
                # 过滤港股代码
                hk_codes = [code for code in codes if code.startswith(('HK.', 'SH.', 'SZ.'))]
                logger.info(f"获取到 {len(hk_codes)} 只港股: {hk_codes[:10]}...")
                return hk_codes
            else:
                logger.error(f"获取自选股失败: {data}")
                return []
        except Exception as e:
            logger.error(f"获取自选股异常: {e}")
            return []
    
    def get_stock_info(self, code: str) -> Dict:
        """
        获取股票信息
        
        Args:
            code: 股票代码
            
        Returns:
            包含价格、市值等信息的字典
        """
        try:
            ret, data = self.quote_ctx.get_market_snapshot([code])
            if ret == RET_OK and not data.empty:
                stock_info = data.iloc[0].to_dict()
                return {
                    'current_price': stock_info['last_price'],
                    'market_val': stock_info.get('market_val', 0),
                    'turnover_rate': stock_info.get('turnover_rate', 0),
                    'volume': stock_info.get('volume', 0)
                }
            else:
                logger.warning(f"无法获取 {code} 的市场快照")
                return {}
        except Exception as e:
            logger.error(f"获取股票信息异常 {code}: {e}")
            return {}
    
    def calculate_position_size(self, current_price: float, available_funds: float) -> int:
        """
        计算持仓大小
        
        Args:
            current_price: 当前价格
            available_funds: 可用资金
            
        Returns:
            买入股数
        """
        if current_price <= 0:
            return 0
        
        # 计算最大可投资金（总资金的20%）
        max_investment = available_funds * self.max_position_ratio
        
        # 计算股数（以手为单位，每手100股或根据股票调整）
        shares_to_buy = int(max_investment / current_price)
        
        # 确保最小购买量
        min_lot_size = 100  # 默认100股一手
        lot_size = max(min_lot_size, shares_to_buy // 100 * 100)
        
        return max(0, lot_size)
    
    def calculate_trading_hours(self, start_time: datetime, end_time: datetime) -> float:
        """
        计算两个时间点之间的港股交易小时数（排除非交易时段）
        
        港股交易时间：
        - 上午：09:30 - 12:00
        - 下午：13:00 - 16:00
        - 周末和节假日不交易
        
        Args:
            start_time: 信号产生时间
            end_time: 当前时间
            
        Returns:
            交易小时数（浮点数）
        """
        from pandas.tseries.holiday import AbstractHolidayCalendar, Holiday
        from pandas.tseries.offsets import CustomBusinessDay
        
        # 港股节假日（简化版，主要节假日）
        class HKHolidays(AbstractHolidayCalendar):
            rules = [
                Holiday('New Year', month=1, day=1),
                Holiday('Lunar New Year 1', month=2, day=10),  # 春节（示例日期）
                Holiday('Lunar New Year 2', month=2, day=11),
                Holiday('Lunar New Year 3', month=2, day=12),
                Holiday('Good Friday', month=3, day=29),  # 耶稣受难节（示例）
                Holiday('Easter Monday', month=4, day=1),  # 复活节星期一
                Holiday('Labour Day', month=5, day=1),
                Holiday('MidAutumn', month=9, day=17),  # 中秋节（示例）
                Holiday('National Day', month=10, day=1),
                Holiday('Christmas', month=12, day=25),
                Holiday('Boxing Day', month=12, day=26),
            ]
        
        total_hours = 0.0
        current = start_time

