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
    QGridLayout, QHeaderView, QProgressDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
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
except ImportError:
    HKTradingController = None

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
        # 确保按钮在界面显示后是可见的
        self.ensure_buttons_visible()
        
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
        
        self.data_source_combo = QComboBox()
        self.data_source_combo.addItems(["Futu优先", "SQLite数据库"])
        manual_layout.addWidget(QLabel("数据源:"))
        manual_layout.addWidget(self.data_source_combo)
        
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

        # --- 基础设置 ---
        base_settings_group = QGroupBox("基础设置")
        base_settings_layout = QVBoxLayout()
        self.bi_strict_cb = QCheckBox("笔严格模式")
        self.bi_strict_cb.setChecked(True)
        base_settings_layout.addWidget(self.bi_strict_cb)
        self.data_source_label = QLabel("数据源: SQLite (离线)")
        base_settings_layout.addWidget(self.data_source_label)
        base_settings_group.setLayout(base_settings_layout)
        layout.addWidget(base_settings_group)

        # --- 自动化模块 ---
        auto_group = QGroupBox("自动化模块")
        auto_layout = QVBoxLayout()
        
        # 富途监控控制
        futu_layout = QHBoxLayout()
        self.futu_monitor_status = QLabel("Futu监控: [未启动]")
        self.futu_monitor_btn = QPushButton("启动监控")
        self.futu_monitor_btn.clicked.connect(self.toggle_futu_monitor)
        futu_layout.addWidget(self.futu_monitor_status)
        futu_layout.addWidget(self.futu_monitor_btn)
        futu_layout.addStretch()
        auto_layout.addLayout(futu_layout)
        
        # 港股自动交易控制
        hk_auto_layout = QHBoxLayout()
        self.hk_auto_status = QLabel("港股自动交易: [未启动]")
        self.hk_auto_btn = QPushButton("启动自动交易")
        self.hk_auto_btn.clicked.connect(self.toggle_hk_trading)
        hk_auto_layout.addWidget(self.hk_auto_status)
        hk_auto_layout.addWidget(self.hk_auto_btn)
        
        # 资金查询按钮
        self.query_funds_btn = QPushButton("刷新账户资金")
        self.query_funds_btn.clicked.connect(self.on_query_funds_clicked)
        hk_auto_layout.addWidget(self.query_funds_btn)
        
        # 一键清仓按钮
        self.liquidate_btn = QPushButton("一键清仓")
        self.liquidate_btn.clicked.connect(self.on_liquidate_clicked)
        self.liquidate_btn.setStyleSheet("background-color: #ff4d4f; color: white; font-weight: bold;")
        hk_auto_layout.addWidget(self.liquidate_btn)
        
        hk_auto_layout.addStretch()
        auto_layout.addLayout(hk_auto_layout)
        
        # 自动化专属日志及信息显示
        self.auto_log_text = QTextEdit()
        self.auto_log_text.setReadOnly(True)
        self.auto_log_text.setPlaceholderText("自动化模块运行日志及账户信息将显示在此处...")
        self.auto_log_text.setMinimumHeight(200)
        auto_layout.addWidget(self.auto_log_text)
        
        auto_group.setLayout(auto_layout)
        layout.addWidget(auto_group)

        layout.addStretch()
        
    def append_auto_log(self, text):
        """添加日志到自动化专属日志区域"""
        import datetime
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.auto_log_text.append(f"[{now}] {text}")

    def toggle_futu_monitor(self):
        """切换富途实时监控状态"""
        if self.futu_monitor is None:
            try:
                group_name = self.watchlist_combo.currentText()
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
                group_name = self.watchlist_combo.currentText()
                self.hk_trading_controller = HKTradingController(hk_watchlist_group=group_name)
                self.hk_trading_controller.log_message.connect(self.append_auto_log)
                
                # 在新线程中运行策略
                import threading
                def run_trade():
                    self.hk_trading_controller.run_scan_and_trade()
                    
                self.hk_trade_thread = threading.Thread(target=run_trade, daemon=True)
                self.hk_trade_thread.start()
                
                self.hk_auto_status.setText("港股自动交易: [运行中]")
                self.hk_auto_btn.setText("停止自动交易")
                self.append_auto_log("✅ 港股自动交易已启动。注意：此策略主要进行30M级别的突破和背驰判断，结合风险管理器控制仓位。")
            except Exception as e:
                self.append_auto_log(f"❌ 启动港股自动交易失败: {e}")
                self.hk_trading_controller = None
        else:
            self.hk_trading_controller.stop()
            self.hk_trading_controller = None
            self.hk_auto_status.setText("港股自动交易: [已停止]")
            self.hk_auto_btn.setText("启动自动交易")
            self.append_auto_log("ℹ️ 港股自动交易已停止")
            
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
            funds = temp_controller.get_available_funds()
            
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
            
            # 安全终止活动线程
            if hasattr(self, 'update_db_thread') and self.update_db_thread and self.update_db_thread.isRunning():
                self.update_db_thread.stop()
                self.update_db_thread.wait(1000)
            
            # 使用 os.execl 重生新进程
            os.execl(sys.executable, sys.executable, *sys.argv)

    def get_chan_config(self):
        """获取缠论配置"""
        config = CChanConfig()
        config.bNewStyle = True  # 新笔模式
        config.bi_strict = self.bi_strict_cb.isChecked()  # 笔严格模式
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
        start_date = self.start_date_input.date().toString("yyyy-MM-dd")
        end_date = self.end_date_input.date().toString("yyyy-MM-dd")
        
        # 从本地获取股票列表，根据自选股分组选择
        try:
            from DataAPI.SQLiteAPI import CChanDB
            db = CChanDB()
            
            # 显示数据库当前统计信息
            self.display_db_stats(db)
            
            # 获取自选股分组选择
            selected_watchlist = self.watchlist_combo.currentText()
            
            # 根据选择的分组构建查询条件
            if selected_watchlist not in ["沪深A股", "港股通", "全部"] and selected_watchlist != "加载中...":
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
                if selected_watchlist == "沪深A股":
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
            if selected_watchlist not in ["沪深A股", "港股通", "全部"] and selected_watchlist != "加载中...":
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
                if selected_watchlist == "沪深A股":
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
            
            selected_data_source = self.data_source_combo.currentText()
            if selected_data_source == "Futu优先":
                data_sources = [DATA_SRC.FUTU, "custom:SQLiteAPI.SQLiteAPI"]
            else:
                data_sources = ["custom:SQLiteAPI.SQLiteAPI", DATA_SRC.FUTU]
            
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

    def on_analysis_finished(self, chan_results):
        """处理多级别图表分析完成"""
        try:
            if not chan_results:
                self.log_text.append("❌ 分析结果为空")
                return

            self.log_text.append(f"📊 获取到 {len(chan_results)} 个级别的图表，正在渲染...")
            import matplotlib.pyplot as plt
            
            details_text = "缠论分析完成！\n\n"
            first_chan = list(chan_results.values())[0]
            details_text += f"股票: {first_chan.code}\n"
            details_text += f"时间范围: {first_chan.begin_time} - {first_chan.end_time}\n"
            
            # 各级别 x_range 设置
            x_range_map = {
                "日线": 350,
                "30分钟": 350,
                "5分钟": 350,
                "1分钟": 350,
            }
            
            kl_name_map = {
                "K_DAY": "日线",
                "K_30M": "30分钟",
                "K_5M": "5分钟",
                "K_1M": "1分钟"
            }

            plt.close('all')

            for kl_name, chan in chan_results.items():
                tf_name = kl_name_map.get(kl_name)
                if not tf_name or tf_name not in self.tf_frames:
                    continue
                
                tf_frame = self.tf_frames[tf_name]
                tf_layout = tf_frame.layout()
                
                if len(chan.lv_list) == 0:
                    continue
                    
                first_lv = chan.lv_list[0]
                kl_data = list(chan[first_lv])
                
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
                plot_driver = CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)
                
                # 清理旧的canvas
                while tf_layout.count() > 0:
                    item = tf_layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                
                # 重新创建图表，避免重影和缩放问题
                new_canvas = FigureCanvas(plot_driver.figure)
                new_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                
                tf_layout.addWidget(new_canvas)
                
                first_lv_data = chan[first_lv]
                bi_count = len(list(first_lv_data.bi_list)) if hasattr(first_lv_data, 'bi_list') and first_lv_data.bi_list is not None else 0
                seg_count = len(list(first_lv_data.seg_list)) if hasattr(first_lv_data, 'seg_list') and first_lv_data.seg_list is not None else 0
                zs_count = len(list(first_lv_data.zs_list)) if hasattr(first_lv_data, 'zs_list') and first_lv_data.zs_list is not None else 0
                details_text += f"[{tf_name}] 数据源: {chan.data_src} | K线: {len(kl_data)} | 笔: {bi_count} | 段: {seg_count} | 中枢: {zs_count}\n"
                
            self.analysis_detail_text.setPlainText(details_text)
            self.log_text.append("✅ 图表渲染完成")
            
        except Exception as e:
            self.log_text.append(f"❌ 渲染图表失败: {str(e)}")
            import traceback
            self.log_text.append(f"详细错误: {traceback.format_exc()}")

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
            default_groups = ["沪深A股", "港股通", "全部", "自选股1", "自选股2"]
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