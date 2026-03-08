#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理模块

该模块提供独立的风险管理功能，包括：
1. 全局熔断机制（基于市场整体风险）
2. 动态仓位控制（基于单票风险和资金分配）
3. 交易频率限制（防止过度交易）
4. 异常检测和自动暂停

设计原则：
- 独立于交易逻辑，可被任何交易控制器调用
- 基于配置驱动，支持灵活的风险参数调整
- 提供详细的日志记录和状态报告
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import threading
import time

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 导入配置
from config import TRADING_CONFIG
from Trade.db_util import CChanDB

logger = logging.getLogger(__name__)

class RiskManager:
    """
    风险管理器类
    
    负责管理全局和个股层面的风险控制，提供熔断、仓位控制、交易频率限制等功能。
    """
    
    def __init__(self, db_path: str = "chan_trading.db"):
        """
        初始化风险管理器
        
        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
        self.db = CChanDB(db_path)
        
        # 配置参数
        self.max_position_ratio = TRADING_CONFIG.get('max_position_ratio', 0.2)
        self.max_total_positions = TRADING_CONFIG.get('max_total_positions', 10)
        self.min_visual_score = TRADING_CONFIG.get('min_visual_score', 70)
        self.max_signal_age_hours = TRADING_CONFIG.get('max_signal_age_hours', 4)
        self.dry_run = TRADING_CONFIG.get('dry_run', True)
        
        # 熔断相关配置
        self.circuit_breaker_enabled = TRADING_CONFIG.get('circuit_breaker_enabled', True)
        self.max_daily_loss_ratio = TRADING_CONFIG.get('max_daily_loss_ratio', 0.05)  # 5%日最大亏损
        self.max_consecutive_losses = TRADING_CONFIG.get('max_consecutive_losses', 3)  # 连续亏损次数
        self.circuit_breaker_duration = TRADING_CONFIG.get('circuit_breaker_duration', 3600)  # 熔断持续时间（秒）
        
        # 交易频率限制
        self.max_trades_per_hour = TRADING_CONFIG.get('max_trades_per_hour', 10)
        self.min_trade_interval = TRADING_CONFIG.get('min_trade_interval', 300)  # 最小交易间隔（秒）
        
        # 状态变量
        self.circuit_breaker_active = False
        self.circuit_breaker_start_time = None
        self.last_trade_time = {}
        self.consecutive_losses = 0
        self.daily_trades = []
        self.daily_pnl = 0.0
        self.total_positions = 0
        
        # 线程安全锁
        self._lock = threading.Lock()
        
        # 初始化今日交易记录
        self._init_daily_stats()
    
    def _init_daily_stats(self):
        """初始化今日交易统计数据"""
        today = datetime.now().date()
        try:
            # 获取今日的交易记录
            orders = self.db.execute_query(
                "SELECT * FROM orders WHERE date(created_at) = ? AND order_status = 'EXECUTED'",
                (today.isoformat(),)
            )
            
            if not orders.empty:
                self.daily_trades = orders.to_dict('records')
                # 计算今日盈亏（简化版，实际需要更复杂的计算）
                self.daily_pnl = sum(order.get('pnl', 0) for order in self.daily_trades)
                self.consecutive_losses = self._calculate_consecutive_losses(orders)
            
            # 获取当前总持仓数
            positions = self.db.execute_query("SELECT COUNT(*) as count FROM positions")
            if not positions.empty:
                self.total_positions = positions.iloc[0]['count']
                
        except Exception as e:
            logger.warning(f"初始化今日交易统计失败: {e}")
            self.daily_trades = []
            self.daily_pnl = 0.0
            self.consecutive_losses = 0
            self.total_positions = 0
    
    def _calculate_consecutive_losses(self, orders_df) -> int:
        """计算连续亏损次数"""
        if orders_df.empty:
            return 0
        
        # 按时间排序
        orders_df = orders_df.sort_values('created_at')
        consecutive_losses = 0
        max_consecutive = 0
        
        for _, order in orders_df.iterrows():
            pnl = order.get('pnl', 0)
            if pnl < 0:
                consecutive_losses += 1
                max_consecutive = max(max_consecutive, consecutive_losses)
            else:
                consecutive_losses = 0
        
        return max_consecutive
    
    def check_circuit_breaker(self) -> bool:
        """
        检查熔断机制是否触发
        
        Returns:
            bool: True表示熔断激活，应暂停交易；False表示正常交易
        """
        with self._lock:
            # 检查熔断是否已过期
            if self.circuit_breaker_active and self.circuit_breaker_start_time:
                elapsed_time = (datetime.now() - self.circuit_breaker_start_time).total_seconds()
                if elapsed_time > self.circuit_breaker_duration:
                    self.circuit_breaker_active = False
                    self.circuit_breaker_start_time = None
                    logger.info("熔断机制已解除，恢复交易")
                    return False
            
            # 如果熔断已激活，直接返回
            if self.circuit_breaker_active:
                return True
            
            # 检查熔断条件
            if not self.circuit_breaker_enabled:
                return False
            
            # 检查日最大亏损
            if self.daily_pnl < 0 and abs(self.daily_pnl) > self.max_daily_loss_ratio * 100000:  # 假设本金10万
                self._trigger_circuit_breaker("日最大亏损触发熔断")
                return True
            
            # 检查连续亏损
            if self.consecutive_losses >= self.max_consecutive_losses:
                self._trigger_circuit_breaker("连续亏损触发熔断")
                return True
            
            return False
    
    def _trigger_circuit_breaker(self, reason: str):
        """触发熔断机制"""
        self.circuit_breaker_active = True
        self.circuit_breaker_start_time = datetime.now()
        logger.warning(f"熔断机制触发: {reason}, 持续时间: {self.circuit_breaker_duration}秒")
    
    def calculate_position_size(self, code: str, available_funds: float, current_price: float, 
                             signal_score: int, risk_factor: float = 1.0, 
                             atr: Optional[float] = None, atr_multiplier: float = 2.0) -> int:
        """
        计算建议的仓位大小
        
        Args:
            code: 股票代码
            available_funds: 可用资金
            current_price: 当前价格
            signal_score: 信号评分
            risk_factor: 风险因子（基于波动率等）
            atr: ATR (Average True Range) 的值，用于计算止损距离
            atr_multiplier: ATR止损倍数
        
        Returns:
            int: 建议的股数
        """
        with self._lock:
            # 检查熔断
            if self.check_circuit_breaker():
                return 0
            
            # 检查总持仓限制
            if self.total_positions >= self.max_total_positions:
                logger.warning(f"达到最大持仓数量限制 ({self.max_total_positions})，跳过 {code}")
                return 0
            
            # 基于信号评分调整最大投入比例
            score_factor = min(signal_score / 100.0, 1.0)
            if signal_score < self.min_visual_score:
                return 0  # 评分不足，不交易
            
            # 使用 ATR 方式计算可买入数量
            max_investment = available_funds * self.max_position_ratio * score_factor / risk_factor
            
            lot_size = self._get_lot_size(code)
            
            if atr and atr > 0:
                # 每笔交易最大可承受亏损额度 = 最大投入金额 * 单笔回撤容忍度(如5%)
                # 假设单笔交易风险为总资金的一个比例，这里使用最大持仓的百分比作为损失限界
                max_loss_amount = available_funds * 0.02 * score_factor # 2% total equity risk per trade
                stop_distance = atr * atr_multiplier
                max_shares = int(max_loss_amount / stop_distance)
                
                # 不能超过可用资金允许的上限
                max_shares_by_funds = int(max_investment / current_price)
                max_shares = min(max_shares, max_shares_by_funds)
            else:
                # 降级：如果没有ATR数据，直接使用资金占比分配
                max_shares = int(max_investment / current_price)
                
            shares = (max_shares // lot_size) * lot_size
            
            logger.info(f"仓位计算 - {code}: 可用资金={available_funds:.2f}, 价格={current_price:.2f}, "
                       f"评分={signal_score}, 风险因子={risk_factor:.2f}, 建议股数={shares}")
            
            return shares
    
    def _get_lot_size(self, code: str) -> int:
        """获取股票的最小交易单位"""
        # 港股通常为100股一手，但有些可能不同
        if code.startswith('HK.'):
            return 100
        elif code.startswith('US.'):
            return 1
        else:  # A股
            return 100
    
    def check_trade_frequency_limit(self, code: str) -> bool:
        """
        检查交易频率限制
        
        Args:
            code: 股票代码
        
        Returns:
            bool: True表示可以交易，False表示频率超限
        """
        with self._lock:
            now = datetime.now()
            last_time = self.last_trade_time.get(code)
            
            if last_time:
                elapsed = (now - last_time).total_seconds()
                if elapsed < self.min_trade_interval:
                    logger.warning(f"{code} 交易频率超限，上次交易时间: {last_time}, "
                                 f"还需等待 {self.min_trade_interval - elapsed:.0f} 秒")
                    return False
            
            # 检查每小时交易次数限制
            hour_start = now.replace(minute=0, second=0, microsecond=0)
            recent_trades = [t for t in self.daily_trades 
                           if datetime.fromisoformat(t['created_at']) >= hour_start]
            if len(recent_trades) >= self.max_trades_per_hour:
                logger.warning(f"每小时交易次数超限 ({self.max_trades_per_hour})，跳过交易")
                return False
            
            return True
    
    def record_trade(self, code: str, action: str, quantity: int, price: float, 
                    signal_score: int, pnl: float = 0.0):
        """
        记录交易并更新风险统计
        
        Args:
            code: 股票代码
            action: 交易动作 ('BUY' or 'SELL')
            quantity: 数量
            price: 价格
            signal_score: 信号评分
            pnl: 盈亏（仅对卖出有效）
        """
        with self._lock:
            now = datetime.now()
            trade_record = {
                'code': code,
                'action': action,
                'quantity': quantity,
                'price': price,
                'signal_score': signal_score,
                'pnl': pnl,
                'created_at': now.isoformat()
            }
            
            self.daily_trades.append(trade_record)
            self.last_trade_time[code] = now
            
            # 更新盈亏统计
            if action == 'SELL':
                self.daily_pnl += pnl
                if pnl < 0:
                    self.consecutive_losses += 1
                else:
                    self.consecutive_losses = 0
            
            # 更新持仓统计
            if action == 'BUY':
                self.total_positions += 1
            elif action == 'SELL':
                self.total_positions = max(0, self.total_positions - 1)
            
            # 保存到数据库
            try:
                self.db.execute_query(
                    "INSERT INTO risk_logs (code, action, quantity, price, signal_score, pnl, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (code, action, quantity, price, signal_score, pnl, now.isoformat())
                )
            except Exception as e:
                logger.warning(f"记录风险日志失败: {e}")
    
    def get_risk_status(self) -> Dict:
        """获取当前风险状态"""
        with self._lock:
            circuit_breaker_info = None
            if self.circuit_breaker_active and self.circuit_breaker_start_time:
                remaining_time = self.circuit_breaker_duration - (
                    datetime.now() - self.circuit_breaker_start_time
                ).total_seconds()
                circuit_breaker_info = {
                    'active': True,
                    'remaining_time': max(0, remaining_time),
                    'start_time': self.circuit_breaker_start_time.isoformat()
                }
            else:
                circuit_breaker_info = {'active': False}
            
            return {
                'circuit_breaker': circuit_breaker_info,
                'daily_pnl': self.daily_pnl,
                'consecutive_losses': self.consecutive_losses,
                'total_positions': self.total_positions,
                'daily_trades_count': len(self.daily_trades),
                'max_position_ratio': self.max_position_ratio,
                'max_total_positions': self.max_total_positions,
                'min_visual_score': self.min_visual_score
            }
    
    def can_execute_trade(self, code: str, signal_score: int) -> bool:
        """
        检查是否可以执行交易
        
        Args:
            code: 股票代码
            signal_score: 信号评分
        
        Returns:
            bool: True表示可以执行，False表示存在风险限制
        """
        # 检查熔断
        if self.check_circuit_breaker():
            return False
        
        # 检查信号评分
        if signal_score < self.min_visual_score:
            return False
        
        # 检查交易频率
        if not self.check_trade_frequency_limit(code):
            return False
        
        return True

# 全局风险管理器实例
_risk_manager_instance = None
_risk_manager_lock = threading.Lock()

def get_risk_manager(db_path: str = "chan_trading.db") -> RiskManager:
    """
    获取全局风险管理器实例（单例模式）
    
    Args:
        db_path: 数据库路径
    
    Returns:
        RiskManager: 风险管理器实例
    """
    global _risk_manager_instance
    with _risk_manager_lock:
        if _risk_manager_instance is None:
            _risk_manager_instance = RiskManager(db_path)
        return _risk_manager_instance