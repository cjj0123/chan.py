#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时性能监控模块

该模块提供实时的系统性能监控功能，包括：
- 扫描性能指标（处理速度、内存使用等）
- 交易性能指标（信号质量、执行成功率等）
- 系统资源使用情况
- 风险状态监控

设计原则：
- 轻量级：低开销，不影响主业务逻辑
- 实时性：提供秒级更新的性能数据
- 可视化：为GUI提供友好的数据接口
"""

import time
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import deque
import logging

# 添加项目根目录到Python路径
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from Trade.db_util import CChanDB
from Trade.RiskManager import get_risk_manager
from Config.EnvConfig import config

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """
    实时性能监控器
    
    提供系统级别的性能监控和统计功能。
    """
    
    def __init__(self, db_path: str = None):
        """初始化性能监控器"""
        if db_path is None:
            db_path = config.get('database.path', 'chan_trading.db')
        
        self.db = CChanDB(db_path)
        self.risk_manager = get_risk_manager(db_path)
        
        # 性能数据缓冲区（保留最近60秒的数据）
        self.scan_times = deque(maxlen=60)
        self.memory_usage = deque(maxlen=60)
        self.cpu_usage = deque(maxlen=60)
        self.signal_scores = deque(maxlen=100)  # 保留最近100个信号评分
        
        # 统计计数器
        self.total_scanned = 0
        self.total_signals = 0
        self.total_executed = 0
        self.failed_scans = 0
        
        # 启动后台监控线程
        self._monitor_thread = None
        self._stop_monitoring = False
        self._start_background_monitoring()
        
        logger.info("性能监控器已初始化")
    
    def _start_background_monitoring(self):
        """启动后台监控线程"""
        self._stop_monitoring = False
        self._monitor_thread = threading.Thread(target=self._background_monitor, daemon=True)
        self._monitor_thread.start()
    
    def _background_monitor(self):
        """后台监控循环"""
        while not self._stop_monitoring:
            try:
                # 收集系统资源使用情况
                current_time = time.time()
                current_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
                current_cpu = psutil.cpu_percent(interval=1)
                
                self.memory_usage.append((current_time, current_memory))
                self.cpu_usage.append((current_time, current_cpu))
                
                time.sleep(1)  # 每秒更新一次
                
            except Exception as e:
                logger.warning(f"后台监控出错: {e}")
                time.sleep(5)  # 出错时延长等待时间
    
    def record_scan_performance(self, stock_count: int, duration: float):
        """
        记录扫描性能数据
        
        Args:
            stock_count: 扫描的股票数量
            duration: 扫描耗时（秒）
        """
        if duration > 0:
            scan_speed = stock_count / duration
            self.scan_times.append((time.time(), scan_speed))
            self.total_scanned += stock_count
    
    def record_signal(self, score: float):
        """
        记录信号评分
        
        Args:
            score: 信号评分（0-100）
        """
        self.signal_scores.append((time.time(), score))
        self.total_signals += 1
    
    def record_execution(self, success: bool):
        """
        记录交易执行结果
        
        Args:
            success: 执行是否成功
        """
        if success:
            self.total_executed += 1
        else:
            self.failed_scans += 1
    
    def get_realtime_metrics(self) -> Dict:
        """
        获取实时性能指标
        
        Returns:
            包含各项实时指标的字典
        """
        current_time = time.time()
        
        # 计算最近30秒的平均扫描速度
        recent_scans = [speed for timestamp, speed in self.scan_times 
                       if current_time - timestamp <= 30]
        avg_scan_speed = sum(recent_scans) / len(recent_scans) if recent_scans else 0
        
        # 计算最近30秒的平均内存使用
        recent_memory = [mem for timestamp, mem in self.memory_usage 
                        if current_time - timestamp <= 30]
        avg_memory = sum(recent_memory) / len(recent_memory) if recent_memory else 0
        
        # 计算最近30秒的平均CPU使用率
        recent_cpu = [cpu for timestamp, cpu in self.cpu_usage 
                     if current_time - timestamp <= 30]
        avg_cpu = sum(recent_cpu) / len(recent_cpu) if recent_cpu else 0
        
        # 计算最近信号的平均评分
        recent_signals = [score for timestamp, score in self.signal_scores 
                         if current_time - timestamp <= 3600]  # 最近1小时
        avg_signal_score = sum(recent_signals) / len(recent_signals) if recent_signals else 0
        
        # 获取风险状态
        risk_status = self.risk_manager.get_risk_status()
        
        return {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'scan_speed': round(avg_scan_speed, 2),
            'memory_usage_mb': round(avg_memory, 2),
            'cpu_usage_percent': round(avg_cpu, 2),
            'avg_signal_score': round(avg_signal_score, 2),
            'total_scanned': self.total_scanned,
            'total_signals': self.total_signals,
            'total_executed': self.total_executed,
            'execution_success_rate': round(
                self.total_executed / (self.total_executed + self.failed_scans) * 100 
                if (self.total_executed + self.failed_scans) > 0 else 0, 2
            ),
            'risk_status': risk_status,
            'circuit_breaker_active': risk_status.get('circuit_breaker_triggered', False)
        }
    
    def get_historical_performance(self, hours: int = 24) -> Dict:
        """
        获取历史性能数据
        
        Args:
            hours: 回溯小时数
            
        Returns:
            历史性能数据字典
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        
        # 查询历史订单数据
        orders_query = """
        SELECT add_time, side, price, quantity, status, stock_code
        FROM trading_orders
        WHERE add_time >= ? AND add_time <= ?
        ORDER BY add_time ASC
        """
        orders_df = self.db.execute_query(
            orders_query,
            (start_time.strftime('%Y-%m-%d %H:%M:%S'), end_time.strftime('%Y-%m-%d %H:%M:%S'))
        )
        
        # 查询历史信号数据
        signals_query = """
        SELECT add_date, model_score_before as score, bstype as signal_type, stock_code
        FROM trading_signals
        WHERE add_date >= ? AND add_date <= ?
        ORDER BY add_date ASC
        """
        signals_df = self.db.execute_query(
            signals_query,
            (start_time.strftime('%Y-%m-%d'), end_time.strftime('%Y-%m-%d'))
        )
        
        return {
            'orders': orders_df.to_dict('records') if not orders_df.empty else [],
            'signals': signals_df.to_dict('records') if not signals_df.empty else [],
            'period_start': start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'period_end': end_time.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def stop_monitoring(self):
        """停止监控"""
        self._stop_monitoring = True
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("性能监控器已停止")

# 全局性能监控器实例
_performance_monitor_instance = None

def get_performance_monitor(db_path: str = None) -> PerformanceMonitor:
    """
    获取全局性能监控器实例（单例模式）
    
    Args:
        db_path: 数据库路径
        
    Returns:
        PerformanceMonitor: 性能监控器实例
    """
    global _performance_monitor_instance
    if _performance_monitor_instance is None:
        _performance_monitor_instance = PerformanceMonitor(db_path)
    return _performance_monitor_instance