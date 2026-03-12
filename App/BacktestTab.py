import sys
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit,
    QPushButton, QTextEdit, QComboBox, QSplitter, QScrollArea, QFrame,
    QDateTimeEdit, QMessageBox, QStyledItemDelegate
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QEvent
from PyQt6.QtGui import QPixmap, QStandardItemModel, QPalette, QStandardItem

# 解决跨级导入问题
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backtesting.enhanced_backtester import EnhancedBacktestEngine
from scripts.analyze_results import BacktestAnalyzer

logger = logging.getLogger(__name__)


class CheckableComboBox(QComboBox):
    """支持多选的下拉框"""
    item_checked_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("请选择股票 (最多5只)")
        
        # 允许多行文本显示
        palette = self.lineEdit().palette()
        palette.setColor(QPalette.ColorRole.Base, palette.color(QPalette.ColorRole.Window))
        self.lineEdit().setPalette(palette)
        
        self.model = QStandardItemModel(self)
        self.setModel(self.model)
        self.view().pressed.connect(self.handleItemPressed)
        self._max_selections = 5
        self._internal_updating = False

    def handleItemPressed(self, index):
        item = self.model.itemFromIndex(index)
        if item.flags() & Qt.ItemFlag.ItemIsEnabled == 0:
            return
            
        if item.checkState() == Qt.CheckState.Checked:
            item.setCheckState(Qt.CheckState.Unchecked)
        else:
            # 检查是否超过最大限制
            checked_count = len(self.get_checked_items())
            if checked_count >= self._max_selections:
                QMessageBox.warning(self, "警告", f"最多只能选择 {self._max_selections} 只股票！")
                return
            item.setCheckState(Qt.CheckState.Checked)
            
        self.update_text()
        self.item_checked_changed.emit()

    def update_text(self):
        checked_items = self.get_checked_items()
        if checked_items:
            self.lineEdit().setText(", ".join(checked_items))
        else:
            self.lineEdit().setText("")

    def addItems(self, texts, checked_texts=None):
        if checked_texts is None:
            checked_texts = []
            
        self._internal_updating = True
        for text in texts:
            self.addItem(text, text in checked_texts)
        self._internal_updating = False
        self.update_text()

    def addItem(self, text, checked=False):
        item = QStandardItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        item.setData(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
        self.model.appendRow(item)

    def get_checked_items(self):
        checked_items = []
        for i in range(self.model.rowCount()):
            item = self.model.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                checked_items.append(item.text())
        return checked_items
        
    def clear(self):
        self.model.clear()
        self.update_text()


class BacktestRunnerThread(QThread):
    """后台运行回测的线程"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, dict, str)  # success, results, message

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            self.progress.emit("🚀 正在初始化增强版回测引擎...")
            engine = EnhancedBacktestEngine(
                initial_funds=self.config.get('initial_funds', 100000),
                start_date=self.config.get('start_date', '2024-01-01'),
                end_date=self.config.get('end_date', '2025-12-31'),
                watchlist=self.config.get('watchlist', []),
                use_hk_costs=True,
                use_ml=self.config.get('use_ml', False)
            )
            
            self.progress.emit(f"📊 准备回测 {len(self.config.get('watchlist', []))} 只股票...")
            results = engine.run()
            
            if 'error' in results:
                self.finished.emit(False, {}, f"回测失败: {results['error']}")
                return

            self.progress.emit("✅ 回测完成，正在从内存中生成分析报告和图表...")
            
            # 使用现有逻辑保存结果
            output_dir = "backtest_reports"
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            json_file = os.path.join(output_dir, f"results_{timestamp}.json")
            
            # 由于 engine.run() 返回的字典已包含 equity_curve 和 trade_log，直接序列化保存
            import json
            import subprocess
            
            def _json_serializer(obj):
                """处理不可序列化的对象"""
                if hasattr(obj, 'isoformat'):
                    return obj.isoformat()
                if hasattr(obj, 'item'):  # numpy types
                    return obj.item()
                return str(obj)
            
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, default=_json_serializer, indent=2, ensure_ascii=False)
            
            # 生成图表 (通过独立进程，避免 macOS 上的 Matplotlib 线程冲突)
            script_path = os.path.join(str(Path(__file__).resolve().parent.parent), "scripts", "analyze_results.py")
            cmd = [sys.executable, script_path, json_file, "--output-dir", output_dir]
            
            subprocess.run(cmd, check=True, capture_output=True)
            
            # CLI 生成的是固定文件名，根据时间戳重命名
            generated_equity = os.path.join(output_dir, "equity_curve.png")
            generated_dist = os.path.join(output_dir, "trade_distribution.png")
            generated_report = os.path.join(output_dir, "analysis_report.md")
            
            equity_curve_path = os.path.join(output_dir, f"equity_curve_{timestamp}.png")
            trade_dist_path = os.path.join(output_dir, f"trade_distribution_{timestamp}.png")
            report_path = os.path.join(output_dir, f"report_{timestamp}.md")
            
            if os.path.exists(generated_equity):
                os.rename(generated_equity, equity_curve_path)
            if os.path.exists(generated_dist):
                os.rename(generated_dist, trade_dist_path)
            if os.path.exists(generated_report):
                os.rename(generated_report, report_path)
            
            results['equity_curve_path'] = equity_curve_path
            results['trade_dist_path'] = trade_dist_path
            
            self.finished.emit(True, results, "回测及分析图表生成成功！")
        except Exception as e:
            logger.exception("回测线程执行异常")
            self.finished.emit(False, {}, f"执行异常: {str(e)}")


class BacktestTab(QWidget):
    """回测模块界面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.backtest_thread = None

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # === 左侧：配置与日志 ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- 1. 参数配置 ---
        config_group = QGroupBox("1. 回测参数配置")
        config_layout = QVBoxLayout()
        
        # 初始资金
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("初始资金 (HKD):"))
        self.initial_funds_input = QLineEdit("100000")
        h1.addWidget(self.initial_funds_input)
        config_layout.addLayout(h1)
        
        # 时间范围
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("开始日期:"))
        self.start_date_input = QDateTimeEdit()
        self.start_date_input.setCalendarPopup(True)
        self.start_date_input.setDate((datetime.now() - timedelta(days=365)).date())
        h2.addWidget(self.start_date_input)
        
        h2.addWidget(QLabel("结束日期:"))
        self.end_date_input = QDateTimeEdit()
        self.end_date_input.setCalendarPopup(True)
        self.end_date_input.setDate(datetime.now().date())
        h2.addWidget(self.end_date_input)
        config_layout.addLayout(h2)
        
        # 选择自选股分组以加载股票
        h_group = QHBoxLayout()
        h_group.addWidget(QLabel("从分组加载:"))
        self.watchlist_group_combo = QComboBox()
        self.watchlist_group_combo.addItem("加载中...")
        self.watchlist_group_combo.currentTextChanged.connect(self.on_watchlist_group_changed)
        h_group.addWidget(self.watchlist_group_combo)
        
        self.refresh_group_btn = QPushButton("刷新分组")
        self.refresh_group_btn.clicked.connect(self.load_futu_groups)
        self.refresh_group_btn.setMaximumWidth(80)
        h_group.addWidget(self.refresh_group_btn)
        config_layout.addLayout(h_group)
        
        # 多选股票列表
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("回测股票 (限1-5只):"))
        self.stocks_combo = CheckableComboBox()
        self.stocks_combo.setMinimumWidth(250)
        h3.addWidget(self.stocks_combo)
        config_layout.addLayout(h3)
        
        # 并发初始化加载分组
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self.load_futu_groups)
        
        # 策略选择 (为下一步 ML 增强预留)
        h4 = QHBoxLayout()
        h4.addWidget(QLabel("测试策略:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["标准缠论策略 (Standard)", "机器学习增强策略 (ML-Enhanced, 待接入)"])
        h4.addWidget(self.strategy_combo)
        config_layout.addLayout(h4)
        
        # 操作按钮
        self.run_btn = QPushButton("🚀 开始回测")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; font-size: 14px;")
        self.run_btn.clicked.connect(self.run_backtest)
        config_layout.addWidget(self.run_btn)
        
        config_group.setLayout(config_layout)
        left_layout.addWidget(config_group)
        
        # --- 2. 运行日志 ---
        log_group = QGroupBox("2. 回测日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        left_layout.addWidget(log_group, stretch=1)
        
        # === 右侧：结果展示 ===
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 核心指标
        metrics_group = QGroupBox("核心指标 (Metrics)")
        metrics_layout = QHBoxLayout()
        
        self.lbl_total_return = QLabel("总回报: -")
        self.lbl_ann_return = QLabel("年化回报: -")
        self.lbl_max_dd = QLabel("最大回撤: -")
        self.lbl_win_rate = QLabel("胜率: -")
        self.lbl_pl_ratio = QLabel("盈亏比: -")
        
        for lbl in [self.lbl_total_return, self.lbl_ann_return, self.lbl_max_dd, self.lbl_win_rate, self.lbl_pl_ratio]:
            lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
            metrics_layout.addWidget(lbl)
            
        # 刷新按钮
        self.refresh_btn = QPushButton("🔄 刷新最新结果")
        self.refresh_btn.setFixedWidth(120)
        self.refresh_btn.clicked.connect(self.load_latest_report)
        metrics_layout.addWidget(self.refresh_btn)
            
        metrics_group.setLayout(metrics_layout)
        right_layout.addWidget(metrics_group)
        
        # 图表展示 (滚动区域以防图片过大)
        chart_scroll = QScrollArea()
        chart_scroll.setWidgetResizable(True)
        chart_content = QWidget()
        chart_layout = QVBoxLayout(chart_content)
        
        self.equity_curve_label = QLabel("资金曲线图表将显示在这里")
        self.equity_curve_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.equity_curve_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        self.equity_curve_label.setMinimumHeight(400)
        
        self.trade_dist_label = QLabel("交易分布图表将显示在这里")
        self.trade_dist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.trade_dist_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        self.trade_dist_label.setMinimumHeight(300)
        
        chart_layout.addWidget(self.equity_curve_label)
        chart_layout.addWidget(self.trade_dist_label)
        chart_layout.addStretch()
        
        chart_scroll.setWidget(chart_content)
        right_layout.addWidget(chart_scroll, stretch=1)
        
        # 组装分隔栏
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        
        main_layout.addWidget(splitter)

    def log(self, msg: str):
        time_str = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{time_str}] {msg}")

    def load_futu_groups(self):
        """加载富途自选股分组列表 (类似于 TraderGUI)"""
        try:
            from futu import OpenQuoteContext, RET_OK
            import os
            self.watchlist_group_combo.clear()
            self.watchlist_group_combo.addItem("正在连接富途...")
            
            FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
            quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
            
            ret, data = quote_ctx.get_user_security_group()
            if ret == RET_OK:
                groups = data.to_dict('records')
                group_names = [group['group_name'] for group in groups if group['group_name'].strip()]
                
                self.watchlist_group_combo.clear()
                self.watchlist_group_combo.addItems(["--请选择分组--"] + group_names)
                self.log("✅ 成功加载富途自选股分组")
            else:
                self.watchlist_group_combo.clear()
                self.watchlist_group_combo.addItem("--富途连接失败--")
                self.log(f"❌ 获取自选股分组失败: {data}")
            quote_ctx.close()
            
        except ImportError:
            self.watchlist_group_combo.clear()
            self.watchlist_group_combo.addItem("--未检测到futu-api--")
            self.log("⚠️ 未检测到 futu-api 模块，无法提供自选股分组此功能。")
        except Exception as e:
            self.watchlist_group_combo.clear()
            self.watchlist_group_combo.addItem("--出错--")
            self.log(f"❌ 加载分组出错: {str(e)}")

    def on_watchlist_group_changed(self, group_name):
        """当自选股分组切换时，加载该分组下的股票"""
        if group_name in ["", "加载中...", "正在连接富途...", "--请选择分组--", "--富途连接失败--", "--未检测到futu-api--", "--出错--"]:
            self.stocks_combo.clear()
            return
            
        try:
            from futu import OpenQuoteContext, RET_OK
            import os
            FUTU_OPEND_ADDRESS = os.getenv('FUTU_OPEND_ADDRESS', '127.0.0.1')
            quote_ctx = OpenQuoteContext(host=FUTU_OPEND_ADDRESS, port=11111)
            
            ret, data = quote_ctx.get_user_security(group_name)
            self.stocks_combo.clear()
            
            if ret == RET_OK and not data.empty:
                codes = data['code'].tolist()
                # 默认勾选前3个作为演示
                self.stocks_combo.addItems(codes, checked_texts=codes[:3])
                self.log(f"✅ 从 '{group_name}' 加载了 {len(codes)} 只股票")
            else:
                self.log(f"⚠️ 分组为空或获取失败: {data}")
                
            quote_ctx.close()
        except Exception as e:
            self.log(f"❌ 加载分组股票失败: {str(e)}")

    def update_metrics(self, results: dict):
        total_ret = results.get('total_return_pct', 0) * 100
        ann_ret = results.get('annualized_return', 0) * 100
        max_dd = results.get('max_drawdown_pct', 0) * 100
        win_rate = results.get('win_rate', 0) * 100
        pl_ratio = results.get('profit_loss_ratio', 0)
        
        self.lbl_total_return.setText(f"总回报: {total_ret:.2f}%")
        self.lbl_total_return.setStyleSheet(f"color: {'red' if total_ret > 0 else 'green'}; font-weight: bold;")
        
        self.lbl_ann_return.setText(f"年化: {ann_ret:.2f}%")
        self.lbl_ann_return.setStyleSheet(f"color: {'red' if ann_ret > 0 else 'green'}; font-weight: bold;")
        
        self.lbl_max_dd.setText(f"最大回撤: {max_dd:.2f}%")
        self.lbl_win_rate.setText(f"胜率: {win_rate:.1f}%")
        self.lbl_pl_ratio.setText(f"盈亏比: {pl_ratio:.2f}")
        
    def load_charts(self, equity_path: str, dist_path: str):
        if os.path.exists(equity_path):
            pixmap = QPixmap(equity_path)
            # 缩放适应宽度, 若宽度还没计算出来则用默认值 800
            target_w = self.equity_curve_label.width()
            if target_w < 100: target_w = 800
            self.equity_curve_label.setPixmap(pixmap.scaled(target_w, 800, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        
        if os.path.exists(dist_path):
            pixmap2 = QPixmap(dist_path)
            target_w = self.trade_dist_label.width()
            if target_w < 100: target_w = 800
            self.trade_dist_label.setPixmap(pixmap2.scaled(target_w, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def load_latest_report(self):
        """扫描目录并加载最新的回测报告"""
        output_dir = "backtest_reports"
        if not os.path.exists(output_dir):
            self.log("❌ 报告目录不存在")
            return
            
        files = [f for f in os.listdir(output_dir) if f.startswith("results_") and f.endswith(".json")]
        if not files:
            self.log("ℹ️ 未发现任何回测报告")
            return
            
        # 按文件名（含时间戳）排序，取最后一个
        files.sort()
        latest_file = os.path.join(output_dir, files[-1])
        
        try:
            with open(latest_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
            
            self.log(f"🔄 正在加载最新报告: {files[-1]}")
            self.update_metrics(results)
            
            # 自动推导图表路径 (由于保存时使用了相同时间戳)
            timestamp = files[-1].replace("results_", "").replace(".json", "")
            equity_path = os.path.join(output_dir, f"equity_curve_{timestamp}.png")
            dist_path = os.path.join(output_dir, f"trade_distribution_{timestamp}.png")
            
            self.load_charts(equity_path, dist_path)
            self.log("✅ 刷新成功")
        except Exception as e:
            self.log(f"❌ 加载报告失败: {str(e)}")

    def run_backtest(self):
        if self.backtest_thread and self.backtest_thread.isRunning():
            QMessageBox.warning(self, "警告", "已有回测任务正在运行，请稍候！")
            return
            
        try:
            initial_funds = float(self.initial_funds_input.text().strip())
        except ValueError:
            QMessageBox.critical(self, "错误", "初始资金必须是数字！")
            return
            
        start_date = self.start_date_input.date().toString("yyyy-MM-dd")
        end_date = self.end_date_input.date().toString("yyyy-MM-dd")
        
        watchlist = self.stocks_combo.get_checked_items()
        if not watchlist:
            QMessageBox.critical(self, "错误", "必须选择至少一只股票代码！")
            return
        if len(watchlist) > 5:
            QMessageBox.critical(self, "错误", "最多只能选择 5 只股票代码！")
            return
        
        config = {
            'initial_funds': initial_funds,
            'start_date': start_date,
            'end_date': end_date,
            'watchlist': watchlist,
            'use_ml': "机器学习增强" in self.strategy_combo.currentText()
        }
        
        self.log("=" * 40)
        self.log(f"启动新一轮回测任务，股票数：{len(watchlist)}")
        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ 回测运行中...")
        
        # 启动后台线程
        self.backtest_thread = BacktestRunnerThread(config)
        self.backtest_thread.progress.connect(self.log)
        self.backtest_thread.finished.connect(self.on_backtest_finished)
        self.backtest_thread.start()

    def on_backtest_finished(self, success: bool, results: dict, msg: str):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("🚀 开始回测")
        self.log(msg)
        
        if success:
            self.log("✅ 开始更新指标和图表面板...")
            # 延迟一小会儿确保图片文件已完全写入磁盘并能被加载
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(500, self.load_latest_report)
            QMessageBox.information(self, "回测完成", "回测执行成功并已更新面板！")
            self.log("所有回测流程结束。")
