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
    funds_updated = pyqtSignal(float, float, list) # (available, total, positions)
    
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
        
        self.ib = None
        self.host = os.getenv("IB_HOST", "127.0.0.1")
        self.port = int(os.getenv("IB_PORT", "4002"))
        self.client_id = int(os.getenv("IB_CLIENT_ID", "10"))
        
        self.charts_dir = "charts_us"
        os.makedirs(self.charts_dir, exist_ok=True)
        
        self.visual_judge = VisualJudge()
        self.ml_validator = SignalValidator()
        self.min_visual_score = TRADING_CONFIG.get('min_visual_score', 70)
        self.dry_run = TRADING_CONFIG.get('us_dry_run', False)
        
        # 信号历史，用于去重
        self.notified_signals = {}
        self.visual_score_cache = {}

        self.us_tz = pytz.timezone('America/New_York')

    def get_us_now(self) -> datetime:
        """获取当前美国东部时间 (New York)"""
        return datetime.now(self.us_tz).replace(tzinfo=None)

    def _connect_ib(self):
        """连接 IB"""
        if self.ib is None:
            self.ib = IB()
            
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
            self.ib = IB() # 在 IB 线程中实例化，确保 Event Loop 绑定正确
            self._connect_ib()
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 初始化失败: {e}")
            self._is_running = False
            return

        self.log_message.emit(f"🚀 [美股] 自动交易循环已启动 (分组: {self.watchlist_group})")
        
        # 初始化扫描时间为过去 (使用美东时间)，确保启动后在交易时段内能立即触发扫描
        last_scan_bar = self.get_us_now() - timedelta(minutes=60)
        
        while self._is_running:
            try:
                # 1. 核心睡眠：必须使用 ib.sleep() 才能驱动 asyncio 事件循环处理 Socket
                self.ib.sleep(0.5)
                
                # 2. 处理 GUI 命令队列 (线程安全地在 IB 线程执行 IB 调用)
                while not self.cmd_queue.empty():
                    cmd_type, data = self.cmd_queue.get_nowait()
                    self.log_message.emit(f"📥 [队列] 正在执行指令: {cmd_type}")
                    self._handle_gui_command(cmd_type, data)

                # Phase 4: 检查并热加载最新的优化的模型
                self.ml_validator.check_and_reload()

                if self._is_paused:
                    continue

                # 3. 交易时段判断与扫描逻辑
                now_et = self.get_us_now()
                if not self.is_trading_time():
                    # 非交易时段，心跳变慢
                    if now_et.second % 60 == 0:
                        self.log_message.emit(f"💤 非交易时段 (NY: {now_et.strftime('%H:%M:%S')}), 等待 09:30 开盘...")
                    self.ib.sleep(10)
                    continue
                
                # 使用纽约时间计算 30 分钟 K 线 Bar
                current_bar_et = now_et.replace(minute=(now_et.minute // 30) * 30, second=0, microsecond=0)
                
                if current_bar_et > last_scan_bar:
                    # 检查是否满足 2 分钟稳定延迟 (开盘前 2 分钟通常数据不全)
                    wait_minutes = now_et.minute % 30
                    if wait_minutes < 2:
                        if now_et.second % 10 == 0:
                            self.log_message.emit(f"⏳ 等待数据稳定 (NY: {now_et.strftime('%H:%M:%S')}, 已过 {wait_minutes}/2 分钟)...")
                        self.ib.sleep(1)
                        continue
                        
                    self.log_message.emit(f"⚡ [美股] 触发新周期扫描 (Bar: {current_bar_et.strftime('%H:%M')})")
                    self._perform_strategy_scan()
                    last_scan_bar = current_bar_et
                else:
                    # 心跳日志，确认程序仍在运行
                    if now_et.second % 60 == 0:
                        next_scan = current_bar_et + timedelta(minutes=30, seconds=120)
                        self.log_message.emit(f"💓 扫描心跳 (NY: {now_et.strftime('%H:%M')}), 下次扫描约在 {next_scan.strftime('%H:%M:%S')}")
                        self.ib.sleep(1)
                
            except Exception as e:
                self.log_message.emit(f"⚠️ [美股] 循环异常: {e}")
                logger.error(f"Loop error: {e}", exc_info=True)
                self.ib.sleep(10)
                if not self.ib.isConnected():
                    try: self._connect_ib()
                    except: pass

        # 退出循环后断开连接
        if self.ib and self.ib.isConnected():
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
                available, total, positions = self.get_account_assets()
                self.funds_updated.emit(available, total, positions)
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股] 指令执行失败 ({cmd_type}): {e}")


    def get_position_quantity(self, code: str) -> int:
        """获取指定代码的持仓数量"""
        if self.ib is None or not self.ib.isConnected(): return 0
        symbol = code.split('.')[-1]
        for p in self.ib.positions():
            if p.contract.symbol == symbol:
                return int(p.position)
        return 0

    def check_pending_orders(self, code: str, side: str) -> bool:
        """检查是否有相同方向的未成交订单"""
        if self.ib is None or not self.ib.isConnected(): return False
        symbol = code.split('.')[-1]
        for trade in self.ib.openTrades():
            if trade.contract.symbol == symbol and trade.order.action == side.upper():
                # 状态包括已提交、待提交、预提交等
                if trade.orderStatus.status in ('PendingSubmit', 'PreSubmitted', 'Submitted'):
                    return True
        return False

    def _perform_strategy_scan(self):
        """执行策略扫描"""
        self.log_message.emit(f"🔍 [美股] 正在从自选股分组 '{self.watchlist_group}' 获取代码并执行扫描...")
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

            # 4. 缠论分析 (30M)
            local_chan_config = CHAN_CONFIG.copy()
            local_chan_config['trigger_step'] = True
            chan_30m = CChan(code=code, data_src=DATA_SRC.IB, lv_list=[KL_TYPE.K_30M], config=CChanConfig(local_chan_config), autype=AUTYPE.QFQ)
            chan_30m.trigger_load({KL_TYPE.K_30M: units})
            
            if len(chan_30m[0]) == 0: return

            bsp_list = chan_30m.get_latest_bsp(number=0)
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
                    
                    # 5. 为了视觉评分捕捉 5M 数据
                    chan_5m = None
                    try:
                        bars_5m = self.ib.reqHistoricalData(
                            contract, endDateTime='', durationStr='10 D',
                            barSizeSetting='5 mins', whatToShow='TRADES', useRTH=True
                        )
                        if bars_5m:
                            units_5m = []
                            for bar in bars_5m:
                                dt_5m = bar.date
                                if not isinstance(dt_5m, datetime): dt_5m = datetime(dt_5m.year, dt_5m.month, dt_5m.day)
                                units_5m.append(CKLine_Unit({
                                    DATA_FIELD.FIELD_TIME: CTime(dt_5m.year, dt_5m.month, dt_5m.day, dt_5m.hour, dt_5m.minute),
                                    DATA_FIELD.FIELD_OPEN: float(bar.open), DATA_FIELD.FIELD_HIGH: float(bar.high),
                                    DATA_FIELD.FIELD_LOW: float(bar.low), DATA_FIELD.FIELD_CLOSE: float(bar.close),
                                    DATA_FIELD.FIELD_VOLUME: float(bar.volume), DATA_FIELD.FIELD_TURNOVER: 0.0, DATA_FIELD.FIELD_TURNRATE: 0.0
                                }))
                            chan_5m = CChan(code=code, data_src=DATA_SRC.IB, lv_list=[KL_TYPE.K_5M], config=CChanConfig(local_chan_config), autype=AUTYPE.QFQ)
                            chan_5m.trigger_load({KL_TYPE.K_5M: units_5m})
                    except Exception as e:
                        logger.warning(f"Failed to fetch 5m data for {code}: {e}")

                    self._handle_signal(code, bsp, chan_30m, chan_5m)
            
            if not found_any and bsp_list:
                 logger.debug(f"{code} no new signal, latest at {bsp_list[-1].klu.time}")

        except Exception as e:
            logger.error(f"Analysis error {code}: {e}")

    def _handle_signal(self, code: str, bsp, chan_30m, chan_5m=None):
        """处理信号：验证 -> 评分 -> 下单"""
        is_buy = bsp.is_buy
        bsp_type = bsp.type2str()
        bsp_display = f"{'b' if is_buy else 's'}{bsp_type}"
        
        # 1. 持仓校验 (与港股逻辑一致)
        # 买入信号：若已有持仓，则跳过
        # 卖出信号：若无持仓，则跳过
        pos_qty = self.get_position_quantity(code)
        if is_buy and pos_qty > 0:
            self.log_message.emit(f"⏭️ [美股] {code} {bsp_display} 已有持仓({pos_qty})，跳过买入信号")
            return
        if not is_buy and pos_qty <= 0:
            self.log_message.emit(f"⏭️ [美股] {code} {bsp_display} 无持仓，跳过卖出信号")
            return

        # 2. 挂单校验 (防止重复下单)
        if self.check_pending_orders(code, 'BUY' if is_buy else 'SELL'):
            self.log_message.emit(f"⏭️ [美股] {code} {bsp_display} 已有相同方向挂单，跳过")
            return

        # 3. ML 验证
        if is_buy:
            ml_res = self.ml_validator.validate_signal(chan_30m, bsp)
            ml_valid = ml_res.get('is_valid', True)
            ml_msg = ml_res.get('msg', 'N/A')
            ml_score = ml_res.get('score', 'N/A')
            self.log_message.emit(f"🤖 [美股] {code} ML 验证结果: {'✅ 通过' if ml_valid else '❌ 拦截'}, 分数: {ml_score}, 原因: {ml_msg}")
            if not ml_valid:
                return

        # 4. 生成图表并进行视觉评分
        chart_paths = []
        
        # 30M 图表
        path_30m = os.path.abspath(os.path.join(self.charts_dir, f"{code.replace('.', '_')}_30m.png"))
        plot_30m = CPlotDriver(chan_30m, plot_config=CHART_CONFIG, plot_para=CHART_PARA)
        plt.savefig(path_30m, bbox_inches='tight', dpi=120)
        plt.close('all')
        chart_paths.append(path_30m)

        # 5M 图表 (如果有)
        if chan_5m:
            path_5m = os.path.abspath(os.path.join(self.charts_dir, f"{code.replace('.', '_')}_5m.png"))
            plot_5m = CPlotDriver(chan_5m, plot_config=CHART_CONFIG, plot_para=CHART_PARA)
            plt.savefig(path_5m, bbox_inches='tight', dpi=120)
            plt.close('all')
            chart_paths.append(path_5m)

        self.log_message.emit(f"🧠 [美股] 发起视觉评分 {code} ({len(chart_paths)} 张图片)...")
        visual_res = self.visual_judge.evaluate(chart_paths, bsp.type2str())
        score = visual_res.get('score', 0)
        
        self.log_message.emit(f"🎯 [美股] {code} 最终评分: {score}")
        
        if self.discord_bot and score >= self.min_visual_score:
            msg = f"🗽 **美股自动化预警**\n股票: {code}\n信号: {bsp.type2str()}\n评分: **{score}分**\nML验证: {ml_score if is_buy else 'N/A'}"
            # 发送到 Discord (目前只发送第一张 30m)
            asyncio.run_coroutine_threadsafe(self.discord_bot.send_notification(msg, path_30m), self.discord_bot.loop)

        if score >= self.min_visual_score:
            if self.dry_run:
                self.log_message.emit(f"📝 [美股-模拟] {code} 满足条件({score}分)，跳过实盘下单")
            else:
                self._execute_trade(code, "BUY" if bsp.is_buy else "SELL", bsp.klu.close)
        else:
            self.log_message.emit(f"⏭️ [美股] {code} 评分({score}) 低于阈值({self.min_visual_score})，跳过")

    def get_account_assets(self) -> Tuple[float, float, list]:
        """获取资金和持仓信息"""
        if self.ib is None or not self.ib.isConnected(): return 0.0, 0.0, []
        try:
            available = 0.0
            total = 0.0
            
            for v in self.ib.accountValues():
                if v.tag == 'AvailableFunds' and v.currency == 'USD':
                    available = float(v.value)
                if v.tag == 'NetLiquidation' and v.currency == 'USD':
                    total = float(v.value)
            
            if total == 0:
                summary = self.ib.accountSummary()
                for item in summary:
                    if item.tag == 'AvailableFunds': available = float(item.value)
                    elif item.tag == 'NetLiquidation': total = float(item.value)
            
            # 获取持仓 (使用 Portfolio 包含市值)
            positions_data = []
            for item in self.ib.portfolio():
                if item.position != 0:
                    positions_data.append({
                        'symbol': item.contract.symbol,
                        'qty': int(item.position),
                        'mkt_value': round(item.marketValue, 2),
                        'avg_cost': round(item.averageCost, 2)
                    })
            
            return available, total, positions_data
        except Exception as e:
            logger.error(f"Account query error: {e}")
            return 0.0, 0.0, []

    def _execute_trade(self, code: str, action: str, price: float):
        """执行交易"""
        try:
            symbol = code.split('.')[-1]
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            # Phase 4 Update: 增加单只买入金额到 10,000 USD
            qty = max(1, int(10000 / price))
            
            if action == "SELL":
                # 获取持仓
                curr_qty = self.get_position_quantity(code)
                if curr_qty < qty:
                    old_qty = qty
                    qty = curr_qty
                    if qty <= 0:
                        self.log_message.emit(f"⏭️ [美股] {symbol} {action} 无持仓，跳过执行")
                        return
                    else:
                        self.log_message.emit(f"ℹ️ [美股] {symbol} {action} 持仓不足，由 {old_qty} 调整为 {qty}")

            order = MarketOrder(action, qty)
            self.ib.placeOrder(contract, order)
            self.log_message.emit(f"🚀 [美股] 订单已提交: {symbol} {action} {qty}")
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 交易失败: {e}")
