import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import sqlite3

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use('QtAgg', force=True)  # Use QtAgg backend which is compatible with PyQt6

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget,
    QGroupBox, QHBoxLayout, QPushButton, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QLabel, QLineEdit,
    QSplitter, QFrame, QMessageBox, QProgressBar, QDateTimeEdit,
    QGridLayout, QHeaderView, QProgressDialog, QSizePolicy, QInputDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtGui import QTextCursor
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import platform

# 解决 Mac/Windows 中文乱码问题
if platform.system() == "Darwin":
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS"]
elif platform.system() == "Windows":
    plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False


class ChanPlotCanvas(FigureCanvas):
    """
    嵌入 PyQt 的 Matplotlib 画布

    用于在 GUI 中显示缠论分析图表，包括K线、笔、线段、中枢等。

    Args:
        parent: 父控件
        width: 图表宽度（英寸）
        height: 图表高度（英寸）
    """

    def __init__(self, parent=None, width=12, height=8):
        self.fig = Figure(figsize=(width, height), dpi=100)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumHeight(400)

    def clear(self):
        """清空画布内容"""
        self.fig.clear()
        self.draw()

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Plot.PlotDriver import CPlotDriver

# 富途API相关
try:
    from futu import RET_OK
except ImportError:
    RET_OK = 0  # 如果没有安装futu，使用默认值

# 富途实时监控相关
from Monitoring.FutuMonitor import FutuMonitor

# akshare 相关
import akshare as ak
import os
import re
import yaml

from Common.StockUtils import get_futu_stock_name, get_futu_watchlist_stocks, get_tradable_stocks, normalize_stock_code
from App.ScannerThreads import ScanThread, SingleAnalysisThread, UpdateDatabaseThread, RepairSingleStockThread
try:
    from App.HKTradingController import HKTradingController
    from App.MonitorController import MarketMonitorController
    from App.USTradingController import USTradingController
except ImportError:
    HKTradingController = None
    MarketMonitorController = None
    USTradingController = None

from App.BacktestTab import BacktestTab

class TraderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("缠论交易助手 V2")
        self.setGeometry(100, 100, 1600, 900)

        # --- Main Layout ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # --- Tab Widget ---
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        # --- Create Tabs ---
        self.create_scanner_tab()
        
        # --- Create Backtest Tab ---
        self.backtest_tab = BacktestTab(self)
        self.tabs.addTab(self.backtest_tab, "🔬 策略回测分析")
        
        self.create_settings_tab()

        # --- Initialize threads ---
        self.update_db_thread = None
        self.scan_thread = None
        self.analysis_thread = None
        self.repair_thread = None
        
        # --- Managers ---
        self.futu_monitor = None
        self.hk_trading_controller = None
        self.us_trading_controller = None
        self.schwab_trading_controller = None
        self.market_monitor_controller = None
        self.discord_bot = None
        # 确保按钮在界面显示后是可见的
        self.ensure_buttons_visible()
        
        # 重新加载自选股分组，确保所有 Tab 的下拉框都能获得数据
        # (第一次 load 发生在 create_scanner_tab 中，此时 settings_tab 还不存在)
        self.load_futu_watchlists()
        
        # 启动时不显示数据库统计信息，以提高启动速度
        # 数据库统计将在用户点击"更新本地数据库"时显示
        
    def ensure_buttons_visible(self):
        """确保关键按钮是可见的"""
        if hasattr(self, 'update_db_btn'):
            self.update_db_btn.setVisible(True)
        if hasattr(self, 'stop_db_btn'):
            self.stop_db_btn.setVisible(True)
        if hasattr(self, 'start_scan_btn'):
            self.start_scan_btn.setVisible(True)
        if hasattr(self, 'load_chart_btn'):
            self.load_chart_btn.setVisible(True)

    def create_scanner_tab(self):
        """创建扫描与分析选项卡"""
        self.scanner_tab = QWidget()
        self.tabs.addTab(self.scanner_tab, "📈 扫描与图表分析")
        layout = QHBoxLayout(self.scanner_tab)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # === 左侧：扫描器区 ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- 1. 数据操作区 ---
        data_group = QGroupBox("1. 数据操作")
        data_layout = QVBoxLayout()
        top_row_layout = QHBoxLayout()
        self.update_db_btn = QPushButton("更新本地数据库")
        self.update_db_btn.clicked.connect(self.on_update_db_clicked)
        self.update_db_btn.setVisible(True)
        top_row_layout.addWidget(self.update_db_btn)
        
        self.stop_db_btn = QPushButton("停止更新")
        self.stop_db_btn.clicked.connect(self.on_stop_db_clicked)
        self.stop_db_btn.setVisible(True)
        self.stop_db_btn.setEnabled(False)
        top_row_layout.addWidget(self.stop_db_btn)
        
        self.start_date_input = QDateTimeEdit()
        self.start_date_input.setCalendarPopup(True)
        self.start_date_input.setDate((datetime.now() - timedelta(days=365)).date())
        top_row_layout.addWidget(QLabel("开始:"))
        top_row_layout.addWidget(self.start_date_input)
        
        self.end_date_input = QDateTimeEdit()
        self.end_date_input.setCalendarPopup(True)
        self.end_date_input.setDate(datetime.now().date())
        top_row_layout.addWidget(QLabel("结束:"))
        top_row_layout.addWidget(self.end_date_input)
        
        self.last_update_label = QLabel("上次更新: 未知")
        top_row_layout.addWidget(self.last_update_label)
        top_row_layout.addStretch()
        data_layout.addLayout(top_row_layout)
        data_group.setLayout(data_layout)
        left_layout.addWidget(data_group)

        # --- 2. 扫描配置区 ---
        scan_group = QGroupBox("2. 扫描配置")
        scan_layout = QVBoxLayout()
        
        config_row_layout = QHBoxLayout()
        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItems(["日线", "30分钟", "5分钟", "1分钟"])
        config_row_layout.addWidget(QLabel("模式:"))
        config_row_layout.addWidget(self.scan_mode_combo)
        
        self.days_input = QLineEdit()
        self.days_input.setText("1000")
        self.days_input.setMaximumWidth(40)
        config_row_layout.addWidget(QLabel("天数:"))
        config_row_layout.addWidget(self.days_input)
        
        self.watchlist_combo = QComboBox()
        self.watchlist_combo.addItem("加载中...")
        config_row_layout.addWidget(QLabel("自选股分组:"))
        config_row_layout.addWidget(self.watchlist_combo)
        
        self.refresh_watchlist_btn = QPushButton("刷新")
        self.refresh_watchlist_btn.clicked.connect(self.load_futu_watchlists)
        self.refresh_watchlist_btn.setMaximumWidth(60)
        config_row_layout.addWidget(self.refresh_watchlist_btn)
        config_row_layout.addStretch()
        
        self.load_futu_watchlists()
        
        button_row_layout = QHBoxLayout()
        self.start_scan_btn = QPushButton("开始扫描")
        self.start_scan_btn.clicked.connect(self.on_start_scan_clicked)
        button_row_layout.addWidget(self.start_scan_btn)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        button_row_layout.addWidget(self.progress_bar)
        button_row_layout.addStretch()
        
        scan_layout.addLayout(config_row_layout)
        scan_layout.addLayout(button_row_layout)
        scan_group.setLayout(scan_layout)
        left_layout.addWidget(scan_group)

        # --- 3. 结果列表区 ---
        result_group = QGroupBox("3. 扫描结果")
        result_layout = QVBoxLayout()
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels(["代码", "名称", "信号", "时间"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        # 绑定点击事件加载图表
        self.result_table.itemClicked.connect(self.on_result_table_clicked)
        result_layout.addWidget(self.result_table)
        result_group.setLayout(result_layout)
        left_layout.addWidget(result_group)

        # --- 4. 操作日志区 ---
        log_group = QGroupBox("4. 操作日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        left_layout.addWidget(log_group)
        
        main_splitter.addWidget(left_widget)

        # === 右侧：图表分析区 ===
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 顶部手动分析控制
        manual_group = QGroupBox("图表控制 (加载四级别图表)")
        manual_layout = QHBoxLayout()
        
        self.stock_code_input = QLineEdit()
        self.stock_code_input.setPlaceholderText("代码 (如 600000)")
        self.stock_code_input.setMaximumWidth(120)
        manual_layout.addWidget(self.stock_code_input)
        self.load_chart_btn = QPushButton("加载全级别图表")
        self.load_chart_btn.clicked.connect(self.on_load_multi_chart_clicked)
        manual_layout.addWidget(self.load_chart_btn)
        
        self.repair_btn = QPushButton("修复数据")
        self.repair_btn.clicked.connect(self.on_repair_data_clicked)
        self.repair_btn.setToolTip("尝试重新下载数据")
        manual_layout.addWidget(self.repair_btn)

        manual_layout.addStretch()

        self.restart_btn = QPushButton("重启程序")
        self.restart_btn.clicked.connect(self.on_restart_clicked)
        self.restart_btn.setToolTip("重启图表分析终端")
        self.restart_btn.setStyleSheet("background-color: #f0f0f0; color: #333;")
        manual_layout.addWidget(self.restart_btn)
        manual_group.setLayout(manual_layout)
        right_layout.addWidget(manual_group)
        
        # 底部图表标签页区
        self.charts_tabs = QTabWidget()
        self.tf_frames = {}
        timeframes = ["日线", "30分钟", "5分钟", "1分钟"]
        for tf in timeframes:
            tf_frame = QWidget()
            tf_layout = QVBoxLayout(tf_frame)
            tf_layout.setContentsMargins(0, 0, 0, 0)
            
            # Initial empty canvas
            canvas = FigureCanvas(Figure())
            canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            tf_layout.addWidget(canvas)
            
            self.tf_frames[tf] = tf_frame
            self.charts_tabs.addTab(tf_frame, tf)
        
        # 延迟渲染状态
        self._chan_results = {}       # 缓存分析结果 {kl_name: chan}
        self._rendered_tabs = set()   # 已渲染的标签页名称
        self.charts_tabs.currentChanged.connect(self._on_chart_tab_changed)
        
        right_layout.addWidget(self.charts_tabs)
        
        self.analysis_detail_text = QTextEdit()
        self.analysis_detail_text.setReadOnly(True)
        self.analysis_detail_text.setMaximumHeight(80)
        self.analysis_detail_text.setPlaceholderText("分析详情将显示在此处...")
        right_layout.addWidget(self.analysis_detail_text)
        
        main_splitter.addWidget(right_widget)
        
        # 调整比例: 左侧偏窄, 右侧图表区偏宽
        main_splitter.setSizes([400, 1200])
        
        layout.addWidget(main_splitter)

    def create_settings_tab(self):
        """创建设置与自动化选项卡"""
        self.settings_tab = QWidget()
        self.tabs.addTab(self.settings_tab, "⚙️ 设置 & 自动化")
        layout = QVBoxLayout(self.settings_tab)


        # --- 港股自动交易模块 ---
        hk_group = QGroupBox("🤖 港股自动交易")
        hk_layout = QVBoxLayout()
        
        # 港股控制按钮行
        hk_btns_layout = QHBoxLayout()
        self.futu_monitor_status = QLabel("Futu监控: [未启动]")
        self.futu_monitor_btn = QPushButton("启动监控")
        self.futu_monitor_btn.clicked.connect(self.toggle_futu_monitor)
        hk_btns_layout.addWidget(self.futu_monitor_status)
        hk_btns_layout.addWidget(self.futu_monitor_btn)
        
        self.hk_auto_status = QLabel("自动交易: [未启动]")
        self.hk_auto_btn = QPushButton("启动自动交易")
        self.hk_auto_btn.clicked.connect(self.toggle_hk_trading)
        hk_btns_layout.addWidget(self.hk_auto_status)
        hk_btns_layout.addWidget(self.hk_auto_btn)
        
        # 港股专用自选股选择 (支持多选：逗号分隔)
        hk_btns_layout.addWidget(QLabel(" 📊 港股分组:"))
        self.hk_watchlist_combo = QComboBox()
        # 复用已加载的分组
        for i in range(self.watchlist_combo.count()):
            self.hk_watchlist_combo.addItem(self.watchlist_combo.itemText(i))
        # 默认选中"港股" (如果存在)
        idx = self.hk_watchlist_combo.findText("港股")
        if idx >= 0: self.hk_watchlist_combo.setCurrentIndex(idx)
        hk_btns_layout.addWidget(self.hk_watchlist_combo)
        
        
        hk_btns_layout.addStretch()
        hk_layout.addLayout(hk_btns_layout)
        
        # 港股功能按钮行
        hk_func_layout = QHBoxLayout()
        self.hk_scan_btn = QPushButton("立刻执行扫描")
        self.hk_scan_btn.clicked.connect(self.on_force_scan_clicked)
        hk_func_layout.addWidget(self.hk_scan_btn)
        
        self.query_funds_btn = QPushButton("刷新账户资金")
        self.query_funds_btn.clicked.connect(self.on_query_funds_clicked)
        hk_func_layout.addWidget(self.query_funds_btn)
        
        self.liquidate_btn = QPushButton("一键清仓")
        self.liquidate_btn.clicked.connect(self.on_liquidate_clicked)
        self.liquidate_btn.setStyleSheet("background-color: #ff4d4f; color: white; font-weight: bold;")
        hk_func_layout.addWidget(self.liquidate_btn)
        hk_func_layout.addStretch()
        hk_layout.addLayout(hk_func_layout)
        
        # 港股日志
        self.auto_log_text = QTextEdit()
        self.auto_log_text.setReadOnly(True)
        self.auto_log_text.setPlaceholderText("港股自动化日志将显示在此处...")
        self.auto_log_text.setMinimumHeight(150)
        hk_layout.addWidget(self.auto_log_text)
        
        hk_group.setLayout(hk_layout)

        # --- 美股模块容器 (右侧列) ---
        us_column = QVBoxLayout()
        
        # --- 美股自动交易模块 (IB) ---
        us_group = QGroupBox("🤖 美股自动交易 (IB)")
        us_layout = QVBoxLayout()
        
        # 美股控制按钮行
        us_btns_layout = QHBoxLayout()
        self.us_auto_status = QLabel("自动交易: [未启动]")
        self.us_auto_btn = QPushButton("启动美股交易")
        self.us_auto_btn.clicked.connect(self.toggle_us_trading)
        us_btns_layout.addWidget(self.us_auto_status)
        us_btns_layout.addWidget(self.us_auto_btn)
        
        # 添加美股专用自选股选择
        us_btns_layout.addWidget(QLabel(" 📊 美股分组:"))
        self.us_watchlist_combo = QComboBox()
        # 复用已加载的分组
        for i in range(self.watchlist_combo.count()):
            self.us_watchlist_combo.addItem(self.watchlist_combo.itemText(i))
        # 默认选中“美股” (如果存在)
        idx = self.us_watchlist_combo.findText("美股")
        if idx >= 0: self.us_watchlist_combo.setCurrentIndex(idx)
        us_btns_layout.addWidget(self.us_watchlist_combo)
        

        us_btns_layout.addStretch()
        us_layout.addLayout(us_btns_layout)
        
        # 美股功能按钮行
        us_func_layout = QHBoxLayout()
        self.us_scan_btn = QPushButton("立刻执行扫描")
        self.us_scan_btn.clicked.connect(self.on_us_force_scan_clicked)
        us_func_layout.addWidget(self.us_scan_btn)
        
        self.us_query_funds_btn = QPushButton("刷新账户资金")
        self.us_query_funds_btn.clicked.connect(self.on_us_query_funds_clicked)
        us_func_layout.addWidget(self.us_query_funds_btn)
        
        self.us_liquidate_btn = QPushButton("一键清仓")
        self.us_liquidate_btn.clicked.connect(self.on_us_liquidate_clicked)
        self.us_liquidate_btn.setStyleSheet("background-color: #ff4d4f; color: white; font-weight: bold;")
        us_func_layout.addWidget(self.us_liquidate_btn)

        us_func_layout.addStretch()
        us_layout.addLayout(us_func_layout)
        
        # 美股日志
        self.us_auto_log_text = QTextEdit()
        self.us_auto_log_text.setReadOnly(True)
        self.us_auto_log_text.setPlaceholderText("美股自动化系统日志将显示在此处...")
        self.us_auto_log_text.setMinimumHeight(150)
        us_layout.addWidget(self.us_auto_log_text)
        
        us_group.setLayout(us_layout)
        
        # --- 美股自动交易模块 (Schwab) ---
        schwab_group = QGroupBox("🤖 美股自动交易 (Schwab)")
        schwab_layout = QVBoxLayout()
        
        # Schwab 控制按钮行
        schwab_btns_layout = QHBoxLayout()
        self.schwab_auto_status = QLabel("自动交易: [未启动]")
        self.schwab_auto_btn = QPushButton("启动 Schwab 交易")
        self.schwab_auto_btn.clicked.connect(self.toggle_schwab_trading)
        schwab_btns_layout.addWidget(self.schwab_auto_status)
        schwab_btns_layout.addWidget(self.schwab_auto_btn)
        
        # 自选股选择
        schwab_btns_layout.addWidget(QLabel(" 📊 监控分组:"))
        self.schwab_watchlist_combo = QComboBox()
        for i in range(self.watchlist_combo.count()):
            self.schwab_watchlist_combo.addItem(self.watchlist_combo.itemText(i))
        idx = self.schwab_watchlist_combo.findText("美股")
        if idx >= 0: self.schwab_watchlist_combo.setCurrentIndex(idx)
        schwab_btns_layout.addWidget(self.schwab_watchlist_combo)
        
        
        schwab_btns_layout.addStretch()
        schwab_layout.addLayout(schwab_btns_layout)
        
        # 功能按钮行
        schwab_func_layout = QHBoxLayout()
        self.schwab_scan_btn = QPushButton("立刻执行扫描")
        self.schwab_scan_btn.clicked.connect(self.on_schwab_force_scan_clicked)
        schwab_func_layout.addWidget(self.schwab_scan_btn)
        
        self.schwab_query_funds_btn = QPushButton("刷新账户资金")
        self.schwab_query_funds_btn.clicked.connect(self.on_schwab_query_funds_clicked)
        schwab_func_layout.addWidget(self.schwab_query_funds_btn)
        
        self.schwab_liquidate_btn = QPushButton("一键清仓")
        self.schwab_liquidate_btn.clicked.connect(self.on_schwab_liquidate_clicked)
        self.schwab_liquidate_btn.setStyleSheet("background-color: #ff4d4f; color: white; font-weight: bold;")
        schwab_func_layout.addWidget(self.schwab_liquidate_btn)
        
        schwab_func_layout.addStretch()
        schwab_layout.addLayout(schwab_func_layout)
        
        # Schwab 日志
        self.schwab_auto_log_text = QTextEdit()
        self.schwab_auto_log_text.setReadOnly(True)
        self.schwab_auto_log_text.setPlaceholderText("Schwab 自动化系统日志将显示在此处...")
        self.schwab_auto_log_text.setMinimumHeight(150)
        schwab_layout.addWidget(self.schwab_auto_log_text)
        
        schwab_group.setLayout(schwab_layout)
        
        # --- 美股自动交易模块 (Futu) ---
        futu_us_group = QGroupBox("🤖 美股自动交易 (Futu)")
        futu_us_layout = QVBoxLayout()
        
        # 控制按钮行
        futu_us_btns_layout = QHBoxLayout()
        self.futu_us_auto_status = QLabel("自动交易: [未启动]")
        self.futu_us_auto_btn = QPushButton("启动 Futu 交易")
        self.futu_us_auto_btn.clicked.connect(self.toggle_futu_us_trading)
        futu_us_btns_layout.addWidget(self.futu_us_auto_status)
        futu_us_btns_layout.addWidget(self.futu_us_auto_btn)
        
        # 自选股选择
        futu_us_btns_layout.addWidget(QLabel(" 📊 监控分组:"))
        self.futu_us_watchlist_combo = QComboBox()
        for i in range(self.watchlist_combo.count()):
            self.futu_us_watchlist_combo.addItem(self.watchlist_combo.itemText(i))
        idx = self.futu_us_watchlist_combo.findText("美股")
        if idx >= 0: self.futu_us_watchlist_combo.setCurrentIndex(idx)
        futu_us_btns_layout.addWidget(self.futu_us_watchlist_combo)
        
        futu_us_btns_layout.addStretch()
        futu_us_layout.addLayout(futu_us_btns_layout)
        
        # 功能按钮行
        futu_us_func_layout = QHBoxLayout()
        self.futu_us_scan_btn = QPushButton("立刻执行扫描")
        self.futu_us_scan_btn.clicked.connect(self.on_futu_us_force_scan_clicked)
        futu_us_func_layout.addWidget(self.futu_us_scan_btn)
        
        self.futu_us_query_funds_btn = QPushButton("刷新账户资金")
        self.futu_us_query_funds_btn.clicked.connect(self.on_futu_us_query_funds_clicked)
        futu_us_func_layout.addWidget(self.futu_us_query_funds_btn)
        
        self.futu_us_liquidate_btn = QPushButton("一键清仓")
        self.futu_us_liquidate_btn.clicked.connect(self.on_futu_us_liquidate_clicked)
        self.futu_us_liquidate_btn.setStyleSheet("background-color: #ff4d4f; color: white; font-weight: bold;")
        futu_us_func_layout.addWidget(self.futu_us_liquidate_btn)
        
        futu_us_func_layout.addStretch()
        futu_us_layout.addLayout(futu_us_func_layout)
        
        # Futu 日志
        self.futu_us_auto_log_text = QTextEdit()
        self.futu_us_auto_log_text.setReadOnly(True)
        self.futu_us_auto_log_text.setPlaceholderText("Futu 美股自动化系统日志将显示在此处...")
        self.futu_us_auto_log_text.setMinimumHeight(150)
        futu_us_layout.addWidget(self.futu_us_auto_log_text)
        
        futu_us_group.setLayout(futu_us_layout)
        
        # 组装美股列
        us_column.addWidget(us_group)
        us_column.addWidget(schwab_group)
        us_column.addWidget(futu_us_group)
        
        # 将港股和美股模块并排显示
        market_layout = QHBoxLayout()
        market_layout.addWidget(hk_group)
        market_layout.addLayout(us_column)
        layout.addLayout(market_layout)

        # --- 多市场监控模块 (A股市场监控) ---
        monitor_group = QGroupBox("🔍 A股市场监控")
        monitor_main_layout = QVBoxLayout()
        
        # 监控控制行
        monitor_ctrl_layout = QHBoxLayout()
        self.monitor_status = QLabel("监控状态: [未启动]")
        self.monitor_btn = QPushButton("开启监控")
        self.monitor_btn.clicked.connect(self.toggle_market_monitor)
        monitor_ctrl_layout.addWidget(self.monitor_status)
        monitor_ctrl_layout.addWidget(self.monitor_btn)
        
        self.monitor_watchlist_combo = QComboBox()
        # 复用已加载的分组
        for i in range(self.watchlist_combo.count()):
            self.monitor_watchlist_combo.addItem(self.watchlist_combo.itemText(i))
        idx = self.monitor_watchlist_combo.findText("沪深")
        if idx >= 0: self.monitor_watchlist_combo.setCurrentIndex(idx)
        
        monitor_ctrl_layout.addWidget(QLabel(" 📊 监控分组:"))
        monitor_ctrl_layout.addWidget(self.monitor_watchlist_combo)
        
        
        self.monitor_scan_btn = QPushButton("立刻执行扫描")
        self.monitor_scan_btn.clicked.connect(self.on_monitor_force_scan_clicked)
        monitor_ctrl_layout.addWidget(self.monitor_scan_btn)
        
        monitor_ctrl_layout.addStretch()
        monitor_main_layout.addLayout(monitor_ctrl_layout)
        
        # 监控专属日志
        self.monitor_log_text = QTextEdit()
        self.monitor_log_text.setReadOnly(True)
        self.monitor_log_text.setPlaceholderText("A股/美股监控日志及信号将显示在此处...")
        self.monitor_log_text.setMinimumHeight(180)
        monitor_main_layout.addWidget(self.monitor_log_text)
        
        monitor_group.setLayout(monitor_main_layout)
        layout.addWidget(monitor_group)

        layout.addStretch()
        
    def append_auto_log(self, text):
        """添加日志到港股自动化专属日志区域"""
        import datetime
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.auto_log_text.append(f"[{now}] {text}")

    def append_monitor_log(self, text):
        """添加日志到 A/US 监控专属日志区域"""
        import datetime
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.monitor_log_text.append(f"[{now}] {text}")

    def toggle_market_monitor(self):
        """切换多市场监控状态"""
        if self.market_monitor_controller is None:
            try:
                # 使用 A股专用分组和附加分组
                group_name = self.monitor_watchlist_combo.currentText()
                
                if group_name == "加载中..." or group_name == "":
                    self.append_monitor_log("❌ 启动监控失败: 未选择自选股分组")
                    return
                
                if MarketMonitorController is None:
                    self.append_monitor_log("❌ 无法导入 MarketMonitorController")
                    return

                # 共享 Discord Bot
                from App.DiscordBot import DiscordBot
                bot = self._get_shared_discord_bot(controller=None) # 监控暂不抢占控制权
                
                self.market_monitor_controller = MarketMonitorController(watchlist_group=group_name, discord_bot=bot)
                self.market_monitor_controller.log_message.connect(self.append_monitor_log)
                
                import threading
                def run_monitor():
                    self.market_monitor_controller.run_monitor_loop()
                    
                self.monitor_thread = threading.Thread(target=run_monitor, daemon=True)
                self.monitor_thread.start()
                
                self.monitor_status.setText(f"监控: [运行中 - {group_name}]")
                self.monitor_btn.setText("停止监控")
                self.append_monitor_log(f"✅ 多市场监控已启动，监听分组: {group_name} (避让逻辑已激活)。")
            except Exception as e:
                self.append_monitor_log(f"❌ 启动监控失败: {e}")
                self.market_monitor_controller = None
        else:
            if self.discord_bot and self.discord_bot.controller == self.market_monitor_controller:
                self.discord_bot.controller = None
            self.market_monitor_controller.stop()
            self.market_monitor_controller = None
            self.monitor_status.setText("监控状态: [已停止]")
            self.monitor_btn.setText("开启监控")
            self.append_monitor_log("ℹ️ 多市场监控已停止")

    def toggle_futu_monitor(self):
        """切换富途实时监控状态"""
        if self.futu_monitor is None:
            try:
                # 使用港股专用分组选择框，而非扫描 Tab 的通用 combo
                group_name = self.hk_watchlist_combo.currentText()
                if group_name == "加载中..." or group_name == "":
                    self.append_auto_log("❌ 启动富途监控失败: 未选择自选股分组")
                    return
                self.futu_monitor = FutuMonitor()
                
                # 如果自动交易控制器存在，将实时信号路由给它处理并下单
                if self.hk_trading_controller is not None:
                    self.futu_monitor.set_callback(self.hk_trading_controller.process_realtime_signal)
                    
                # 监控可能会阻塞，因此在实际中通常也要放在线程，但这里先修复参数
                import threading
                def run_monitor():
                    self.futu_monitor.start(group_name)
                threading.Thread(target=run_monitor, daemon=True).start()
                self.futu_monitor_status.setText("Futu监控: [运行中]")
                self.futu_monitor_btn.setText("停止监控")
                self.append_auto_log(f"✅ 富途监控已启动，监听分组: {group_name}")
            except Exception as e:
                self.append_auto_log(f"❌ 启动富途监控失败: {e}")
                self.futu_monitor = None
        else:
            self.futu_monitor.stop()
            self.futu_monitor = None
            self.futu_monitor_status.setText("Futu监控: [已停止]")
            self.futu_monitor_btn.setText("启动监控")
            self.append_auto_log("ℹ️ 富途监控已停止")

    @pyqtSlot(bool)
    def reset_liquidate_btn(self, success: bool):
        """恢复一键清仓按钮状态，由工作线程通过 invokeMethod 跨线程调用"""
        self.liquidate_btn.setEnabled(True)
        self.liquidate_btn.setText("一键清仓")
        if success:
            QMessageBox.information(self, "清仓结果", "✅ 一键清仓执行完成。")
        else:
            QMessageBox.warning(self, "清仓结果", "⚠️ 一键清仓执行部分失败或出现异常，请检查日志。")

    def toggle_hk_trading(self):
        """切换港股自动交易状态"""
        if self.hk_trading_controller is None:
            if HKTradingController is None:
                self.append_auto_log("❌ 无法导入 HKTradingController，可能缺少依赖")
                return
            try:
                # 从港股专用下拉框获取分组名
                group_name = self.hk_watchlist_combo.currentText()
                
                # 共享 Discord Bot
                from App.DiscordBot import DiscordBot
                bot = self._get_shared_discord_bot(controller=None)

                self.hk_trading_controller = HKTradingController(hk_watchlist_group=group_name, discord_bot=bot)
                self.hk_trading_controller.log_message.connect(self.append_auto_log)
                
                # 在新线程中运行策略
                import threading
                def run_trade():
                    # 关联 controller 到 bot
                    if self.discord_bot:
                        self.discord_bot.controller = self.hk_trading_controller
                    self.hk_trading_controller.run_scan_and_trade()
                    
                self.hk_trade_thread = threading.Thread(target=run_trade, daemon=True)
                self.hk_trade_thread.start()
                
                self.hk_auto_status.setText("港股自动交易: [运行中]")
                self.hk_auto_btn.setText("停止自动交易")
                self.append_auto_log("✅ 港股自动交易已启动。")
            except Exception as e:
                self.append_auto_log(f"❌ 启动港股自动交易失败: {e}")
                self.hk_trading_controller = None
        else:
            if self.discord_bot and self.discord_bot.controller == self.hk_trading_controller:
                self.discord_bot.controller = None
            self.hk_trading_controller.stop()
            self.hk_trading_controller = None
            self.hk_auto_status.setText("港股自动交易: [已停止]")
            self.hk_auto_btn.setText("启动自动交易")
            self.append_auto_log("ℹ️ 港股自动交易已停止")
            
    def _get_shared_discord_bot(self, controller=None):
        """获取或创建共享的 Discord Bot"""
        if self.discord_bot is None:
            from config import TRADING_CONFIG
            from App.DiscordBot import DiscordBot
            
            discord_conf = TRADING_CONFIG.get('discord', {})
            token = discord_conf.get('token')
            if token:
                try:
                    self.discord_bot = DiscordBot(
                        token=token,
                        channel_id=discord_conf.get('channel_id'),
                        allowed_user_ids=discord_conf.get('allowed_user_ids', []),
                        controller=controller
                    )
                    self.discord_bot.start()
                    self.append_auto_log("🤖 [共享] Discord 机器人已启动")
                except Exception as e:
                    self.append_auto_log(f"⚠️ Discord 机器人启动失败: {e}")
        elif controller:
            self.discord_bot.controller = controller
            
        return self.discord_bot

    def on_force_scan_clicked(self):
        """手动触发一次缠论策略扫描"""
        if self.hk_trading_controller is None or getattr(self.hk_trading_controller, '_is_running', False) == False:
            self.append_auto_log("⚠️ 请先启动港股自动交易，然后再执行扫描。")
            return
            
        reply = QMessageBox.question(
            self, '执行扫描',
            "⚡ 确认要立即执行强制策略扫描吗？\n这将手动触发对全量自选股的完整缠论分析。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.hk_trading_controller.force_scan()
            self.append_auto_log("⚡ 已下发强制扫描指令，策略将在接下来的几秒内心跳中触发执行，请留意日志刷新。")

    def append_us_auto_log(self, text: str):
        """添加美股自动交易日志"""
        from datetime import datetime
        now = datetime.now().strftime("%H:%M:%S")
        self.us_auto_log_text.append(f"[{now}] {text}")
        # 自动滚动到底部
        self.us_auto_log_text.moveCursor(QTextCursor.MoveOperation.End)

    def toggle_us_trading(self):
        """切换美股自动交易状态 (IB)"""
        if self.us_trading_controller is None:
            if USTradingController is None:
                self.append_us_auto_log("❌ 无法导入 USTradingController，可能缺少依赖")
                return
            try:
                # 使用美股专用分组
                group_name = self.us_watchlist_combo.currentText()
                
                # 共享 Discord Bot
                bot = self._get_shared_discord_bot(controller=None)

                self.us_trading_controller = USTradingController(us_watchlist_group=group_name, discord_bot=bot)
                self.us_trading_controller.log_message.connect(self.append_us_auto_log)
                self.us_trading_controller.funds_updated.connect(self.update_us_funds_display)
                
                import threading
                def run_trade():
                    # 关联 controller 到 bot
                    if self.discord_bot:
                        self.discord_bot.controller = self.us_trading_controller
                    self.us_trading_controller.run_trading_loop()
                    
                self.us_trade_thread = threading.Thread(target=run_trade, daemon=True)
                self.us_trade_thread.start()
                
                self.us_auto_status.setText("美股自动交易: [运行中]")
                self.us_auto_btn.setText("停止美股交易")
                self.append_us_auto_log(f"✅ 美股自动交易已启动 (IB, 分组: {group_name})")
            except Exception as e:
                self.append_us_auto_log(f"❌ 启动美股自动交易失败: {e}")
                self.us_trading_controller = None
        else:
            if self.discord_bot and self.discord_bot.controller == self.us_trading_controller:
                self.discord_bot.controller = None
            self.us_trading_controller.stop()
            self.us_trading_controller = None
            self.us_auto_status.setText("美股自动交易: [已停止]")
            self.us_auto_btn.setText("启动美股交易")
            self.append_us_auto_log("ℹ️ 美股自动交易已停止")

    def update_us_funds_display(self, available: float, total: float, positions: list):
        """更新美股资金和持仓显示 (由 Controller 信号触发)"""
        self.append_us_auto_log(f"💰 [IB 账户] 可用资金: ${available:,.2f}, 总资产: ${total:,.2f}")
        if positions:
            pos_msg = "📦 [当前持仓]:"
            for p in positions:
                pos_msg += f"\n   • {p['symbol']}: {p['qty']} 股, 市值: ${p['mkt_value']:.2f}, 成本: ${p['avg_cost']:.2f}"
            self.append_us_auto_log(pos_msg)
        else:
            self.append_us_auto_log("ℹ️ 当前账户无美股持仓")

    def on_us_force_scan_clicked(self):
        """手动触发美股策略扫描"""
        if self.us_trading_controller is None:
            self.append_us_auto_log("⚠️ 请先启动美股自动交易。")
            return
        
        reply = QMessageBox.question(self, '确认扫描', '确定要立即执行一次完整的美股策略扫描吗？',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.us_trading_controller.force_scan()
            self.append_us_auto_log("⚡ 已手动触发向 IB 发起的扫描指令。")

    def on_us_query_funds_clicked(self):
        """查询美股账户资金 (IB) - 改为异步请求"""
        if self.us_trading_controller:
            self.us_trading_controller.query_account_funds()
        else:
            self.append_us_auto_log("⚠️ 请先启动美股交易连接。")

    def on_us_liquidate_clicked(self):
        """美股一键清仓"""
        if self.us_trading_controller is None:
            self.append_us_auto_log("⚠️ 请先启动美股交易。")
            return
            
        reply = QMessageBox.warning(self, '危险操作', '确定要一键卖出所有美股持仓吗？此操作不可撤销！',
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.append_us_auto_log("🔥 正在执行美股全量清仓...")
            self.us_trading_controller.close_all_positions()

    # --- Futu 美股自动交易控制方法 ---
    def append_futu_us_auto_log(self, text: str):
        """追加 Futu 美股自动化日志"""
        from datetime import datetime
        now = datetime.now().strftime("%H:%M:%S")
        self.futu_us_auto_log_text.append(f"[{now}] {text}")

    def toggle_futu_us_trading(self):
        """切换美股自动交易状态 (Futu)"""
        if not hasattr(self, 'futu_us_trading_controller'): self.futu_us_trading_controller = None
        
        if self.futu_us_trading_controller is None:
            try:
                # 使用选中的美股分组
                group_name = self.futu_us_watchlist_combo.currentText()
                bot = self._get_shared_discord_bot(controller=None)

                self.futu_us_trading_controller = USTradingController(us_watchlist_group=group_name, discord_bot=bot, venue="FUTU")
                self.futu_us_trading_controller.log_message.connect(self.append_futu_us_auto_log)
                self.futu_us_trading_controller.funds_updated.connect(self.update_futu_us_funds_display)
                
                import threading
                def run_trade():
                    if self.discord_bot:
                        self.discord_bot.controller = self.futu_us_trading_controller
                    self.futu_us_trading_controller.run_trading_loop()
                    
                self.futu_us_trade_thread = threading.Thread(target=run_trade, daemon=True)
                self.futu_us_trade_thread.start()
                
                self.futu_us_auto_status.setText("自动交易: [运行中]")
                self.futu_us_auto_btn.setText("停止 Futu 交易")
                self.append_futu_us_auto_log(f"✅ 美股自动交易已启动 (Futu, 分组: {group_name})")
            except Exception as e:
                self.append_futu_us_auto_log(f"❌ 启动美股自动交易失败: {e}")
                self.futu_us_trading_controller = None
        else:
            if self.discord_bot and self.discord_bot.controller == self.futu_us_trading_controller:
                self.discord_bot.controller = None
            self.futu_us_trading_controller.stop()
            self.futu_us_trading_controller = None
            self.futu_us_auto_status.setText("自动交易: [已停止]")
            self.futu_us_auto_btn.setText("启动 Futu 交易")
            self.append_futu_us_auto_log("ℹ️ 美股自动交易 (Futu) 已停止")

    def update_futu_us_funds_display(self, available: float, total: float, positions: list):
        """更新 Futu 美股资金和持仓显示"""
        self.append_futu_us_auto_log(f"💰 [Futu 账户] 可用资金: ${available:,.2f}, 总资产/购买力: ${total:,.2f}")
        if positions:
            pos_msg = "📦 [当前持仓]:"
            for p in positions:
                pos_msg += f"\n   • {p['symbol']}: {p['qty']} 股, 市值: ${p['mkt_value']:.2f}, 成本: ${p['avg_cost']:.2f}"
            self.append_futu_us_auto_log(pos_msg)
        else:
            self.append_futu_us_auto_log("ℹ️ 当前账户无 Futu 美股持仓")

    def on_futu_us_force_scan_clicked(self):
        """手动触发 Futu 美股策略扫描"""
        if not hasattr(self, 'futu_us_trading_controller') or self.futu_us_trading_controller is None:
            self.append_futu_us_auto_log("⚠️ 请先启动 Futu 美股自动交易。")
            return
        
        reply = QMessageBox.question(self, '确认扫描', '确定要立即执行一次完整的 Futu 美股策略扫描吗？',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.futu_us_trading_controller.force_scan()
            self.append_futu_us_auto_log("⚡ 已手动触发向 Futu 发起的扫描指令。")

    def on_futu_us_query_funds_clicked(self):
        """查询 Futu 美股账户资金"""
        if hasattr(self, 'futu_us_trading_controller') and self.futu_us_trading_controller:
            self.futu_us_trading_controller.query_account_funds()
        else:
            self.append_futu_us_auto_log("⚠️ 请先启动 Futu 交易连接。")

    def on_futu_us_liquidate_clicked(self):
        """Futu 美股一键清仓"""
        if not hasattr(self, 'futu_us_trading_controller') or self.futu_us_trading_controller is None:
            self.append_futu_us_auto_log("⚠️ 请先启动 Futu 交易。")
            return
            
        reply = QMessageBox.critical(self, '一键清仓', '🚨 警告: 确定要清空所有 Futu 美股持仓吗？此操作不可撤销！',
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.append_futu_us_auto_log("🔥 正在执行 Futu 美股全量清仓...")
            self.futu_us_trading_controller.close_all_positions()

    def append_schwab_auto_log(self, text: str):
        """添加 Schwab 自动交易日志"""
        from datetime import datetime
        now = datetime.now().strftime("%H:%M:%S")
        self.schwab_auto_log_text.append(f"[{now}] {text}")
        self.schwab_auto_log_text.moveCursor(QTextCursor.MoveOperation.End)

    def toggle_schwab_trading(self):
        """切换 Schwab 自动交易状态"""
        if self.schwab_trading_controller is None:
            if USTradingController is None:
                self.append_schwab_auto_log("❌ 无法导入 USTradingController，可能缺少依赖")
                return
            try:
                group_name = self.schwab_watchlist_combo.currentText()
                
                bot = self._get_shared_discord_bot(controller=None)

                self.schwab_trading_controller = USTradingController(
                    us_watchlist_group=group_name, discord_bot=bot, venue="SCHWAB"
                )
                self.schwab_trading_controller.log_message.connect(self.append_schwab_auto_log)
                self.schwab_trading_controller.funds_updated.connect(self.update_schwab_funds_display)
                
                import threading
                def run_trade():
                    self.schwab_trading_controller.run_trading_loop()
                    
                self.schwab_trade_thread = threading.Thread(target=run_trade, daemon=True)
                self.schwab_trade_thread.start()
                
                self.schwab_auto_status.setText("Schwab 自动交易: [运行中]")
                self.schwab_auto_btn.setText("停止 Schwab 交易")
                self.append_schwab_auto_log(f"✅ Schwab 自动交易已启动 (分组: {group_name})")
            except Exception as e:
                self.append_schwab_auto_log(f"❌ 启动 Schwab 自动交易失败: {e}")
                self.schwab_trading_controller = None
        else:
            self.schwab_trading_controller.stop()
            self.schwab_trading_controller = None
            self.schwab_auto_status.setText("Schwab 自动交易: [已停止]")
            self.schwab_auto_btn.setText("启动 Schwab 交易")
            self.append_schwab_auto_log("ℹ️ Schwab 自动交易已停止")

    def update_schwab_funds_display(self, available: float, total: float, positions: list):
        """更新 Schwab 资金和持仓显示"""
        self.append_schwab_auto_log(f"💰 [Schwab 账户] 可用资金: ${available:,.2f}, 总资产: ${total:,.2f}")
        if positions:
            pos_msg = "📦 [当前持仓]:"
            for p in positions:
                pos_msg += f"\n   • {p['symbol']}: {p['qty']} 股, 市值: ${p['mkt_value']:.2f}, 成本: ${p['avg_cost']:.2f}"
            self.append_schwab_auto_log(pos_msg)
        else:
            self.append_schwab_auto_log("ℹ️ 当前账户无 Schwab 持仓")

    def on_schwab_force_scan_clicked(self):
        """手动触发 Schwab 策略扫描"""
        if self.schwab_trading_controller is None:
            self.append_schwab_auto_log("⚠️ 请先启动 Schwab 自动交易。")
            return
        
        reply = QMessageBox.question(self, '确认扫描', '确定要立即执行一次完整的 Schwab 策略扫描吗？',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.schwab_trading_controller.force_scan()
            self.append_schwab_auto_log("⚡ 已手动触发向 Schwab 发起的扫描指令。")

    def on_schwab_query_funds_clicked(self):
        """查询 Schwab 账户资金"""
        if self.schwab_trading_controller:
            self.schwab_trading_controller.query_account_funds()
        else:
            self.append_schwab_auto_log("⚠️ 请先启动 Schwab 交易连接。")

    def on_schwab_liquidate_clicked(self):
        """Schwab 一键清仓"""
        if self.schwab_trading_controller is None:
            self.append_schwab_auto_log("⚠️ 请先启动 Schwab 交易。")
            return
            
        reply = QMessageBox.warning(self, '危险操作', '确定要一键卖出所有 Schwab 持仓吗？此操作不可撤销！',
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.append_schwab_auto_log("🔥 正在执行 Schwab 全量清仓...")
            self.schwab_trading_controller.close_all_positions()

            
    def on_monitor_force_scan_clicked(self):
        """异步/定时监控：手动触发一次扫描"""
        if self.market_monitor_controller is None or getattr(self.market_monitor_controller, '_is_running', False) == False:
            self.append_monitor_log("⚠️ 请先启动多市场监控，然后再执行扫描。")
            return
            
        reply = QMessageBox.question(
            self, '执行扫描',
            "⚡ 确认要立即对 A/US 监控分组执行强制扫描吗？\n这将手动触发一轮完整的缠论信号分析。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.market_monitor_controller.force_scan()
            self.append_monitor_log("⚡ 已下发监控强制扫描指令，请留意监控日志。")
            
    def on_query_funds_clicked(self):
        """刷新并打印账户持仓及资金到自动化日志"""
        if HKTradingController is None:
            self.append_auto_log("❌ 无法连接接口获取资金信息。")
            return
        
        self.append_auto_log("🔄 正在查询富途账户资金及持仓...")
        try:
            # 临时创建一个控制器来获取资金
            temp_controller = HKTradingController()
            temp_controller.log_message.connect(self.append_auto_log)
            funds, total_assets = temp_controller.get_account_assets()
            
            # 同时查询持仓
            from futu import OpenHKTradeContext, TrdEnv, RET_OK
            try:
                env = temp_controller.trd_env
                trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
                ret, data = trd_ctx.position_list_query(trd_env=env)
                if ret == RET_OK:
                    if data.empty:
                        self.append_auto_log("📊 当前无持仓。")
                    else:
                        self.append_auto_log(f"📊 当前持仓: {len(data)} 个股票")
                        for _, row in data.iterrows():
                            self.append_auto_log(f"   - {row.get('code', 'N/A')}: {row.get('qty', 0)}股, 市值 {row.get('market_val', 0):.2f}")
                else:
                    self.append_auto_log(f"⚠️ 查询持仓失败: {data}")
                trd_ctx.close()
            except Exception as e:
                self.append_auto_log(f"⚠️ 查询持仓出现异常: {e}")
            
            # 关闭临时控制器的连接
            if hasattr(temp_controller, 'quote_ctx') and temp_controller.quote_ctx:
                temp_controller.quote_ctx.close()
            if hasattr(temp_controller, 'trd_ctx') and temp_controller.trd_ctx:
                temp_controller.trd_ctx.close()
            
            self.append_auto_log(f"💰 账户可用资金: {funds:.2f}")
        except Exception as e:
            self.append_auto_log(f"❌ 查询账户资金异常: {e}")
            
    def on_liquidate_clicked(self):
        """
        处理一键清仓点击事件
        """
        reply = QMessageBox.question(
            self, '确认清仓',
            "⚠️ 您确定要执行【一键清仓】吗？\n这将以市价/当前价卖出账户中的所有持仓股票！\n请确保交易环境（模拟/实盘）正确。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 获取或创建一个控制器来执行清仓
            controller = None
            if hasattr(self, 'hk_trading_controller') and self.hk_trading_controller:
                controller = self.hk_trading_controller
            else:
                try:
                    controller = HKTradingController()
                    controller.log_message.connect(self.append_auto_log)
                except Exception as e:
                    self.append_auto_log(f"❌ 初始化清仓控制器失败: {e}")
            
            if controller:
                self.liquidate_btn.setEnabled(False)
                self.liquidate_btn.setText("正在清仓...")
                
                # 定义清仓后的收尾工作
                def run_liquidate():
                    try:
                        success = controller.close_all_positions()
                    except Exception as e:
                        success = False
                        self.append_auto_log(f"❌ 一键清仓遇到异常: {e}")
                    
                    # 回到主线程操作 UI
                    from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
                    
                    def on_finished():
                        self.liquidate_btn.setEnabled(True)
                        self.liquidate_btn.setText("一键清仓")
                        if success:
                            QMessageBox.information(self, "清仓结果", "✅ 一键清仓执行完成。")
                        else:
                            QMessageBox.warning(self, "清仓结果", "⚠️ 一键清仓执行部分失败或出现异常，请检查日志。")
                    
                    QMetaObject.invokeMethod(self, "reset_liquidate_btn", Qt.ConnectionType.QueuedConnection, Q_ARG(bool, success))
                
                # 开启后台线程清仓
                import threading
                threading.Thread(target=run_liquidate, daemon=True).start()
            else:
                QMessageBox.critical(self, "错误", "❌ 无法连接接口，清仓操作无法执行。")

    def on_repair_data_clicked(self):
        """处理修复数据按钮点击"""
        code = self.stock_code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "警告", "请输入要修复的股票代码！")
            return
            
        normalized_code = normalize_stock_code(code)
        
        # 禁用按钮防止重复点击
        self.repair_btn.setEnabled(False)
        self.log_text.append(f"🔧 准备修复 {normalized_code} 的数据...")
        
        try:
            import yaml
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Config", "config.yaml")
            start_date = "2024-01-01"
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    if config and 'scanner' in config and 'data_repair_start_date' in config['scanner']:
                        start_date = config['scanner']['data_repair_start_date']
                        
            # 启动修复线程
            from App.ScannerThreads import RepairSingleStockThread
            self.repair_thread = RepairSingleStockThread(normalized_code, start_date=start_date)
            self.repair_thread.log_signal.connect(self.on_log_message)
            self.repair_thread.finished.connect(self.on_repair_data_finished)
            self.repair_thread.start()
            
        except Exception as e:
            self.log_text.append(f"❌ 启动修复失败: {str(e)}")
            self.repair_btn.setEnabled(True)

    def on_repair_data_finished(self, success, message):
        """处理数据修复完成"""
        if success:
            QMessageBox.information(self, "修复完成", message)
        else:
            QMessageBox.warning(self, "修复失败", message)
        self.repair_btn.setEnabled(True)

    def on_restart_clicked(self):
        """重启整个应用程序"""
        import sys
        import os
        from PyQt6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(self, '重启程序', '确定要重启程序吗？\n(如果有正在更新或扫描网络任务，将被强制中断)',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log_text.append("🔄 正在准备重启...")
            
            # 1. 停止所有的交易和监控控制器 (确保释放资源)
            try:
                if hasattr(self, 'hk_trading_controller') and self.hk_trading_controller:
                    self.hk_trading_controller.stop()
                if hasattr(self, 'us_trading_controller') and self.us_trading_controller:
                    self.us_trading_controller.stop()
                if hasattr(self, 'monitor_controller') and self.monitor_controller:
                    self.monitor_controller.stop()
            except Exception as e:
                print(f"Error stopping controllers: {e}")

            # 2. 安全终止活动线程
            if hasattr(self, 'update_db_thread') and self.update_db_thread and self.update_db_thread.isRunning():
                self.update_db_thread.stop()
                self.update_db_thread.wait(1000)
            
            # 3. 使用 os.execv 强制重启进程 (替换当前镜像)
            import sys
            import os
            
            self.log_text.append("🚀 正在重新实例化进程并重载代码...")
            
            try:
                # 重新计算可执行路径和参数
                executable = sys.executable
                args = [executable] + sys.argv
                
                # 在 Unix 系统上使用 os.execv 完美替换进程
                # 这会立即终止当前 Python 实例并启动新实例
                os.execv(executable, args)
            except Exception as e:
                print(f"Restart failed with os.execv: {e}")
                # 备选方案：如果 os.execv 失败，尝试 QProcess (虽然概率较低)
                from PyQt6.QtCore import QProcess
                if QProcess.startDetached(sys.executable, sys.argv):
                    QApplication.quit()
                    sys.exit(0)
                else:
                    QMessageBox.critical(self, "重启失败", f"无法自动重启: {e}\n请手动关闭并重新运行程序。")

    def get_chan_config(self):
        """获取缠论配置"""
        config = CChanConfig()
        config.bNewStyle = True  # 新笔模式
        # config.bi_strict = self.bi_strict_cb.isChecked()  # 笔严格模式 (已删除 UI)
        return config

    def get_timeframe_kl_type(self):
        """根据扫描配置的时间级别下拉框获取对应的KL_TYPE"""
        timeframe_map = {
            "日线": KL_TYPE.K_DAY,
            "30分钟": KL_TYPE.K_30M,
            "5分钟": KL_TYPE.K_5M,
            "1分钟": KL_TYPE.K_1M,
        }
        selected_timeframe = self.scan_mode_combo.currentText()
        return timeframe_map.get(selected_timeframe, KL_TYPE.K_DAY)

    def get_analysis_timeframe_kl_type(self):
        """根据分析标签页的时间级别下拉框获取对应的KL_TYPE"""
        timeframe_map = {
            "日线": KL_TYPE.K_DAY,
            "30分钟": KL_TYPE.K_30M,
            "5分钟": KL_TYPE.K_5M,
            "1分钟": KL_TYPE.K_1M,
        }
        selected_timeframe = self.timeframe_combo.currentText()
        return timeframe_map.get(selected_timeframe, KL_TYPE.K_DAY)

    def on_update_db_clicked(self):
        """处理更新数据库按钮点击"""
        self.log_text.append("🔄 开始更新本地数据库...")
        
        # 获取时间级别
        selected_timeframe = self.scan_mode_combo.currentText()
        # 不管选择哪个时间级别，都下载所有时间级别的数据
        timeframes_to_download = ['day', '30m', '5m', '1m']
        
        # 获取用户输入的天数
        try:
            days_text = self.days_input.text().strip()
            if days_text:
                days = int(days_text)
                if days <= 0:
                    days = 30  # 如果输入不合法，默认为30天
            else:
                days = 30  # 如果没有输入，默认为30天
        except ValueError:
            days = 30  # 如果转换失败，默认为30天
            self.log_text.append(f"⚠️ 天数输入格式不正确，使用默认值30天")
        
        # 获取日期范围
        start_date = self.start_date_input.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        end_date = self.end_date_input.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        
        # 从本地获取股票列表，根据自选股分组选择
        try:
            from DataAPI.SQLiteAPI import CChanDB
            db = CChanDB()
            
            # 显示数据库当前统计信息
            self.display_db_stats(db)
            
            # 获取自选股分组选择
            selected_watchlist = self.watchlist_combo.currentText()
            
            # 根据选择的分组构建查询条件
            if selected_watchlist not in ["沪深", "港股通", "全部"] and selected_watchlist != "加载中...":
                # 如果选择的是自定义分组，则尝试从富途API获取具体的自选股列表
                try:
                    from futu import OpenQuoteContext, RET_OK
                    import os
                    FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
                    
                    quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
                    ret, data = quote_ctx.get_user_security(selected_watchlist)
                    
                    if ret == RET_OK and not data.empty:
                        stock_codes = data['code'].tolist()
                        if stock_codes:
                            # 构建查询条件，只获取自选股的数据
                            code_placeholders = ','.join([f"'{code}'" for code in stock_codes])
                            stock_query = f"SELECT DISTINCT code FROM kline_day WHERE code IN ({code_placeholders})"
                        else:
                            self.log_text.append(f"⚠️ 自选股分组 '{selected_watchlist}' 中没有股票")
                            quote_ctx.close()
                            return
                    else:
                        self.log_text.append(f"⚠️ 获取自选股列表失败: {data}")
                        # 如果富途API获取失败，回退到查询所有股票
                        stock_query = "SELECT DISTINCT code FROM kline_day"
                        
                    quote_ctx.close()
                except Exception as e:
                    self.log_text.append(f"⚠️ 获取富途自选股时出错: {str(e)}")
                    # 出错时回退到查询所有股票
                    stock_query = "SELECT DISTINCT code FROM kline_day"
            else:
                # 如果选择的是预设分组，则使用相应的筛选条件
                stock_query = "SELECT DISTINCT code FROM kline_day"
                
                # 根据选择的分组应用不同的筛选条件
                if selected_watchlist == "沪深":
                    stock_query += " WHERE code LIKE 'SH.%' OR code LIKE 'SZ.%'"
                elif selected_watchlist == "港股通":
                    stock_query += " WHERE code LIKE 'HK.%'"
                elif selected_watchlist == "全部":
                    # 查询所有股票，不做额外筛选
                    pass
                # 对于其他情况，查询所有股票
            
            # 获取股票列表
            try:
                stock_df = db.execute_query(stock_query)
                stock_codes = stock_df['code'].tolist() if not stock_df.empty else []
            except Exception as db_error:
                self.log_text.append(f"⚠️ 读取数据库时出现问题: {str(db_error)}")
                stock_codes = []
            
            if not stock_codes:
                # 如果数据库中没有数据，尝试从其他地方获取一些示例股票
                # 从现有的股票列表文件中获取
                try:
                    import os
                    if os.path.exists("../futu_a_stocks.txt"):
                        with open("../futu_a_stocks.txt", "r", encoding="utf-8") as f:
                            stock_codes = [line.strip() for line in f.readlines() if line.strip()]
                        stock_codes = stock_codes[:50]  # 限制数量
                    else:
                        # 使用默认的示例股票
                        stock_codes = ["SH.000001", "SZ.000002", "SH.600000", "SZ.000001"]
                except:
                    stock_codes = ["SH.000001", "SZ.000002", "SH.600000", "SZ.000001"]
            
            self.log_text.append(f"📊 准备下载 {len(stock_codes)} 只股票的 {selected_timeframe} 数据...")
            self.log_text.append(f"📅 日期范围: {start_date} 到 {end_date}")
            
            # 启动QThread下载数据
            self.update_db_thread = UpdateDatabaseThread(
                stock_codes,
                days,  # 使用用户输入的天数
                timeframes_to_download,
                start_date,  # 使用用户选择的开始日期
                end_date    # 使用用户选择的结束日期
            )
            self.update_db_thread.log_signal.connect(self.on_log_message)
            self.update_db_thread.finished.connect(self.on_update_database_finished)
            self.update_db_thread.start()
            
            self.update_db_btn.setEnabled(False)
            self.stop_db_btn.setEnabled(True)
            
        except Exception as e:
            self.log_text.append(f"❌ 获取股票列表失败: {str(e)}")
            import traceback
            self.log_text.append(f"详细错误: {traceback.format_exc()}")
    
    def display_db_stats(self, db):
        """显示数据库统计信息"""
        try:
            import os
            from datetime import datetime
            
            # 获取数据库文件大小
            db_size = 0
            if os.path.exists(db.db_path):
                db_size = os.path.getsize(db.db_path)
                # 转换为MB
                db_size_mb = round(db_size / (1024 * 1024), 2)
            
            # 使用单个连接执行所有查询以提高效率
            with sqlite3.connect(db.db_path) as conn:
                # 查询不同时间级别的统计数据
                day_count = pd.read_sql_query("SELECT COUNT(*) as count FROM kline_day", conn).iloc[0]['count']
                day_stock_count = pd.read_sql_query("SELECT COUNT(DISTINCT code) as count FROM kline_day", conn).iloc[0]['count']
                day_max_date = pd.read_sql_query("SELECT MAX(date) as max_date FROM kline_day", conn).iloc[0]['max_date']
                
                m30_count = pd.read_sql_query("SELECT COUNT(*) as count FROM kline_30m", conn).iloc[0]['count']
                m30_stock_count = pd.read_sql_query("SELECT COUNT(DISTINCT code) as count FROM kline_30m", conn).iloc[0]['count']
                m30_max_date = pd.read_sql_query("SELECT MAX(date) as max_date FROM kline_30m", conn).iloc[0]['max_date']
                
                m5_count = pd.read_sql_query("SELECT COUNT(*) as count FROM kline_5m", conn).iloc[0]['count']
                m5_stock_count = pd.read_sql_query("SELECT COUNT(DISTINCT code) as count FROM kline_5m", conn).iloc[0]['count']
                m5_max_date = pd.read_sql_query("SELECT MAX(date) as max_date FROM kline_5m", conn).iloc[0]['max_date']
                
                m1_count = pd.read_sql_query("SELECT COUNT(*) as count FROM kline_1m", conn).iloc[0]['count']
                m1_stock_count = pd.read_sql_query("SELECT COUNT(DISTINCT code) as count FROM kline_1m", conn).iloc[0]['count']
                m1_max_date = pd.read_sql_query("SELECT MAX(date) as max_date FROM kline_1m", conn).iloc[0]['max_date']
            
            # 显示统计信息
            self.log_text.append("📈 数据库当前统计:")
            self.log_text.append(f"  数据库大小: {db_size_mb} MB")
            self.log_text.append(f"  日线数据: {day_stock_count} 只股票, {day_count} 条记录, 最近更新: {day_max_date or '无数据'}")
            self.log_text.append(f"  30分钟线数据: {m30_stock_count} 只股票, {m30_count} 条记录, 最近更新: {m30_max_date or '无数据'}")
            self.log_text.append(f"  5分钟线数据: {m5_stock_count} 只股票, {m5_count} 条记录, 最近更新: {m5_max_date or '无数据'}")
            self.log_text.append(f"  1分钟线数据: {m1_stock_count} 只股票, {m1_count} 条记录, 最近更新: {m1_max_date or '无数据'}")
            
        except Exception as e:
            self.log_text.append(f"⚠️ 获取数据库统计信息失败: {str(e)}")

    def on_start_scan_clicked(self):
        """处理开始扫描按钮点击"""
        self.log_text.append("🔍 开始执行扫描...")
        
        try:
            # 获取配置
            config = self.get_chan_config()
            kl_type = self.get_timeframe_kl_type()
            
            # 从数据库获取股票列表
            from DataAPI.SQLiteAPI import CChanDB
            db = CChanDB()
            
            # 根据自选股分组选择获取股票列表
            selected_watchlist = self.watchlist_combo.currentText()
            
            # 根据选择的分组构建查询条件
            if selected_watchlist not in ["沪深", "港股通", "全部"] and selected_watchlist != "加载中...":
                # 如果选择的是自定义分组，则尝试从富途API获取具体的自选股列表
                try:
                    from futu import OpenQuoteContext, RET_OK
                    import os
                    FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
                    
                    quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
                    ret, data = quote_ctx.get_user_security(selected_watchlist)
                    
                    if ret == RET_OK and not data.empty:
                        codes = data['code'].tolist()
                        if codes:
                            # 构建查询条件，只获取自选股的数据
                            code_placeholders = ','.join([f"'{code}'" for code in codes])
                            stock_query = f"SELECT DISTINCT code FROM kline_day WHERE code IN ({code_placeholders})"
                        else:
                            self.log_text.append(f"⚠️ 自选股分组 '{selected_watchlist}' 中没有股票")
                            quote_ctx.close()
                            return
                    else:
                        self.log_text.append(f"⚠️ 获取自选股列表失败: {data}")
                        # 如果富途API获取失败，回退到查询所有股票
                        stock_query = "SELECT DISTINCT code FROM kline_day"
                        
                    quote_ctx.close()
                except Exception as e:
                    self.log_text.append(f"⚠️ 获取富途自选股时出错: {str(e)}")
                    # 出错时回退到查询所有股票
                    stock_query = "SELECT DISTINCT code FROM kline_day"
            else:
                # 如果选择的是预设分组，则使用相应的筛选条件
                stock_query = "SELECT DISTINCT code FROM kline_day"
                
                # 根据选择的分组应用不同的筛选条件
                if selected_watchlist == "沪深":
                    stock_query += " WHERE code LIKE 'SH.%' OR code LIKE 'SZ.%'"
                elif selected_watchlist == "港股通":
                    stock_query += " WHERE code LIKE 'HK.%'"
                elif selected_watchlist == "全部":
                    # 查询所有股票，不做额外筛选
                    pass
            try:
                stock_df = db.execute_query(stock_query)
            except Exception as db_error:
                self.log_text.append(f"⚠️ 读取数据库时出现问题: {str(db_error)}")
                stock_df = pd.DataFrame(columns=['code'])  # 创建空的DataFrame
            
            if stock_df.empty or stock_df['code'].empty:
                self.log_text.append("⚠️ 数据库中没有股票数据，尝试从富途或akshare获取实时股票列表...")
                # 回退到在线模式，使用 get_tradable_stocks() 获取股票列表
                stock_list = get_tradable_stocks()
                if stock_list.empty:
                    self.log_text.append("❌ 无法获取股票列表，请检查网络连接或富途API配置")
                    return
                else:
                    self.log_text.append(f"✅ 成功获取 {len(stock_list)} 只可交易股票，使用在线模式进行扫描...")
                    # 使用在线扫描数据源
                    data_src = DATA_SRC.FUTU
            else:
                # 添加模拟的股票名称和价格信息
                stock_list = pd.DataFrame({
                    '代码': stock_df['code'].tolist(),
                    '名称': [f'股票_{code.split(".")[-1]}' for code in stock_df['code'].tolist()],
                    '最新价': [10.0] * len(stock_df),
                    '涨跌幅': [0.0] * len(stock_df)
                })
                # 使用离线扫描数据源
                data_src = "custom:SQLiteAPI.SQLiteAPI"
            
            self.log_text.append(f"📊 准备扫描 {len(stock_list)} 只股票 (来自: {selected_watchlist})...")
            
            # 获取用户输入的天数
            try:
                days_text = self.days_input.text().strip()
                if days_text:
                    days = int(days_text)
                    if days <= 0:
                        days = 30  # 如果输入不合法，默认为30天
                else:
                    days = 30  # 如果没有输入，默认为30天
            except ValueError:
                days = 30  # 如果转换失败，默认为30天
                self.log_text.append(f"⚠️ 天数输入格式不正确，使用默认值30天")
            
            # 启动扫描线程
            self.scan_thread = ScanThread(stock_list, config, days=days, kl_type=kl_type, data_src=data_src)
            self.scan_thread.progress.connect(self.on_scan_progress)
            self.scan_thread.found_signal.connect(self.on_buy_point_found)
            self.scan_thread.finished.connect(self.on_scan_finished)
            self.scan_thread.log_signal.connect(self.on_log_message)
            self.scan_thread.start()
            
            # 显示进度条
            self.progress_bar.setVisible(True)
            self.progress_bar.setMaximum(len(stock_list))
            
        except Exception as e:
            self.log_text.append(f"❌ 扫描启动失败: {str(e)}")
            import traceback
            self.log_text.append(f"详细错误: {traceback.format_exc()}")

    def on_result_table_clicked(self, item):
        """处理扫描结果表格点击"""
        row = item.row()
        code = self.result_table.item(row, 0).text()
        self.stock_code_input.setText(code)
        self.on_load_multi_chart_clicked()

    def on_load_multi_chart_clicked(self):
        """加载四个级别的图表"""
        code = self.stock_code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "警告", "请输入股票代码！")
            return
        
        normalized_code = normalize_stock_code(code)
        self.log_text.append(f"📈 正在加载 {normalized_code} 的全级别图表...")
        
        try:
            config = self.get_chan_config()
            
            try:
                days_text = self.days_input.text().strip()
                days = int(days_text) if days_text else 30
            except ValueError:
                days = 30
            
            # 数据源由 SingleAnalysisThread 根据代码自动选择最优优先级
            data_sources = None
            
            kl_types = [KL_TYPE.K_DAY, KL_TYPE.K_30M, KL_TYPE.K_5M, KL_TYPE.K_1M]
            
            # 使用 SingleAnalysisThread 返回多个 timeframe
            self.analysis_thread = SingleAnalysisThread(normalized_code, config, kl_types=kl_types, days=days, data_sources=data_sources)
            self.analysis_thread.finished.connect(self.on_analysis_finished)
            self.analysis_thread.error.connect(self.on_analysis_error)
            self.analysis_thread.log_signal.connect(self.on_log_message)
            self.analysis_thread.start()
            
        except Exception as e:
            self.log_text.append(f"❌ 图表加载失败: {str(e)}")

    def on_log_message(self, message):
        """处理日志消息"""
        self.log_text.append(message)

    def on_stop_db_clicked(self):
        """处理停止更新按钮点击"""
        if hasattr(self, 'update_db_thread') and self.update_db_thread and self.update_db_thread.isRunning():
            self.update_db_thread.stop()
            self.stop_db_btn.setEnabled(False)
            self.log_text.append("🛑 正在发送停止信号给数据下载线程...")

    def on_update_database_finished(self, success, message):
        """处理数据库更新完成"""
        if success:
            self.log_text.append(f"✅ {message}")
            self.last_update_label.setText(f"上次更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        else:
            self.log_text.append(f"❌ {message}")
        
        # 重新启用按钮
        self.update_db_btn.setEnabled(True)
        self.stop_db_btn.setEnabled(False)

    def on_scan_progress(self, current, total, stock_info):
        """处理扫描进度"""
        self.progress_bar.setValue(current)
        self.statusBar().showMessage(f'扫描进度: {current}/{total} - {stock_info}')

    def on_buy_point_found(self, data):
        """处理发现买点或卖点"""
        # 在结果表格中添加一行
        row_position = self.result_table.rowCount()
        self.result_table.insertRow(row_position)
        
        self.result_table.setItem(row_position, 0, QTableWidgetItem(data['code']))
        self.result_table.setItem(row_position, 1, QTableWidgetItem(data['name']))
        self.result_table.setItem(row_position, 2, QTableWidgetItem(data['bsp_type']))
        self.result_table.setItem(row_position, 3, QTableWidgetItem(data['bsp_time']))

    def on_scan_finished(self, success_count, fail_count):
        """处理扫描完成"""
        self.log_text.append(f"✅ 扫描完成！成功: {success_count}, 失败: {fail_count}")
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage('扫描完成')

    # ─── 级别名称映射 ───
    KL_NAME_MAP = {
        "K_DAY": "日线",
        "K_30M": "30分钟",
        "K_5M": "5分钟",
        "K_1M": "1分钟",
    }
    TF_NAMES = ["日线", "30分钟", "5分钟", "1分钟"]

    def on_analysis_finished(self, chan_results):
        """处理多级别图表分析完成（延迟渲染：只渲染当前标签页）"""
        try:
            if not chan_results:
                self.log_text.append("❌ 分析结果为空")
                return

            self.log_text.append(f"📊 获取到 {len(chan_results)} 个级别的数据，准备渲染...")
            import matplotlib.pyplot as plt
            plt.close('all')

            # 缓存分析结果并清除已渲染标记
            self._chan_results = chan_results
            self._rendered_tabs = set()

            # 生成汇总信息
            details_text = "缠论分析完成！\n\n"
            first_chan = list(chan_results.values())[0]
            details_text += f"股票: {first_chan.code}\n"
            details_text += f"时间范围: {first_chan.begin_time} - {first_chan.end_time}\n"
            for kl_name, chan in chan_results.items():
                tf_name = self.KL_NAME_MAP.get(kl_name, kl_name)
                if len(chan.lv_list) == 0:
                    continue
                first_lv = chan.lv_list[0]
                kl_data = list(chan[first_lv])
                first_lv_data = chan[first_lv]
                bi_count = len(list(first_lv_data.bi_list)) if hasattr(first_lv_data, 'bi_list') and first_lv_data.bi_list is not None else 0
                seg_count = len(list(first_lv_data.seg_list)) if hasattr(first_lv_data, 'seg_list') and first_lv_data.seg_list is not None else 0
                zs_count = len(list(first_lv_data.zs_list)) if hasattr(first_lv_data, 'zs_list') and first_lv_data.zs_list is not None else 0
                details_text += f"[{tf_name}] 数据源: {chan.data_src} | K线: {len(kl_data)} | 笔: {bi_count} | 段: {seg_count} | 中枢: {zs_count}\n"
            self.analysis_detail_text.setPlainText(details_text)

            # 只渲染当前激活的标签页
            current_idx = self.charts_tabs.currentIndex()
            if 0 <= current_idx < len(self.TF_NAMES):
                current_tf = self.TF_NAMES[current_idx]
                self._render_tab_by_name(current_tf)

            self.log_text.append("✅ 当前标签页图表渲染完成（其他级别将在切换时加载）")

        except Exception as e:
            self.log_text.append(f"❌ 渲染图表失败: {str(e)}")
            import traceback
            self.log_text.append(f"详细错误: {traceback.format_exc()}")

    def _on_chart_tab_changed(self, index):
        """标签页切换时按需渲染对应图表"""
        if index < 0 or index >= len(self.TF_NAMES):
            return
        tf_name = self.TF_NAMES[index]
        if tf_name not in self._rendered_tabs and self._chan_results:
            self.log_text.append(f"📊 正在渲染 {tf_name} 图表...")
            self._render_tab_by_name(tf_name)
            self.log_text.append(f"✅ {tf_name} 渲染完成")

    def _render_tab_by_name(self, tf_name):
        """渲染指定标签页的图表"""
        # 反查 kl_name
        reverse_map = {v: k for k, v in self.KL_NAME_MAP.items()}
        kl_name = reverse_map.get(tf_name)
        if not kl_name or kl_name not in self._chan_results:
            return

        chan = self._chan_results[kl_name]
        if tf_name not in self.tf_frames or len(chan.lv_list) == 0:
            return

        tf_frame = self.tf_frames[tf_name]
        tf_layout = tf_frame.layout()

        first_lv = chan.lv_list[0]

        x_range_map = {"日线": 250, "30分钟": 630, "5分钟": 660, "1分钟": 1100}
        x_range = x_range_map.get(tf_name, 150)

        fig_width = max(5, tf_frame.width() / 100)
        fig_height = max(3, tf_frame.height() / 100)

        plot_para = {
            "figure": {
                "x_range": x_range,
                "w": fig_width,
                "h": fig_height,
            }
        }
        plot_config = {
            "plot_kline": True, "plot_kline_combine": True,
            "plot_bi": True, "plot_seg": True, "plot_zs": True,
            "plot_macd": True, "plot_bsp": True,
        }

        try:
            plot_driver = CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)

            # 清理旧的 canvas
            while tf_layout.count() > 0:
                item = tf_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            new_canvas = FigureCanvas(plot_driver.figure)
            new_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            tf_layout.addWidget(new_canvas)

            self._rendered_tabs.add(tf_name)
        except Exception as e:
            self.log_text.append(f"❌ 渲染 {tf_name} 失败: {str(e)}")

    def on_analysis_error(self, error_msg):
        """处理分析错误"""
        self.log_text.append(f"❌ 图表分析失败: {error_msg}")

    def load_futu_watchlists(self):
        """加载富途自选股分组列表"""
        try:
            from futu import OpenQuoteContext, RET_OK
            # 从环境变量或配置文件获取富途API地址
            import os
            FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
            
            # 创建富途API连接
            quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
            
            # 获取所有自选股分组
            ret, data = quote_ctx.get_user_security_group()
            if ret == RET_OK:
                groups = data.to_dict('records')
                group_names = [group['group_name'] for group in groups if group['group_name'].strip()]
                
                # 更新下拉菜单选项
                self.watchlist_combo.clear()
                self.watchlist_combo.addItems(group_names)
                
                if hasattr(self, 'monitor_watchlist_combo'):
                    self.monitor_watchlist_combo.clear()
                    self.monitor_watchlist_combo.addItems(group_names)
                    idx = self.monitor_watchlist_combo.findText("沪深")
                    if idx >= 0: self.monitor_watchlist_combo.setCurrentIndex(idx)
                    
                if hasattr(self, 'us_watchlist_combo'):
                    self.us_watchlist_combo.clear()
                    self.us_watchlist_combo.addItems(group_names)
                    idx = self.us_watchlist_combo.findText("美股")
                    if idx >= 0: self.us_watchlist_combo.setCurrentIndex(idx)
                
                if hasattr(self, 'hk_watchlist_combo'):
                    self.hk_watchlist_combo.clear()
                    self.hk_watchlist_combo.addItems(group_names)
                    idx = self.hk_watchlist_combo.findText("港股")
                    if idx >= 0: self.hk_watchlist_combo.setCurrentIndex(idx)
                    
                
                # 安全地写入日志
                if hasattr(self, 'log_text'):
                    self.log_text.append(f"✅ 成功加载 {len(group_names)} 个自选股分组")
                    
                # 关闭连接
                quote_ctx.close()
                return group_names
            else:
                # 安全地写入日志
                if hasattr(self, 'log_text'):
                    self.log_text.append(f"❌ 获取自选股分组失败: {data}")
                    
                # 关闭连接
                quote_ctx.close()
                return []
        except ImportError:
            # 如果没有futu模块，添加默认选项
            default_groups = ["沪深", "港股通", "全部", "自选股1", "自选股2"]
            self.watchlist_combo.clear()
            self.watchlist_combo.addItems(default_groups)
            
            # 安全地写入日志
            if hasattr(self, 'log_text'):
                self.log_text.append(f"⚠️ 未安装futu-api模块，使用默认分组选项。如需使用富途自选股，请安装futu-api模块。")
            return default_groups
        except Exception as e:
            # 安全地写入日志
            if hasattr(self, 'log_text'):
                self.log_text.append(f"❌ 加载自选股分组时出错: {str(e)}")
                import traceback
                self.log_text.append(f"详细错误: {traceback.format_exc()}")
            return []

    def closeEvent(self, event):
        """窗口关闭处理事件，确保安全退出所有线程"""
        if hasattr(self, 'log_text'):
            self.log_text.append("🛑 正在关闭程序...")
        
        # 停止所有子线程
        if hasattr(self, 'update_db_thread') and self.update_db_thread and self.update_db_thread.isRunning():
            self.update_db_thread.stop()
            self.update_db_thread.wait(2000)
            
        if hasattr(self, 'scan_thread') and self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()
            self.scan_thread.wait(2000)
            
        if hasattr(self, 'analysis_thread') and self.analysis_thread and self.analysis_thread.isRunning():
            self.analysis_thread.wait(2000)
            
        if hasattr(self, 'repair_thread') and self.repair_thread and self.repair_thread.isRunning():
            self.repair_thread.stop()
            self.repair_thread.wait(2000)
            
        # 停止监控
        if hasattr(self, 'futu_monitor') and self.futu_monitor:
            try:
                self.futu_monitor.stop()
            except:
                pass
                
        if hasattr(self, 'hk_trading_controller') and self.hk_trading_controller:
            try:
                self.hk_trading_controller.stop()
            except:
                pass

        if hasattr(self, 'us_trading_controller') and self.us_trading_controller:
            try:
                self.us_trading_controller.stop()
            except:
                pass
                
        event.accept()

def main():
    """程序入口函数"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = TraderGUI()
    window.show()
    
    # 确保在窗口显示后按钮是可见的
    window.ensure_buttons_visible()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()