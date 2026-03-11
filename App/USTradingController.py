#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股自动化交易控制器 (IB) - 异步与线程安全优化版
"""

import os
import sys
import time
import json
import logging
import threading
import asyncio
from datetime import datetime, timedelta
import pytz
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
import queue

from PyQt6.QtCore import QObject, pyqtSignal

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TRADING_CONFIG, CHAN_CONFIG, CHART_CONFIG, CHART_PARA
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 导入 IB
from ib_insync import IB, Stock, MarketOrder, LimitOrder, util

# 导入 视觉评分
from visual_judge import VisualJudge
# 导入 信号验证
from ML.SignalValidator import SignalValidator
# 导入 DiscordBot
from App.DiscordBot import DiscordBot

logger = logging.getLogger(__name__)

class USTradingController(QObject):
    """
    美股交易控制器 (IB)
    """
    log_message = pyqtSignal(str)
    scan_finished = pyqtSignal(int, int, int, int)
    funds_updated = pyqtSignal(float, float) # (available, total)
    
    def __init__(self, 
                 us_watchlist_group: str = "美股", 
                 discord_bot: DiscordBot = None, 
                 parent=None):
        super().__init__(parent)
        self.watchlist_group = us_watchlist_group
        self.discord_bot = discord_bot
        self._is_running = False
        self._is_paused = False
        
        # 指令队列，用于处理 GUI 线程发来的请求 (线程安全)
        self.cmd_queue = queue.Queue()
        
        self.ib = IB()
        self.host = os.getenv("IB_HOST", "127.0.0.1")
        self.port = int(os.getenv("IB_PORT", "4002"))
        self.client_id = int(os.getenv("IB_CLIENT_ID", "10"))
        
        self.charts_dir = "charts_us"
        os.makedirs(self.charts_dir, exist_ok=True)
        
        self.visual_judge = VisualJudge()
        self.ml_validator = SignalValidator()
        self.min_visual_score = TRADING_CONFIG.get('min_visual_score', 70)
        self.dry_run = TRADING_CONFIG.get('dry_run', True)
        
        # 信号历史，用于去重
        self.notified_signals = {}
        self.visual_score_cache = {}

        self.us_tz = pytz.timezone('America/New_York')

    def get_us_now(self) -> datetime:
        """获取当前美国东部时间 (New York)"""
        return datetime.now(self.us_tz).replace(tzinfo=None)

    def _connect_ib(self):
        """连接 IB"""
        if not self.ib.isConnected():
            try:
                self.ib.connect(self.host, self.port, clientId=self.client_id)
                self.log_message.emit(f"🔌 [美股] 已连接 IB Gateway ({self.host}:{self.port})")
            except Exception as e:
                self.log_message.emit(f"❌ [美股] IB 连接失败: {e}")
                raise e

    def stop(self):
        self._is_running = False
        self.log_message.emit("🛑 [美股] 正在停止交易进程...")

    def toggle_pause(self, paused: bool):
        self._is_paused = paused
        status = "已暂停" if paused else "已恢复"
        self.log_message.emit(f"ℹ️ [美股] 策略执行{status}")

    def force_scan(self):
        self.cmd_queue.put(('FORCE_SCAN', None))
        self.log_message.emit("⚡ [美股] 已加入强制扫描队列")

    def query_account_funds(self):
        self.cmd_queue.put(('QUERY_FUNDS', None))
        self.log_message.emit("💰 [美股] 已加入资金查询队列")

    def place_test_order(self, code: str = "US.AAPL"):
        self.cmd_queue.put(('TEST_ORDER', code))
        self.log_message.emit(f"🧪 [美股] 已加入 {code} 下单测试队列")

    def is_trading_time(self) -> bool:
        """判断美股交易时间 (09:30 - 16:00 ET)"""
        now_et = self.get_us_now()
        if now_et.weekday() >= 5: return False
        current_time = now_et.time()
        start = datetime.strptime("09:30", "%H:%M").time()
        end = datetime.strptime("16:00", "%H:%M").time()
        return start <= current_time <= end

    def run_trading_loop(self):
        """主交易循环 - 运行在独立线程"""
        self._is_running = True
        
        import nest_asyncio
        nest_asyncio.apply()
        
        # 确保在线程中建立正确的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            self._connect_ib()
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 初始化失败: {e}")
            self._is_running = False
            return

        self.log_message.emit(f"🚀 [美股] 自动交易循环已启动 (分组: {self.watchlist_group})")
        
        last_scan_bar = datetime.now().replace(minute=(datetime.now().minute // 30) * 30, second=0, microsecond=0)
        
        while self._is_running:
            try:
                # 1. 核心睡眠：必须使用 ib.sleep() 才能驱动 asyncio 事件循环处理 Socket
                self.ib.sleep(0.5)
                
                # 2. 处理 GUI 命令队列 (线程安全地在 IB 线程执行 IB 调用)
                while not self.cmd_queue.empty():
                    cmd_type, data = self.cmd_queue.get_nowait()
                    self._handle_gui_command(cmd_type, data)

                if self._is_paused:
                    continue

                # 3. 交易时段判断与扫描逻辑
                if not self.is_trading_time():
                    # 非交易时段，心跳变慢，但不停止，以便处理 GUI 强制指令
                    self.ib.sleep(5)
                    continue
                
                now = datetime.now()
                current_bar = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
                
                if current_bar > last_scan_bar:
                    if now.minute % 30 >= 2: # 延迟2分钟等待数据稳定
                        self._perform_strategy_scan()
                        last_scan_bar = current_bar
                
            except Exception as e:
                self.log_message.emit(f"⚠️ [美股] 循环异常: {e}")
                logger.error(f"Loop error: {e}", exc_info=True)
                self.ib.sleep(10)
                if not self.ib.isConnected():
                    try: self._connect_ib()
                    except: pass

        # 退出循环后断开连接
        if self.ib.isConnected():
            try:
                self.ib.disconnect()
            except:
                pass
        self.log_message.emit("🛑 [美股] 交易进程已安全停止")

    def _handle_gui_command(self, cmd_type, data):
        """处理来自 GUI 的指令 (在 IB 线程执行)"""
        try:
            if cmd_type == 'FORCE_SCAN':
                self._perform_strategy_scan()
            elif cmd_type == 'QUERY_FUNDS':
                available, total = self.get_account_assets()
                self.funds_updated.emit(available, total)
            elif cmd_type == 'TEST_ORDER':
                self._do_test_order(data)
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股] 指令执行失败 ({cmd_type}): {e}")

    def _do_test_order(self, code: str):
        """执行测试下单"""
        try:
            symbol = code.split('.')[-1]
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            order = MarketOrder("BUY", 1)
            self.ib.placeOrder(contract, order)
            self.log_message.emit(f"🧪 [测试] 已提交 1 股 {symbol} 市价单。请检查 TWS/Gateway。")
        except Exception as e:
            self.log_message.emit(f"❌ [测试] 下单失败: {e}")

    def _perform_strategy_scan(self):
        """执行策略扫描"""
        self.log_message.emit("🔍 [美股] 正在获取自选股并执行扫描...")
        try:
            from Monitoring.FutuMonitor import FutuMonitor
            monitor = FutuMonitor()
            ret, data = monitor.quote_ctx.get_user_security(group_name=self.watchlist_group)
            monitor.quote_ctx.close()
            
            if ret != 0 or data.empty:
                self.log_message.emit(f"⚠️ [美股] 未能在富途找到分组 '{self.watchlist_group}'。")
                return
                
            us_codes = [c for c in data['code'].tolist() if c.startswith("US.")]
            if not us_codes:
                self.log_message.emit(f"ℹ️ [美股] 分组中没有美股。")
                return
                
            self.log_message.emit(f"📡 [美股] 开始扫描 {len(us_codes)} 只美股...")
            
            for i, code in enumerate(us_codes):
                if not self._is_running: break
                try:
                    self.log_message.emit(f"⏳ [{i+1}/{len(us_codes)}] 正在分析 {code}...")
                    self._analyze_stock(code)
                    # 每只股票之间由于 reqHistoricalData 等待，本身就会驱动 asyncio
                    # 额外增加 ib.sleep 确保线程活跃
                    self.ib.sleep(0.2)
                except Exception as e:
                    self.log_message.emit(f"❌ [美股] 分析 {code} 报错: {e}")
            
            self.log_message.emit("✅ [美股] 本轮扫描完成.")
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 扫描失败: {e}")

    def _analyze_stock(self, code: str):
        """分析单只股票"""
        try:
            # 内部使用 reqHistoricalData，会被 ib.sleep(0) 或 next bar 驱动
            # 这里我们使用非异步封装的调用，ib-insync 会自动驱动 loop
            symbol = code.split(".")[1] if "." in code else code
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            bars = self.ib.reqHistoricalData(
                contract, endDateTime='', durationStr='90 D',
                barSizeSetting='30 mins', whatToShow='TRADES', useRTH=True
            )
            
            if not bars:
                self.log_message.emit(f"ℹ️ [美股] {code} 无数据")
                return

            units = []
            for bar in bars:
                dt = bar.date
                if not isinstance(dt, datetime): dt = datetime(dt.year, dt.month, dt.day)
                units.append(CKLine_Unit({
                    DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                    DATA_FIELD.FIELD_OPEN: float(bar.open), DATA_FIELD.FIELD_HIGH: float(bar.high),
                    DATA_FIELD.FIELD_LOW: float(bar.low), DATA_FIELD.FIELD_CLOSE: float(bar.close),
                    DATA_FIELD.FIELD_VOLUME: float(bar.volume), DATA_FIELD.FIELD_TURNOVER: 0.0, DATA_FIELD.FIELD_TURNRATE: 0.0
                }))

            local_chan_config = CHAN_CONFIG.copy()
            local_chan_config['trigger_step'] = True
            chan = CChan(code=code, data_src=DATA_SRC.IB, lv_list=[KL_TYPE.K_30M], config=CChanConfig(local_chan_config), autype=AUTYPE.QFQ)
            chan.trigger_load({KL_TYPE.K_30M: units})
            
            if len(chan[0]) == 0: return

            bsp_list = chan.get_latest_bsp(number=0)
            us_now = self.get_us_now()
            in_market = self.is_trading_time()
            window_sec = 3600 if in_market else 86400
            
            found_any = False
            for bsp in bsp_list:
                b_time = bsp.klu.time
                bsp_dt = datetime(b_time.year, b_time.month, b_time.day, b_time.hour, b_time.minute, b_time.second)
                if (us_now - bsp_dt).total_seconds() <= window_sec: 
                    sig_key = f"{code}_{str(bsp.klu.time)}_{bsp.type2str()}"
                    if sig_key in self.notified_signals: continue
                    found_any = True
                    self.notified_signals[sig_key] = us_now.strftime("%Y-%m-%d %H:%M:%S")
                    self.log_message.emit(f"🎯 [美股] {code} 发现信号: {bsp.type2str()} @ {bsp.klu.time}")
                    self._handle_signal(code, bsp, chan)
            
            if not found_any and bsp_list:
                 logger.debug(f"{code} no new signal, latest at {bsp_list[-1].klu.time}")

        except Exception as e:
            logger.error(f"Analysis error {code}: {e}")

    def _handle_signal(self, code: str, bsp, chan):
        """处理信号：验证 -> 评分 -> 下单"""
        if bsp.is_buy:
            ml_res = self.ml_validator.validate_signal(chan, bsp)
            if not ml_res.get('is_valid', True):
                self.log_message.emit(f"🚫 [美股] {code} ML 过滤: {ml_res.get('msg')}")
                return

        chart_path = os.path.abspath(os.path.join(self.charts_dir, f"{code.replace('.', '_')}.png"))
        plot_driver = CPlotDriver(chan, plot_config=CHART_CONFIG, plot_para=CHART_PARA)
        plt.savefig(chart_path, bbox_inches='tight', dpi=120)
        plt.close('all')
        
        self.log_message.emit(f"🧠 [美股] 视觉评分 {code}...")
        visual_res = self.visual_judge.evaluate([chart_path], bsp.type2str())
        score = visual_res.get('score', 0)
        
        self.log_message.emit(f"🎯 [美股] {code} 信号: {bsp.type2str()}, 评分: {score}")
        
        if self.discord_bot and score >= self.min_visual_score:
            msg = f"🗽 **美股自动化预警**\n股票: {code}\n信号: {bsp.type2str()}\n评分: **{score}分**"
            asyncio.run_coroutine_threadsafe(self.discord_bot.send_notification(msg, chart_path), self.discord_bot.loop)

        if score >= self.min_visual_score:
            if self.dry_run:
                self.log_message.emit(f"📝 [美股-模拟] {code} 跳过实盘下单")
            else:
                self._execute_trade(code, "BUY" if bsp.is_buy else "SELL", bsp.klu.close)

    def get_account_assets(self) -> Tuple[float, float]:
        """获取资金信息 - 此方法现在由 IB 线程调用"""
        if not self.ib.isConnected(): return 0.0, 0.0
        try:
            # 1. 尝试从已更新的清单中找
            available = 0.0
            total = 0.0
            
            # 使用同步阻塞但在 IB 线程中安全的 waitOnUpdate
            # 或者直接读取 accountValues (ib-insync 会自动维护它)
            for v in self.ib.accountValues():
                if v.tag == 'AvailableFunds' and v.currency == 'USD':
                    available = float(v.value)
                if v.tag == 'NetLiquidation' and v.currency == 'USD':
                    total = float(v.value)
            
            # 如果没拿到，重刷一次
            if total == 0:
                summary = self.ib.accountSummary()
                for item in summary:
                    if item.tag == 'AvailableFunds': available = float(item.value)
                    elif item.tag == 'NetLiquidation': total = float(item.value)
            
            return available, total
        except Exception as e:
            logger.error(f"Funds error: {e}")
            return 0.0, 0.0

    def _execute_trade(self, code: str, action: str, price: float):
        """执行交易"""
        try:
            symbol = code.split('.')[-1]
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            qty = max(1, int(2000 / price))
            
            if action == "SELL":
                # 获取持仓
                curr_qty = 0
                for p in self.ib.positions():
                    if p.contract.symbol == symbol:
                        curr_qty = p.position
                        break
                if curr_qty < qty:
                    qty = curr_qty
                    if qty <= 0: return

            order = MarketOrder(action, qty)
            self.ib.placeOrder(contract, order)
            self.log_message.emit(f"🚀 [美股] 订单已提交: {symbol} {action} {qty}")
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 交易失败: {e}")
