import sys
import sqlite3
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QSplitter, QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from datetime import datetime, timedelta
from Trade.db_util import CChanDB
from App.ScannerThreads import NewsCollectorThread


class InsightTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = CChanDB()
        self.collector_thread = None
        self.init_ui()

        # Auto-refresh UI from DB every 10s
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_ui)
        self.timer.start(10000)

        self.refresh_ui()

    # ── UI Layout ──────────────────────────────────────────────
    def init_ui(self):
        layout = QVBoxLayout(self)

        # Controls
        ctrl = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 强制更新数据 (获取最新资讯)")
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        ctrl.addWidget(self.refresh_btn)

        self.purge_btn = QPushButton("🗑️ 清理旧/低质量数据")
        self.purge_btn.clicked.connect(self.on_purge_clicked)
        ctrl.addWidget(self.purge_btn)

        self.status_label = QLabel("状态: 就绪")
        ctrl.addWidget(self.status_label)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Vertical)

        # News
        news_grp = QGroupBox("🗞️ 市场资讯与情绪导航 (Gemini AI)")
        nl = QVBoxLayout()
        self.news_table = QTableWidget()
        self.news_table.setColumnCount(5)
        self.news_table.setHorizontalHeaderLabels(
            ["时间", "市场", "相关代码", "资讯标题", "情绪得分"]
        )
        self.news_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.news_table.setAlternatingRowColors(True)
        self.news_table.setStyleSheet("QTableWidget { font-size: 12px; background-color: #ffffff; }")
        nl.addWidget(self.news_table)
        news_grp.setLayout(nl)

        # Sectors
        sec_grp = QGroupBox("🔥 热点板块与资金联动")
        sl = QVBoxLayout()
        self.sector_table = QTableWidget()
        self.sector_table.setColumnCount(4)
        self.sector_table.setHorizontalHeaderLabels(
            ["市场", "板块名称", "领涨个股", "热度/更新"]
        )
        self.sector_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.sector_table.setAlternatingRowColors(True)
        self.sector_table.setStyleSheet("QTableWidget { background-color: #ffffff; }")
        sl.addWidget(self.sector_table)
        sec_grp.setLayout(sl)

        splitter.addWidget(news_grp)
        splitter.addWidget(sec_grp)
        splitter.setSizes([600, 300])
        layout.addWidget(splitter)

    # ── Refresh Button ─────────────────────────────────────────
    @pyqtSlot()
    def on_refresh_clicked(self):
        if self.collector_thread and self.collector_thread.isRunning():
            self.status_label.setText("状态: 上次抓取仍在运行中...")
            return

        self.refresh_btn.setEnabled(False)
        self.status_label.setText("状态: 🚀 正在启动抓取任务...")

        self.collector_thread = NewsCollectorThread()
        self.collector_thread.finished.connect(self.on_collector_finished)
        self.collector_thread.log_signal.connect(
            lambda msg: self.status_label.setText(f"状态: {msg}")
        )
        self.collector_thread.start()

    def on_collector_finished(self):
        self.refresh_btn.setEnabled(True)
        self.refresh_ui()
        # Keep status from the thread's last log_signal (don't overwrite)

    # ── Purge Button ───────────────────────────────────────────
    @pyqtSlot()
    def on_purge_clicked(self):
        """Delete old CCTV / political / short news from DB"""
        try:
            with sqlite3.connect(self.db.db_path) as conn:
                cur = conn.cursor()
                # Count before
                cur.execute("SELECT COUNT(*) FROM market_news")
                before = cur.fetchone()[0]
                # Delete rules
                cur.execute("""
                    DELETE FROM market_news WHERE
                        source = 'CCTV'
                        OR LENGTH(title) < 10
                        OR title LIKE '%会见%'
                        OR title LIKE '%考察%'
                        OR title LIKE '%致辞%'
                        OR title LIKE '%调研%'
                        OR title LIKE '%联播快讯%'
                        OR title LIKE '%快评%'
                """)
                conn.commit()
                cur.execute("SELECT COUNT(*) FROM market_news")
                after = cur.fetchone()[0]
                deleted = before - after

            self.status_label.setText(
                f"状态: 🗑️ 已清理 {deleted} 条低质量数据 (剩余 {after} 条)"
            )
            self.refresh_ui()
        except Exception as e:
            self.status_label.setText(f"状态: ❌ 清理失败: {e}")

    @pyqtSlot()
    def refresh_ui(self):
        # News - Filter to last 24 hours
        try:
            cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
            ndf = self.db.execute_query(
                "SELECT timestamp, market, symbols, title, sentiment_score "
                "FROM market_news WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT 50",
                (cutoff,)
            )
            self.news_table.setRowCount(len(ndf))
            for i, r in ndf.iterrows():
                self.news_table.setItem(i, 0, QTableWidgetItem(str(r["timestamp"])))
                # Market Color Coding
                mkt = str(r["market"]).upper()
                mi = QTableWidgetItem(mkt)
                if mkt == 'CN':
                    mi.setForeground(Qt.GlobalColor.red)
                elif mkt == 'HK':
                    mi.setForeground(Qt.GlobalColor.blue)
                elif mkt == 'US':
                    mi.setForeground(Qt.GlobalColor.magenta)
                self.news_table.setItem(i, 1, mi)

                self.news_table.setItem(
                    i, 2, QTableWidgetItem(str(r["symbols"] or ""))
                )
                self.news_table.setItem(i, 3, QTableWidgetItem(str(r["title"])))
                
                sc = r["sentiment_score"] or 0.0
                si = QTableWidgetItem(f"{sc:+.2f}")
                if sc > 0.15:
                    si.setForeground(Qt.GlobalColor.darkGreen)
                elif sc < -0.15:
                    si.setForeground(Qt.GlobalColor.darkRed)
                else:
                    si.setForeground(Qt.GlobalColor.gray) # Gray out neutral/disabled scores
                self.news_table.setItem(i, 4, si)
        except Exception as e:
            print(f"⚠️ InsightTab News Refresh Error: {e}")

        # Sectors
        try:
            sdf = self.db.execute_query(
                "SELECT market, sector_name, top_movers, created_at "
                "FROM sector_heat_daily WHERE date = ? "
                "ORDER BY market, sector_name",
                (datetime.now().strftime("%Y-%m-%d"),),
            )
            if sdf.empty:
                sdf = self.db.execute_query(
                    "SELECT market, sector_name, top_movers, created_at "
                    "FROM sector_heat_daily ORDER BY created_at DESC LIMIT 20"
                )
            self.sector_table.setRowCount(len(sdf))
            for i, r in sdf.iterrows():
                mkt = str(r["market"]).upper()
                mi = QTableWidgetItem(mkt)
                if mkt == 'CN':
                    mi.setForeground(Qt.GlobalColor.red)
                elif mkt == 'HK':
                    mi.setForeground(Qt.GlobalColor.blue)
                elif mkt == 'US':
                    mi.setForeground(Qt.GlobalColor.magenta)
                self.sector_table.setItem(i, 0, mi)
                self.sector_table.setItem(
                    i, 1, QTableWidgetItem(str(r["sector_name"]))
                )
                self.sector_table.setItem(
                    i, 2, QTableWidgetItem(str(r["top_movers"]))
                )
                self.sector_table.setItem(
                    i, 3, QTableWidgetItem(str(r["created_at"]))
                )
        except Exception as e:
            print(f"⚠️ InsightTab Sector Refresh Error: {e}")


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    w = InsightTab()
    w.resize(1000, 800)
    w.show()
    sys.exit(app.exec())
