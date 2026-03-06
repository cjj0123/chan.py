#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
性能仪表盘组件

该模块提供实时性能监控的可视化组件，用于在GUI中显示系统性能指标。
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                            QLabel, QProgressBar, QTableWidget, QTableWidgetItem)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).resolve().parent.parent))

from Monitoring.PerformanceMonitor import get_performance_monitor

class PerformanceDashboard(QWidget):
    """
    性能仪表盘组件
    
    显示实时的系统性能指标，包括扫描速度、内存使用、CPU使用率、信号质量等。
    """
    
    def __init__(self, parent=None):
        """初始化性能仪表盘"""
        super().__init__(parent)
        
        # 获取性能监控器实例
        self.performance_monitor = get_performance_monitor()
        
        # 初始化UI
        self.init_ui()
        
        # 启动定时器，每秒更新一次数据
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_metrics)
        self.update_timer.start(1000)  # 1秒更新一次
        
        # 初始更新
        self.update_metrics()
    
    def init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("📊 系统性能仪表盘")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(title_label)
        
        # 性能指标卡片
        self.metrics_group = QGroupBox("核心性能指标")
        metrics_layout = QVBoxLayout(self.metrics_group)
        
        # 扫描速度
        self.scan_speed_label = QLabel("扫描速度: -- 只/秒")
        metrics_layout.addWidget(self.scan_speed_label)
        
        # 内存使用
        self.memory_layout = QHBoxLayout()
        self.memory_label = QLabel("内存使用: -- MB")
        self.memory_progress = QProgressBar()
        self.memory_progress.setRange(0, 1000)  # 假设最大1GB
        self.memory_layout.addWidget(self.memory_label)
        self.memory_layout.addWidget(self.memory_progress)
        metrics_layout.addLayout(self.memory_layout)
        
        # CPU使用率
        self.cpu_layout = QHBoxLayout()
        self.cpu_label = QLabel("CPU使用率: -- %")
        self.cpu_progress = QProgressBar()
        self.cpu_progress.setRange(0, 100)
        self.cpu_layout.addWidget(self.cpu_label)
        self.cpu_layout.addWidget(self.cpu_progress)
        metrics_layout.addLayout(self.cpu_layout)
        
        # 信号质量
        self.signal_layout = QHBoxLayout()
        self.signal_label = QLabel("平均信号评分: -- / 100")
        self.signal_progress = QProgressBar()
        self.signal_progress.setRange(0, 100)
        self.signal_layout.addWidget(self.signal_label)
        self.signal_layout.addWidget(self.signal_progress)
        metrics_layout.addLayout(self.signal_layout)
        
        layout.addWidget(self.metrics_group)
        
        # 统计信息表格
        self.stats_group = QGroupBox("统计信息")
        stats_layout = QVBoxLayout(self.stats_group)
        
        self.stats_table = QTableWidget(4, 2)
        self.stats_table.setHorizontalHeaderLabels(["指标", "数值"])
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        
        stats_layout.addWidget(self.stats_table)
        layout.addWidget(self.stats_group)
        
        # 风险状态
        self.risk_group = QGroupBox("风险状态")
        risk_layout = QVBoxLayout(self.risk_group)
        
        self.risk_status_label = QLabel("风险状态: 正常")
        self.risk_status_label.setStyleSheet("font-weight: bold; color: green;")
        risk_layout.addWidget(self.risk_status_label)
        
        self.circuit_breaker_label = QLabel("熔断机制: 未激活")
        self.circuit_breaker_label.setStyleSheet("color: green;")
        risk_layout.addWidget(self.circuit_breaker_label)
        
        layout.addWidget(self.risk_group)
        
        # 设置布局
        self.setLayout(layout)
    
    def update_metrics(self):
        """更新性能指标"""
        try:
            # 获取实时指标
            metrics = self.performance_monitor.get_realtime_metrics()
            
            # 更新扫描速度
            scan_speed = metrics.get('scan_speed', 0)
            self.scan_speed_label.setText(f"扫描速度: {scan_speed:.2f} 只/秒")
            
            # 更新内存使用
            memory_usage = metrics.get('memory_usage_mb', 0)
            self.memory_label.setText(f"内存使用: {memory_usage:.2f} MB")
            self.memory_progress.setValue(int(min(memory_usage, 1000)))
            self._update_progress_color(self.memory_progress, memory_usage, 1000)
            
            # 更新CPU使用率
            cpu_usage = metrics.get('cpu_usage_percent', 0)
            self.cpu_label.setText(f"CPU使用率: {cpu_usage:.2f} %")
            self.cpu_progress.setValue(int(cpu_usage))
            self._update_progress_color(self.cpu_progress, cpu_usage, 100)
            
            # 更新信号质量
            avg_signal_score = metrics.get('avg_signal_score', 0)
            self.signal_label.setText(f"平均信号评分: {avg_signal_score:.2f} / 100")
            self.signal_progress.setValue(int(avg_signal_score))
            self._update_progress_color(self.signal_progress, avg_signal_score, 100)
            
            # 更新统计信息表格
            self.stats_table.setItem(0, 0, QTableWidgetItem("总扫描股票数"))
            self.stats_table.setItem(0, 1, QTableWidgetItem(str(metrics.get('total_scanned', 0))))
            
            self.stats_table.setItem(1, 0, QTableWidgetItem("总信号数"))
            self.stats_table.setItem(1, 1, QTableWidgetItem(str(metrics.get('total_signals', 0))))
            
            self.stats_table.setItem(2, 0, QTableWidgetItem("已执行交易"))
            self.stats_table.setItem(2, 1, QTableWidgetItem(str(metrics.get('total_executed', 0))))
            
            self.stats_table.setItem(3, 0, QTableWidgetItem("执行成功率"))
            self.stats_table.setItem(3, 1, QTableWidgetItem(f"{metrics.get('execution_success_rate', 0):.2f}%"))
            
            # 更新风险状态
            risk_status = metrics.get('risk_status', {})
            circuit_breaker_active = metrics.get('circuit_breaker_active', False)
            
            if circuit_breaker_active:
                self.risk_status_label.setText("风险状态: ⚠️ 高风险")
                self.risk_status_label.setStyleSheet("font-weight: bold; color: red;")
                self.circuit_breaker_label.setText("熔断机制: 🔴 已激活")
                self.circuit_breaker_label.setStyleSheet("color: red; font-weight: bold;")
            else:
                self.risk_status_label.setText("风险状态: ✅ 正常")
                self.risk_status_label.setStyleSheet("font-weight: bold; color: green;")
                self.circuit_breaker_label.setText("熔断机制: ✅ 未激活")
                self.circuit_breaker_label.setStyleSheet("color: green;")
                
        except Exception as e:
            print(f"更新性能指标时出错: {e}")
    
    def _update_progress_color(self, progress_bar, value, max_value):
        """根据值更新进度条颜色"""
        if value / max_value > 0.8:
            progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #e74c3c; }")
        elif value / max_value > 0.6:
            progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #f39c12; }")
        else:
            progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #2ecc71; }")
    
    def stop_updates(self):
        """停止定时更新"""
        if self.update_timer.isActive():
            self.update_timer.stop()