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
from typing import Dict, Optional

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
<<<<<<< HEAD
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

        # 按股票代码和时间排序，进行买卖配对
        win_count = 0
        total_trades = 0
        
        for code in filled_orders['stock_code'].unique():
            code_orders = filled_orders[filled_orders['stock_code'] == code].sort_values('add_time')
            buy_queue = []
            
            for _, order in code_orders.iterrows():
                if order['side'] == 'BUY':
                    buy_queue.append(order)
                elif order['side'] == 'SELL' and buy_queue:
                    # 配对最近的买入订单
                    buy_order = buy_queue.pop(0)
                    total_trades += 1
                    if order['price'] > buy_order['price']:
                        win_count += 1
        
        return win_count / total_trades if total_trades > 0 else 0.0

    def _calculate_sharpe_ratio(self, orders_df: pd.DataFrame) -> float:
        """
        计算夏普比率。

        Args:
            orders_df (pd.DataFrame): 订单数据框。

        Returns:
            float: 夏普比率。
        """
        if orders_df.empty:
            return 0.0

        # 计算每日盈亏
        orders_df = orders_df[orders_df['status'] == 'FILLED'].copy()
        if orders_df.empty:
            return 0.0
            
        orders_df['date'] = pd.to_datetime(orders_df['add_time']).dt.date
        orders_df['pnl'] = np.where(
            orders_df['side'] == 'BUY',
            -orders_df['price'] * orders_df['quantity'],
            orders_df['price'] * orders_df['quantity']
        )
        
        daily_pnl = orders_df.groupby('date')['pnl'].sum()
        if len(daily_pnl) < 2:
            return 0.0
            
        # 计算日收益率（假设初始资金为100万）
        initial_capital = 1000000.0
        daily_returns = daily_pnl / initial_capital
        
        returns = daily_returns.values
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
        sharpe_ratio = self._calculate_sharpe_ratio(orders_df)

        # 5. 构建结果字典
        metrics = {
            'period': f"过去{days}天",
            'total_pnl': round(total_pnl, 2),
            'win_rate': round(win_rate, 4),
            'sharpe_ratio': round(sharpe_ratio, 4),
            'max_drawdown': self._calculate_max_drawdown(orders_df),
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
    
    def _calculate_max_drawdown(self, orders_df: pd.DataFrame) -> float:
        """
        计算最大回撤。

        Args:
            orders_df (pd.DataFrame): 订单数据框。

        Returns:
            float: 最大回撤（负值，例如 -0.15 表示15%的回撤）。
        """
        if orders_df.empty:
            return 0.0

        filled_orders = orders_df[orders_df['status'] == 'FILLED'].copy()
        if filled_orders.empty:
            return 0.0

        # 按时间排序并计算累计盈亏
        filled_orders = filled_orders.sort_values('add_time')
        filled_orders['pnl'] = np.where(
            filled_orders['side'] == 'BUY',
            -filled_orders['price'] * filled_orders['quantity'],
            filled_orders['price'] * filled_orders['quantity']
        )
        filled_orders['cumulative_pnl'] = filled_orders['pnl'].cumsum()
        
        # 计算净值（假设初始资金为100万）
        initial_capital = 1000000.0
        filled_orders['net_value'] = initial_capital + filled_orders['cumulative_pnl']
        
        # 计算最大回撤
        running_max = filled_orders['net_value'].cummax()
        drawdown = (filled_orders['net_value'] - running_max) / running_max
        max_dd = drawdown.min()
        
        return float(max_dd)

    def _load_trades_from_db(self) -> pd.DataFrame:
        """
        从数据库加载所有已成交的交易记录。

        Returns:
            包含交易记录的DataFrame。
        """
        # 这里假设订单表中有 'order_status' = 'filled' 的记录代表已成交
        query = """
        SELECT o.*, s.signal_type 
        FROM orders o
        LEFT JOIN signals s ON o.signal_id = s.id
        WHERE o.order_status = 'filled'
        ORDER BY o.timestamp
        """
        try:
            return pd.read_sql_query(query, f"sqlite:///{self.db_path}")
        except Exception as e:
            print(f"Warning: Failed to load trades from DB: {e}. Using empty DataFrame.")
            return pd.DataFrame()

    def calculate_pnl(self, trades_df: Optional[pd.DataFrame] = None) -> float:
        """
        计算总盈亏 (Profit and Loss)。

        Args:
            trades_df: 交易记录DataFrame。如果为None，则从数据库加载。

        Returns:
            总盈亏金额。
        """
        if trades_df is None:
            trades_df = self._load_trades_from_db()
        
        if trades_df.empty:
            return 0.0
        
        # 简化计算：假设每笔交易的成本和收入直接由数量和价格决定
        # 在更复杂的系统中，这里会考虑手续费、滑点等
        buy_trades = trades_df[trades_df['action'] == 'BUY']
        sell_trades = trades_df[trades_df['action'] == 'SELL']
        
        total_cost = (buy_trades['quantity'] * buy_trades['price']).sum()
        total_revenue = (sell_trades['quantity'] * sell_trades['price']).sum()
        
        return float(total_revenue - total_cost)

    def calculate_win_rate(self, trades_df: Optional[pd.DataFrame] = None) -> float:
        """
        计算胜率。

        Args:
            trades_df: 交易记录DataFrame。如果为None，则从数据库加载。

        Returns:
            胜率（0.0 到 1.0之间）。
        """
        if trades_df is None:
            trades_df = self._load_trades_from_db()
        
        if trades_df.empty:
            return 0.0
        
        # 为了简化，我们假设每个卖出信号都是对之前买入的平仓
        # 并且盈亏由卖出价和买入价的差额决定
        # 这是一个简化的模型，实际中需要更精确的配对逻辑
        buy_prices = trades_df[trades_df['action'] == 'BUY']['price'].values
        sell_prices = trades_df[trades_df['action'] == 'SELL']['price'].values
        
        if len(buy_prices) == 0 or len(sell_prices) == 0:
            return 0.0
        
        # 配对买卖交易（这里做最简单的顺序配对）
        min_len = min(len(buy_prices), len(sell_prices))
        profits = sell_prices[:min_len] - buy_prices[:min_len]
        wins = np.sum(profits > 0)
        
        return float(wins / min_len) if min_len > 0 else 0.0

    def calculate_sharpe_ratio(self, trades_df: Optional[pd.DataFrame] = None, risk_free_rate: float = 0.02) -> float:
        """
        计算年化夏普比率。

        Args:
            trades_df: 交易记录DataFrame。如果为None，则从数据库加载。
            risk_free_rate: 无风险利率（年化）。

        Returns:
            年化夏普比率。
        """
        if trades_df is None:
            trades_df = self._load_trades_from_db()
        
        if trades_df.empty or len(trades_df) < 2:
            return 0.0
        
        # 计算每日收益率（简化处理）
        # 在真实场景中，需要基于每日净值计算
        buy_trades = trades_df[trades_df['action'] == 'BUY'].copy()
        sell_trades = trades_df[trades_df['action'] == 'SELL'].copy()
        
        if buy_trades.empty or sell_trades.empty:
            return 0.0
        
        # 合并买卖记录并按时间排序
        all_trades = pd.concat([buy_trades, sell_trades]).sort_values('timestamp')
        all_trades['daily_return'] = all_trades['price'].pct_change()
        daily_returns = all_trades['daily_return'].dropna()
        
        if daily_returns.empty:
            return 0.0
        
        daily_mean_return = daily_returns.mean()
        daily_std_return = daily_returns.std()
        
        if daily_std_return == 0:
            return np.inf if daily_mean_return > 0 else -np.inf
        
        # 年化
        annualized_mean = daily_mean_return * 252
        annualized_std = daily_std_return * np.sqrt(252)
        
        return float((annualized_mean - risk_free_rate) / annualized_std)

    def calculate_max_drawdown(self, trades_df: Optional[pd.DataFrame] = None) -> float:
        """
        计算最大回撤。

        Args:
            trades_df: 交易记录DataFrame。如果为None，则从数据库加载。

        Returns:
            最大回撤（负值，例如 -0.15 表示15%的回撤）。
        """
        if trades_df is None:
            trades_df = self._load_trades_from_db()
        
        if trades_df.empty:
            return 0.0
        
        # 构建一个简化的净值序列
        # 在真实场景中，这应该基于每日收盘后的持仓计算
        buy_trades = trades_df[trades_df['action'] == 'BUY'].copy()
        sell_trades = trades_df[trades_df['action'] == 'SELL'].copy()
        
        if buy_trades.empty:
            return 0.0
        
        # 假设初始资金足够，并且每次买入后净值下降，卖出后净值上升
        # 这是一个非常简化的模型
        all_trades = pd.concat([buy_trades, sell_trades]).sort_values('timestamp')
        all_trades['cash_flow'] = np.where(all_trades['action'] == 'BUY', -all_trades['quantity'] * all_trades['price'], all_trades['quantity'] * all_trades['price'])
        all_trades['cumulative_pnl'] = all_trades['cash_flow'].cumsum()
        
        # 计算净值（假设初始资金为0，只看累计盈亏）
        cumulative_pnl = all_trades['cumulative_pnl']
        running_max = cumulative_pnl.cummax()
        drawdown = (cumulative_pnl - running_max) / (running_max + 1e-8) # 避免除零
        
        max_dd = drawdown.min()
        return float(max_dd)

    def get_all_metrics(self) -> Dict[str, float]:
        """
        获取所有关键指标。

        Returns:
            包含所有指标的字典。
        """
        trades_df = self._load_trades_from_db()
        return {
            "total_pnl": self.calculate_pnl(trades_df),
            "win_rate": self.calculate_win_rate(trades_df),
            "sharpe_ratio": self.calculate_sharpe_ratio(trades_df),
            "max_drawdown": self.calculate_max_drawdown(trades_df)
        }
