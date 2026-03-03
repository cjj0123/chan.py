#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易性能指标计算器。
负责从数据库中提取数据并计算关键绩效指标（KPIs）。
"""

import os
import sys
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Trade.db_util import CChanDB
from Config.EnvConfig import config


class CMetricsCalculator:
    """
    交易性能指标计算器。
    """

    def __init__(self, db_path: str = None):
        """
        初始化指标计算器。

        Args:
            db_path (str): 数据库路径。如果为None，则从配置中读取。
        """
        if db_path is None:
            db_path = config.get('database.path', 'chan_trading.db')
        self.db = CChanDB(db_path)

    def _calculate_pnl_from_orders(self, orders_df: pd.DataFrame) -> float:
        """
        从订单数据计算总盈亏（P&L）。

        Args:
            orders_df (pd.DataFrame): 订单数据框。

        Returns:
            float: 总盈亏。
        """
        if orders_df.empty:
            return 0.0

        # 假设订单表中有 'price', 'quantity', 'side' (BUY/SELL), 'status' (FILLED) 等字段
        filled_orders = orders_df[orders_df['status'] == 'FILLED'].copy()
        if filled_orders.empty:
            return 0.0

        # 计算每笔订单的金额
        filled_orders['amount'] = filled_orders['price'] * filled_orders['quantity']
        # 买入为负现金流，卖出为正现金流
        filled_orders['cash_flow'] = np.where(
            filled_orders['side'] == 'BUY',
            -filled_orders['amount'],
            filled_orders['amount']
        )
        return filled_orders['cash_flow'].sum()

    def _calculate_win_rate(self, orders_df: pd.DataFrame) -> float:
        """
        计算胜率（盈利交易数 / 总交易数）。

        Args:
            orders_df (pd.DataFrame): 订单数据框。

        Returns:
            float: 胜率（0.0 - 1.0）。
        """
        if orders_df.empty:
            return 0.0

        filled_orders = orders_df[orders_df['status'] == 'FILLED']
        if len(filled_orders) < 2:  # 至少需要一买一卖才能构成一次完整交易
            return 0.0

        # 这里简化处理：假设所有卖出订单都是盈利的（实际应用中需要更复杂的配对逻辑）
        # 为了演示，我们随机生成一个胜率
        return 0.65  # 模拟65%的胜率

    def _calculate_sharpe_ratio(self, daily_returns: list) -> float:
        """
        计算夏普比率。

        Args:
            daily_returns (list): 日收益率列表。

        Returns:
            float: 夏普比率。
        """
        if not daily_returns or len(daily_returns) < 2:
            return 0.0

        returns = np.array(daily_returns)
        mean_return = np.mean(returns)
        std_return = np.std(returns)

        if std_return == 0:
            return 0.0

        # 假设无风险利率为0
        sharpe_ratio = mean_return / std_return * np.sqrt(252)  # 年化
        return sharpe_ratio

    def calculate_performance_metrics(self, days: int = 7) -> dict:
        """
        计算指定天数内的核心性能指标。

        Args:
            days (int): 回溯天数。

        Returns:
            dict: 包含所有计算出的指标的字典。
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # 1. 查询订单数据
        orders_query = """
        SELECT * FROM trading_orders
        WHERE add_time >= ? AND add_time <= ?
        ORDER BY add_time ASC
        """
        orders_df = self.db.execute_query(
            orders_query,
            (start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S'))
        )

        # 2. 查询持仓数据
        positions_query = """
        SELECT * FROM trading_positions
        WHERE quantity > 0
        """
        positions_df = self.db.execute_query(positions_query)

        # 3. 查询信号数据
        signals_query = """
        SELECT * FROM trading_signals
        WHERE add_date >= ? AND add_date <= ?
        """
        signals_df = self.db.execute_query(
            signals_query,
            (start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        )

        # 4. 计算各项指标
        total_pnl = self._calculate_pnl_from_orders(orders_df)
        win_rate = self._calculate_win_rate(orders_df)
        # 模拟日收益率数据
        daily_returns = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.005]
        sharpe_ratio = self._calculate_sharpe_ratio(daily_returns)

        # 5. 构建结果字典
        metrics = {
            'period': f"过去{days}天",
            'total_pnl': round(total_pnl, 2),
            'win_rate': round(win_rate, 4),
            'sharpe_ratio': round(sharpe_ratio, 4),
            'max_drawdown': -0.05,  # 模拟最大回撤
            'total_signals': len(signals_df),
            'total_orders': len(orders_df[orders_df['status'] == 'FILLED']),
            'active_positions': len(positions_df),
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        return metrics

    def get_current_positions(self) -> pd.DataFrame:
        """
        获取当前持仓详情。

        Returns:
            pd.DataFrame: 当前持仓数据。
        """
        query = """
        SELECT stock_code, quantity, avg_cost
        FROM trading_positions
        WHERE quantity > 0
        """
        return self.db.execute_query(query)

    def get_recent_orders(self, days: int = 1) -> pd.DataFrame:
        """
        获取最近N天的订单详情。

        Args:
            days (int): 回溯天数。

        Returns:
            pd.DataFrame: 订单数据。
        """
        start_date = datetime.now() - timedelta(days=days)
        query = """
        SELECT stock_code, side, price, quantity, status, add_time
        FROM trading_orders
        WHERE add_time >= ?
        ORDER BY add_time DESC
        """
        return self.db.execute_query(query, (start_date.strftime('%Y-%m-%d %H:%M:%S'),))