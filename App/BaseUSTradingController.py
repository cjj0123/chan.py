#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股自动化交易控制器 (IB) - 异步与线程安全优化版
"""

import os
import sys
import time
import random
import json
import logging
import threading
import asyncio
import traceback
from datetime import datetime, timedelta
import pytz
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
import queue
import nest_asyncio
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import sqlite3
from Trade.MemorySummarizer import MemorySummarizer
import requests

if os.environ.get('WEB_MODE') == '1':
    from App.WebControllerAdapter import WebSignal as pyqtSignal, WebObject as QObject
else:
    try:
        from PyQt6.QtCore import QObject, pyqtSignal
    except ImportError:
        from App.WebControllerAdapter import WebSignal as pyqtSignal, WebObject as QObject

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TRADING_CONFIG, CHAN_CONFIG, CHART_CONFIG, CHART_PARA, MARKET_SPECIFIC_CONFIG
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.SQLiteAPI import SQLiteAPI, download_and_save_all_stocks_multi_timeframe, download_and_save_all_stocks_async
from Trade.db_util import CChanDB
from Trade.RiskManager import get_risk_manager
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
from App.DiscordBot import DiscordBot


# --- 配置导入 ---
# Schwab API 与 频率限制器
from DataAPI.SchwabAPI import CSchwabAPI
from Common.SchwabRateLimiter import get_schwab_limiter

# 导入 Futu US 交易
from futu import OpenSecTradeContext, TrdMarket, TrdSide, OrderType, RET_OK, TrdEnv

logger = logging.getLogger(__name__)

class BaseUSTradingController(QObject):
    """
    美股交易控制器 (IB)
    """
    log_message = pyqtSignal(str)
    scan_finished = pyqtSignal(int, int, int, int)
    funds_updated = pyqtSignal(float, float, list) # (available, total, positions)

    def get_watchlist_data(self) -> Dict[str, str]:
        """返回当前美股监控股票池，供 GUI/Web 汇总展示。"""
        return self.get_futu_watchlist()
    
    def get_futu_watchlist(self):
        """支持多个分组合并同步 (如 '美股,热点_实盘')"""
        all_dict = {}
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('127.0.0.1', 11111))
            sock.close()
            if result != 0:
                # 🟢 [IB/Schwab] Futu 关停时，支持从本地 Config/us_watchlist.txt 加载扫描股票池
                import os
                local_path = "Config/us_watchlist.txt"
                if os.path.exists(local_path):
                    with open(local_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                c = line if line.startswith("US.") else f"US.{line}"
                                all_dict[c] = c.split('.')[-1]
                return all_dict

            from futu import OpenQuoteContext, RET_OK
            ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            groups = [g.strip() for g in self.watchlist_group.split(',') if g.strip()]
            for grp in groups:
                ret, data = ctx.get_user_security(group_name=grp)
                if ret == RET_OK and not data.empty:
                    name_col = 'name' if 'name' in data.columns else 'stock_name'
                    for _, row in data.iterrows():
                        c = row['code']
                        if c.startswith("US."):
                            all_dict[c] = row.get(name_col, c)
            ctx.close()
        except Exception:
            pass
        return all_dict

    def __init__(self, 
                 us_watchlist_group: str = "美股", 
                 discord_bot: DiscordBot = None, 
                 venue: str = "IB",
                 parent=None):
        super().__init__(parent)
        self.watchlist_group = us_watchlist_group
        self.discord_bot = discord_bot
        self.venue = venue.upper()
        self._is_running = False
        self._is_paused = False
        
        # 指令队列，用于处理 GUI 线程发来的请求 (线程安全)
        self.cmd_queue = queue.Queue()
        self._pending_execute_codes = set() # 🟢 [风控加固] 用于队列内指令去重
        
        self.ib = None
        self.host = os.getenv("IB_HOST", "127.0.0.1")
        self.paper_port = int(os.getenv("IB_PAPER_PORT", "4002"))
        self.real_port = int(os.getenv("IB_REAL_PORT", "4001"))
        self.port = int(os.getenv("IB_PORT", str(self.paper_port)))
        self.client_id = 10 # 彻底隔离：交易使用 10-20，扫描使用 50-450
        
        self.charts_dir = f"charts_us_{self.venue.lower()}"
        os.makedirs(self.charts_dir, exist_ok=True)
        # 实例化工具组件
        self.signal_validator = SignalValidator()
        self.visual_judge = VisualJudge()
        self.db = CChanDB()
        self.risk_manager = get_risk_manager()
        self.discord_bot = discord_bot or None
        # 💡 [架构解耦] 支持按渠道进行独立参数覆盖：如 TRADING_CONFIG = {"FUTU": {"us_dry_run": True}}
        venue_cfg = TRADING_CONFIG.get(self.venue, {}) if isinstance(TRADING_CONFIG.get(self.venue), dict) else {}
        
        self.min_visual_score = venue_cfg.get('min_visual_score', TRADING_CONFIG.get('min_visual_score', 70))
        self.dry_run = venue_cfg.get('us_dry_run', TRADING_CONFIG.get('us_dry_run', False))
        self.trd_env = TrdEnv.SIMULATE if self.dry_run else TrdEnv.REAL
        
        # 💡 [业务对齐] 如果选了 Futu 渠道，由于您是用作模拟盘，强制打入 SIMULATE 状态，防止读取 config 下跌实盘
        if self.venue == "FUTU":
             self.trd_env = TrdEnv.SIMULATE
        
        # 信号历史，用于去重 (持久化到磁盘，防止重启后重复下单)
        self.notified_signals_file = os.path.join(self.charts_dir, f'us_{self.venue.lower()}_notified_signals.json')
        self.notified_signals = self._load_notified_signals()
        self.visual_score_cache = {}
        
        # 线程池：用于执行耗时的 AI 评分和绘图任务，防止阻塞 IB 驱动循环
        self.executor = ThreadPoolExecutor(max_workers=10)
        
        # 图表生成锁，防止多线程 matplotlib 状态泄漏
        self.chart_generation_lock = threading.Lock()

        self.us_tz = pytz.timezone('America/New_York')
        
        # 并发控制：美股扫描使用信号量限制同时请求 IB 数据的人数，防止被封 IP 或限流
        self.scan_semaphore = asyncio.Semaphore(8)

        # Schwab 相关初始化
        self.schwab_token_path = os.path.join(Path(__file__).resolve().parent.parent, 'schwab_token.json')
        self.schwab_account_hash = None
        self.schwab_limiter = get_schwab_limiter()
        self.schwab_api = None
        self.schwab_positions_cache = [] # 缓存 Schwab 持仓
        if os.path.exists(self.schwab_token_path):
             # 占位初始化，真正连接时会刷新
             self.schwab_api = CSchwabAPI("US.AAPL") 
             
        # 风险属性：本地活性止损跟踪器 {code: {entry_price, highest_price, atr, trail_active}}
        self.position_trackers = {}
        self.retry_orders = {}             # 🚨 [补漏专用] 下单异常重试池，防崩溃漏单
        self.structure_barrier = {}        # 🛡️ [风控锁区 Phase 8] 挂载止损隔离舱，防止重复进出损耗
        self.trade_cooldown = {}           # 🛡️ [风控锁区 Phase 9] 冷却期记录，防止高频震荡进出
        self.sold_today = set()            # 🛡️ [风控加固 Phase 13] 单日平仓锁定集合，防止因 API 延迟导致的循环下单
        # 🚀 [Phase 11] 应用针对 美股 优化的专属参数
        us_cfg = MARKET_SPECIFIC_CONFIG.get('US', {})
        self.chan_config = CChanConfig(CHAN_CONFIG)
        if 'bs_type' in us_cfg:
            self.chan_config.bs_point_conf.b_conf.tmp_target_types = us_cfg['bs_type']
            self.chan_config.bs_point_conf.b_conf.parse_target_type()
            self.chan_config.bs_point_conf.s_conf.tmp_target_types = us_cfg['bs_type']
            self.chan_config.bs_point_conf.s_conf.parse_target_type()
        
        self.atr_stop_trail = us_cfg.get('atr_stop_trail', TRADING_CONFIG.get('atr_stop_trail', 2.5))

        self._trd_ctx = None
        self._last_close_date = None
        self._last_reset_date = datetime.now().strftime("%Y-%m-%d") # 🛡️ 日期重置锚点
        self._trackers_initialized = False
        self._trackers_initializing = False

    @property
    def trd_ctx(self):
        """延迟初始化 Futu 交易上下文，确保在使用线程上创建"""
        if self._trd_ctx is None:
            self._trd_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host='127.0.0.1', port=11111)
        return self._trd_ctx

    def _load_notified_signals(self) -> dict:
        """从磁盘加载已通知信号记录，防止重启后重复下单"""
        if os.path.exists(self.notified_signals_file):
            try:
                with open(self.notified_signals_file, 'r') as f:
                    data = json.load(f)
                # 清理超过 24 小时的旧记录，防止文件无限增长
                cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
                return {k: v for k, v in data.items() if v >= cutoff}
            except Exception as e:
                logger.error(f"加载 US 信号记录失败: {e}")
        return {}

    def _save_notified_signals(self):
        """将已通知信号记录持久化到磁盘"""
        try:
            with open(self.notified_signals_file, 'w') as f:
                json.dump(self.notified_signals, f, indent=2)
        except Exception as e:
            logger.error(f"保存 US 信号记录失败: {e}")

    def get_us_now(self) -> datetime:
        """获取当前美国东部时间 (New York)"""
        return datetime.now(self.us_tz).replace(tzinfo=None)

    def is_trading_time(self) -> bool:
        """检查当前是否为美股交易时段 (09:30 - 16:00 ET)"""
        now = self.get_us_now()
        if now.weekday() >= 5: return False
        start_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        end_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return start_time <= now <= end_time

    def stop(self):
        self._is_running = False
        self.log_message.emit("🛑 [美股] 正在停止交易进程...")

    def is_live_account_mode(self) -> bool:
        """当前是否连接到 IB 实盘账户端口。"""
        return self.port == self.real_port

    def set_live_account_mode(self, live_mode: bool):
        """切换 IB 账户模式：实盘(4001) / 模拟盘(4002)。"""
        target_port = self.real_port if live_mode else self.paper_port
        if self.port == target_port:
            return

        self.port = target_port
        self._trackers_initialized = False
        self._trackers_initializing = False
        mode_label = "实盘账户" if live_mode else "模拟盘账户"
        self.log_message.emit(f"🔁 [美股] 正在切换到 {mode_label} (端口: {target_port})")

        if self.ib and self.ib.isConnected():
            try:
                self.ib.disconnect()
                self.log_message.emit("🔌 [美股] 已断开当前 IB 会话，等待按新账户模式重连...")
            except Exception as e:
                self.log_message.emit(f"⚠️ [美股] 切换账户模式时断开连接失败: {e}")

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

    def close_all_positions_command(self):
        self.cmd_queue.put(('CLOSE_ALL', None))
        self.log_message.emit("🔥 [美股] 已加入清仓指令队列")

    def run_trading_loop(self):
        """主线程入口 - 设置异步环境并运行 async_main"""
        print(f"\n[DEBUG] {datetime.now()} US Trading Thread START for group {self.watchlist_group}")
        self._is_running = True
        # 🟢 [极早期排障] 验证 PyQt 信号通道和线程入口是否正常打通
        self.log_message.emit("🔌 [美股] 线程启动入口点触发 (run_trading_loop)...")
        
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        nest_asyncio.apply(self.loop)
        
        try:
            # 确保启动前 IB 对象为空，强制 async_main 重新创建
            self.ib = None 
            self.loop.run_until_complete(self._async_main())
        except Exception as e:
            err_msg = f"🚨 [美股] 异步主循环崩溃: {e}\n{traceback.format_exc()}"
            print(err_msg)
            # 💡 [排障加固] 异常同步输出到 PyQt 的 log_message 通道，避免后台线程静默挂掉
            self.log_message.emit(err_msg)
            self.log_message.emit(err_msg)
        finally:
            self._is_running = False
            if self.ib:
                try: self.ib.disconnect()
                except: pass
            if self.loop and not self.loop.is_closed():
                try: self.loop.close()
                except: pass
            self.loop = None
            self.log_message.emit("🛑 [美股] 交易驱动线程已正常终止")
            print("[DEBUG] US Trading Thread EXIT.")

    def on_market_close(self):
        """收盘逻辑"""
        self.log_message.emit("🌙 [美股] 交易时段结束，正在执行收盘结算...")
        try:
            summarizer = MemorySummarizer()
            count, report_path = summarizer.run()
            self.log_message.emit(f"📝 [美股] Memory Summarize 完成: 归档 {count} 条信号，报告生成于 {report_path}")
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股] Memory Summarize 运行失败: {str(e)}")
        # 清理过时状态
        self.buy_interceptors.clear()

    def on_ib_error(self, reqId, errorCode, errorString, contract):
        """IB 错误事件回调"""
        if errorCode in (1100, 1101, 1102):
            icon = "📡" if errorCode >= 1101 else "🚨"
            self.log_message.emit(f"{icon} [IB-网络状态] {errorCode}: {errorString}")
        elif errorCode == 2100: 
             self.log_message.emit(f"✅ [IB-系统] {errorString}")

    def _on_exec_details(self, trade, fill):
        """IB 成交细节回调，同步推送至 GUI"""
        try:
            symbol = trade.contract.symbol if hasattr(trade, 'contract') else "Unknown"
            exec_price = fill.execution.price
            shares = fill.execution.shares
            side = fill.execution.side
            self.log_message.emit(f"💰 [IB-成交录得] {symbol} {side} {shares:g}股 @ ${exec_price:.2f} (佣金约等结算)")
        except Exception as e:
            print(f"[_on_exec_details Exception] {e}")

    async def _poll_gui_commands(self):
        """高速轮询 GUI 指令的独立协程，保证响应极速"""
        while self._is_running:
            while not self.cmd_queue.empty():
                try:
                    cmd_type, data = self.cmd_queue.get_nowait()
                    self.log_message.emit(f"📥 [快速指令] 正在执行: {cmd_type}")
                    await self._handle_gui_command(cmd_type, data)
                except Exception as ce:
                    self.log_message.emit(f"⚠️ [指令] 响应失败: {ce}")
            await asyncio.sleep(0.05)

    async def _async_main(self):
        """真正的异步主循环"""
        self.log_message.emit("🔌 [美股] 异步中枢启动成功，从底层初始化连接...")
        
        from ib_insync import IB
        self.ib = IB()
        self.ib.errorEvent += self.on_ib_error
        self.ib.execDetailsEvent += self._on_exec_details  # 💡 挂载成交触发，同步推送至 GUI
        self._poll_task = asyncio.create_task(self._poll_gui_commands())
        
        # 避免启动时立即触发全量扫描，初始化为当前 30M Bar 时间，等待下一个周期再触发
        now_et = self.get_us_now()
        # 💡 [策略修正] 引导启动时立即触发首次全量扫描（减去30分钟），不等待下一个周期
        last_scan_bar = now_et.replace(minute=(now_et.minute // 30) * 30, second=0, microsecond=0) - timedelta(minutes=30)
        last_heartbeat_min = -1
        last_reconnect_time = 0
        
        while self._is_running:
            try:
                # --- 每日收盘逻辑探测 (Phase 2) ---
                us_now = self.get_us_now()
                current_us_date = us_now.date()
                if self._last_close_date != current_us_date:
                    # 美股 16:00 正式收盘
                    if us_now.hour == 16 and us_now.minute >= 0:
                        await self._on_market_close_async()
                        self._last_close_date = current_us_date

                # 1. 连接维护 - 仅在 IB 模式下需要
                if self.venue == "IB" and not self.ib.isConnected():
                    now_ts = time.time()
                    if now_ts - last_reconnect_time > 15:
                        last_reconnect_time = now_ts
                        try:
                            import socket
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(2)
                            result = sock.connect_ex((self.host, self.port))
                            sock.close()
                            
                            if result != 0:
                                self.log_message.emit(f"❌ [美股] 目标端口不可达 ({self.host}:{self.port})，请确认 IB Gateway 已启动")
                                last_reconnect_time = now_ts + 20
                                continue

                            if not hasattr(self, '_id_offset'): self._id_offset = 0
                            target_client_id = self.client_id + self._id_offset
                            self._id_offset = (self._id_offset + 1) % 10
                            
                            self.log_message.emit(f"🔄 [美股] 发起连接 ({self.host}:{self.port}, ID:{target_client_id})...")
                            await asyncio.wait_for(self.ib.connectAsync(self.host, self.port, clientId=target_client_id), timeout=12)
                            self.log_message.emit(f"🔌 [美股] IB 连接成功 (ID:{target_client_id})")
                            # 💡 [数据源自适应] 允许没有订阅的情况下，通过 API 拉取 15-20分钟免费延迟行情，用以计算 ATR
                            try: self.ib.reqMarketDataType(3)
                            except: pass
                            # 异步进行仓位风控初始化 (方案丙)
                            if not self._trackers_initialized and not self._trackers_initializing:
                                self._trackers_initializing = True
                                asyncio.create_task(self._initialize_position_trackers())
                        except asyncio.TimeoutError:
                            self.log_message.emit("⚠️ [美股] IB 连接超时 (12s)")
                        except Exception as e:
                            self.log_message.emit(f"⚠️ [美股] 连接失败: {e}")
                    await asyncio.sleep(1)
                    continue

                # Schwab 初始化 - 仅在 Schwab 模式下需要
                if self.venue == "SCHWAB" and self.schwab_account_hash is None:
                    if os.path.exists(self.schwab_token_path):
                        await self._init_schwab_account_async()
                        if self.schwab_account_hash:
                            self.log_message.emit("🔌 [美股] Schwab API 准备就绪")
                    else:
                        self.log_message.emit("❌ [美股] 未找到 `schwab_token.json`，请先进行身份验证")
                        await asyncio.sleep(5)
                        continue

                # 安全检查：IB 模式连不上则跳过
                if self.venue == "IB" and not self.ib.isConnected():
                    await asyncio.sleep(1)
                    continue

                if self.venue == "IB" and self.ib.isConnected():
                    if not self._trackers_initialized and not self._trackers_initializing:
                        self._trackers_initializing = True
                        asyncio.create_task(self._initialize_position_trackers())

                # (指令处理已迁移至 _poll_gui_commands 后台协程)

                await asyncio.sleep(0.5)

                # 3.5 活性持仓止损监测 (方案丙)
                if not hasattr(self, '_last_stop_check_time'):
                    self._last_stop_check_time = time.time()
                elif time.time() - self._last_stop_check_time >= 60: # 60秒一检
                    self._last_stop_check_time = time.time()
                    
                    if self.is_trading_time():
                        await self._check_trailing_stops()
                        
                        # --- 🚨 [自动促成机制] 对暂存在重试池里的故障单进行全自动二次补救 ---
                        if getattr(self, 'retry_orders', {}):
                            for code, data in list(self.retry_orders.items()):
                                try:
                                    self.log_message.emit(f"🔄 [下单自愈] 正在重推异常订单至主队列: {code}")
                                    self.cmd_queue.put(('EXECUTE_TRADE', data))
                                    del self.retry_orders[code]
                                except Exception as er:
                                    self.log_message.emit(f"⚠️ [下单自愈] {code} 依旧失败: {er}")

                if self._is_paused:
                    continue

                # 4. 周期扫描逻辑
                now_et = us_now # 复用循环开始处定义的 us_now
                if not self.is_trading_time():
                    if not hasattr(self, '_notified_closed') or self._notified_closed != now_et.minute // 10:
                        self.log_message.emit(f"🌙 [美股] 当前非交易时段 ({now_et.strftime('%H:%M')}), 系统待机中...")
                        self._notified_closed = now_et.minute // 10
                    await asyncio.sleep(1.0)
                    continue

                # 扫描触发
                current_bar_et = now_et.replace(minute=(now_et.minute // 30) * 30, second=0, microsecond=0)
                should_scan = False
                
                # 💡 [调试追踪]
                # print(f"DEBUG: Checking scan: current_bar_et={current_bar_et}, last_scan_bar={last_scan_bar}, min={now_et.minute}")

                # 💡 [数据对齐] 已迁移至独立同步进程，此处仅触发本地数据库查询扫描
                if current_bar_et > last_scan_bar:
                    
                    # 💡 每个 30M 周期，在第 1 分钟后触发 (给 K 线一点落地时间)
                    if now_et.minute % 30 >= 1:
                        should_scan = True
                        self._current_bar_scanned = True
                elif not getattr(self, '_current_bar_scanned', False):
                    # 💡 补偿刚启动时当前 30M 周期还未跑过扫描的情况 (启动前 8 分钟内允许补扫)
                    if 1 <= (now_et.minute % 30) <= 8:
                        self.log_message.emit("⚡ [美股] 触发启动窗口期补全扫描...")
                        should_scan = True
                        self._current_bar_scanned = True

                if should_scan:
                    try:
                        # 放入后台任务执行，防止阻塞 GUI 指令队列（如查询资金）
                        if not hasattr(self, '_current_scan_task') or self._current_scan_task.done():
                            self._current_scan_task = asyncio.create_task(self._perform_strategy_scan_async())
                        else:
                            self.log_message.emit("⚡ [美股] 上一轮扫描尚未结束，跳过本次触发")
                    except Exception as e:
                        self.log_message.emit(f"❌ [美股] 异步扫描触发异常: {e}")
                        print(traceback.format_exc())
                    last_scan_bar = current_bar_et

            except Exception as e:
                self.log_message.emit(f"🚨 [美股] 循环内部错误: {e}")
                print(traceback.format_exc())
                await asyncio.sleep(5)

    async def _handle_gui_command(self, cmd_type, data):
        """异步指令处理器"""
        try:
            if cmd_type == 'FORCE_SCAN':
                asyncio.create_task(self._perform_strategy_scan_async(is_force_scan=True))
            elif cmd_type == 'QUERY_FUNDS':
                available, total, positions = await asyncio.wait_for(self.get_account_assets_async(), timeout=15)
                self.funds_updated.emit(available, total, positions)
            elif cmd_type == 'CLOSE_ALL':
                await asyncio.wait_for(self._close_all_positions_async(), timeout=30)
            elif cmd_type == 'EXECUTE_TRADE':
                c = data.get('code', 'Unknown')
                try:
                    self.log_message.emit(f"🚀 [美股] 发起指令执行: {c}")
                    await asyncio.wait_for(self._execute_trade_async(**data), timeout=20)
                    # 🟢 [风控加固] 强制睡眠 2.2s，确保整体频率控制在每 30 秒 15 次安全红线内 (30 / 15 = 2.0s)
                    await asyncio.sleep(2.2)
                except Exception as ex:
                    self.log_message.emit(f"⚠️ [指令下单异常] {c} 执行失败: {ex}，已安全载入重试队列。")
                    if not hasattr(self, 'retry_orders'): self.retry_orders = {}
                    self.retry_orders[c] = data
                finally:
                    if hasattr(self, '_pending_execute_codes') and c in self._pending_execute_codes:
                        self._pending_execute_codes.remove(c)
            elif cmd_type == 'MANUAL_TRADE':
                c = data.get('code', 'Unknown')
                self.log_message.emit(f"🕹️ [手动-{self.venue}] 发起指令: {data['action']} {c} ({data['qty']}股 @ ${data['price']:.2f})")
                await asyncio.wait_for(self._execute_trade_async(**data), timeout=20)
        except asyncio.TimeoutError:
            self.log_message.emit(f"⚠️ [指令] 指令 {cmd_type} 执行超时")

    async def _perform_strategy_scan_async(self, is_force_scan: bool = False):
        """执行异步策略扫描"""
        self.log_message.emit(f"🔍 [美股] 正在获取分组 '{self.watchlist_group}' 代码...")
        us_watchlist = {} # code -> name
        
        try:
            # 1. Fetch from Futu via executor (Sync -> Async)
            loop = asyncio.get_running_loop()
            futu_watchlist = await loop.run_in_executor(self.executor, self.get_futu_watchlist)
            us_watchlist.update(futu_watchlist)

            if self.venue == "IB" and self.ib and self.ib.isConnected():
                for p in self.ib.positions():
                    if p.contract.secType == 'STK':
                        c = f"US.{p.contract.symbol}"
                        if c not in us_watchlist:
                            us_watchlist[c] = p.contract.symbol
            elif self.venue == "SCHWAB" and self.schwab_account_hash:
                 await self._update_schwab_cache_async()
                 for p in self.schwab_positions_cache:
                      if p.get('instrument', {}).get('assetType') == 'EQUITY':
                           c = f"US.{p['instrument']['symbol']}"
                           if c not in us_watchlist:
                               us_watchlist[c] = p['instrument']['symbol']

            # [风控加固 Phase 8] 冷却隔离舱平移至后置 chan_30m K线计算内，以提高结构阻点判定精度
            filtered_codes = list(us_watchlist.keys())
            us_codes = sorted(filtered_codes)

            if not us_codes: 
                us_codes = ['US.AAPL', 'US.TSLA', 'US.NVDA']
                us_watchlist = {'US.AAPL': 'AAPL', 'US.TSLA': 'TSLA', 'US.NVDA': 'NVDA'}
            
            self.log_message.emit(f"📡 [美股] 异步并行扫描开始 (共 {len(us_codes)} 只, 并发: 5)...")
            
            # 1. 批量验证合约
            contracts = []
            for code in us_codes:
                symbol = code.split(".")[1] if "." in code else code
                contracts.append(Stock(symbol, 'SMART', 'USD'))
            
            symbol_to_contract = {}
            if self.venue == "IB":
                qualify_start = time.perf_counter()
                self.log_message.emit(f"🔍 [美股] 正在批量验证 {len(contracts)} 个合约...")
                try:
                    await self.ib.qualifyContractsAsync(*contracts)
                    qualify_time = time.perf_counter() - qualify_start
                    self.log_message.emit(f"✅ [美股] 合约验证完成 (耗时: {qualify_time:.2f}s)")
                except Exception as e:
                    self.log_message.emit(f"⚠️ [美股] 合约验证过程异常: {e}")
                # 建立 symbol -> contract 映射 (仅包含验证成功的)
                symbol_to_contract = {c.symbol: c for c in contracts if c.conId > 0}
            else:
                # Schwab 模式下，直接使用 symbol 字符串
                symbol_to_contract = {c.symbol: c for c in contracts}

            # 3. 提取大盘上下文环境 (S&P 500 SPY 动量/波动率) [风控加固 Phase 9]
            self.market_context = {}
            try:
                from Common.CEnum import KL_TYPE, AUTYPE
                from Chan import CChan
                from ChanConfig import CChanConfig
                from Common.StockUtils import get_default_data_sources
                idx_code = TRADING_CONFIG.get("us_market_index", "US.SPY")
                data_sources = get_default_data_sources(idx_code)
                if "custom:SQLiteAPI.SQLiteAPI" not in data_sources:
                     data_sources = ["custom:SQLiteAPI.SQLiteAPI"] + data_sources
                     
                chan_idx = None
                for src in data_sources:
                     try:
                          chan_idx = CChan(
                              code=idx_code,
                              begin_time=(datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d"),
                              data_src=src,
                              lv_list=[KL_TYPE.K_30M],
                              config=CChanConfig(CHAN_CONFIG),
                              autype=AUTYPE.QFQ
                          )
                          if chan_idx.lv_list and len(list(chan_idx[0].klu_iter())) >= 10:
                               break
                     except Exception:
                          continue
                          
                if chan_idx and chan_idx.lv_list and len(list(chan_idx[0].klu_iter())) >= 10:
                    kl_list = list(chan_idx[0].klu_iter())
                    idx_k = kl_list[-1]
                    if len(kl_list) >= 6:
                         pre_5 = kl_list[-6]
                         self.market_context["index_roc_5"] = (idx_k.close - pre_5.close) / (pre_5.close + 1e-7)
                    amps = []
                    for k in kl_list[-10:]:
                         if k.low > 0: amps.append((k.high - k.low) / k.low)
                    if amps:
                         self.market_context["index_volatility"] = sum(amps) / len(amps)
                    self.log_message.emit(f"🌏 美股大盘诊断 ({idx_code}): 5周期动量={self.market_context.get('index_roc_5', 0):.4f}, 动能方差={self.market_context.get('index_volatility', 0):.4f}")
            except Exception as e_idx:
                 self.log_message.emit(f"⚠️ 提取美股大盘环境特征失败: {e_idx}")

            # 3. 串行分析 (依照港股逻辑，稳定可靠)
            scan_start = time.perf_counter()
            self.log_message.emit(f"🚀 [美股] 开始策略扫描 (共 {len(us_codes)} 只)...")
            
            # 💡 [持仓防重买] 在批量扫描前，做一次全量持仓快照预载
            all_pos = {}
            try:
                _, _, positions = await self.get_account_assets_async()
                all_pos = {p['symbol']: p['qty'] for p in positions}
            except Exception as pos_e:
                 self.log_message.emit(f"⚠️ [扫描前置] 持仓预载失败: {pos_e}")
            
            tasks = []
            for i, code in enumerate(us_codes, 1):
                if not self._is_running: break
                try:
                    symbol = code.split(".")[1] if "." in code else code
                    contract = symbol_to_contract.get(symbol)
                    name = us_watchlist.get(code, "")
                    tasks.append(self._analyze_stock_async(code, name=name, index=i, total=len(us_codes), contract=contract, is_force_scan=is_force_scan, all_pos=all_pos))
                except Exception as e:
                    self.log_message.emit(f"❌ [美股] 构建 {code} 任务报错: {e}")
            
            if tasks:
                await asyncio.gather(*tasks)
            
            total_scan_time = time.perf_counter() - scan_start
            self.log_message.emit(f"✅ [美股] 策略扫描完成, 总耗时: {total_scan_time:.2f}s")
            
            # 🟢 [风控加固] 扫描后自动检查上下文状态，防止撑爆
            try:
                MemorySummarizer().check_and_compress()
            except: pass
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 扫描过程异常: {e}")

    async def _analyze_stock_async(self, code: str, name: str = "", index: int = 0, total: int = 0, contract=None, is_force_scan: bool = False, all_pos: dict = None):
        """异步分析单只股票"""
        prefix = f"[{index}/{total}] "
        await asyncio.sleep(0.01)
        self.log_message.emit(f"🔍 [策略扫描] 正在分析 {code} {name} {prefix}...")
        # 让出事件循环控制权，防阻塞 GUI 操作（重要！）
        await asyncio.sleep(0.01)
        
        # --- 在线拉取数据模式 ---
        try:
            now_t = datetime.now()
            # ⚓ 锚定截止时间到上一个收盘的 30M Bar，确保只拿 100% 完整收盘的数据测算，避免未收盘波浮动偏差
            end_time = now_t.replace(minute=(now_t.minute // 30) * 30, second=0, microsecond=0)
            end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
            start_time_30m = end_time - timedelta(days=60)
            start_30m_str = start_time_30m.strftime("%Y-%m-%d")

            await asyncio.sleep(0.01)
            
            analysis_start = time.perf_counter()
            # 💡 [美股-信号一致性] 使用 self.chan_config（已应用 MARKET_SPECIFIC_CONFIG['US'] 专属参数，
            # 如 bs_type='2,2s,3a,3b'，去掉1买点），确保与后台持仓风控/止损逻辑一致
            _us_chan_config = self.chan_config
            
            loop = asyncio.get_running_loop()
            def create_chan_30m():
                try:
                    from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE
                    from Chan import CChan
                    # 💡 [美股-数据源策略] 优先读本地 SQLite（极速，无网络依赖）；
                    # 本地数据不足（<10根K线）时才 fallback 到 Schwab 在线拉取
                    try:
                        result = CChan(
                            code=code,
                            begin_time=start_30m_str,
                            end_time=end_time_str,
                            data_src="custom:SQLiteAPI.SQLiteAPI",
                            lv_list=[KL_TYPE.K_30M],
                            config=_us_chan_config,
                            autype=AUTYPE.QFQ
                        )
                        if result and len(result[0]) >= 10:
                            return result
                    except Exception:
                        pass
                    # 兜底: Schwab 在线拉取
                    return CChan(
                        code=code,
                        begin_time=start_30m_str,
                        end_time=end_time_str,
                        data_src=DATA_SRC.SCHWAB,
                        lv_list=[KL_TYPE.K_30M],
                        config=_us_chan_config,
                        autype=AUTYPE.QFQ
                    )
                except Exception as e:
                    print(f"❌ create_chan_30m 异常 ({code}): {e}")
                    import traceback
                    print(traceback.format_exc())
                    return None

            async with self.scan_semaphore:
                chan_30m = await loop.run_in_executor(None, create_chan_30m)
            analysis_time = time.perf_counter() - analysis_start
            
            # 💡 依照港股规范，不打印耗时和点位信息，仅在发现信号时打印 
            # self.log_message.emit(f"📊 {prefix}{code} [在线 Schwab, 分析: {analysis_time:.2f}s]")

            if chan_30m is None or len(chan_30m[0]) == 0: return

            # 🛡️ [风控加固 Phase 8] 结构锁区检查 (美股防下探拉锯)
            if hasattr(self, 'structure_barrier') and code in self.structure_barrier:
                barrier_ts = self.structure_barrier[code]['lock_time_ts']
                has_new_pivot = False
                if hasattr(chan_30m[0], 'zs_list'):
                    for zs in chan_30m[0].zs_list:
                        if zs.begin.time.ts > barrier_ts:
                            has_new_pivot = True
                            break
                if not has_new_pivot:
                    return
                else:
                    self.log_message.emit(f"🔓 [美股-风控] {code} 脱离旧有止损结构，已刷新中枢，解锁准入。")
                    del self.structure_barrier[code]



            bsp_list = chan_30m.get_latest_bsp(number=0)
            if bsp_list:
                bsp_list = sorted(bsp_list, key=lambda x: str(x.klu.time), reverse=True)[:1]
        except Exception as e_online:
             self.log_message.emit(f"❌ [美股] 在线拉取 {code} 异常: {e_online}")
             return
        
        us_now = self.get_us_now()
        in_market = self.is_trading_time()
        # 交易时段：仅接受 1 小时内的信号；非交易时段：放宽到 2 小时（收盘后复盘用）
        window_sec = 3600 if in_market else 7200
        
        for bsp in bsp_list:
            bsp_dt = datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day, 
                              bsp.klu.time.hour, bsp.klu.time.minute, bsp.klu.time.second)
            is_valid_time = is_force_scan or (us_now - bsp_dt).total_seconds() <= window_sec
            if not is_valid_time:
                # 🛡️ 信号时间超出窗口期，静默丢弃（不打日志，不下单）
                continue
            
            if True:  # 保留缩进层级
                sig_key = f"{code}_{str(bsp.klu.time)}_{bsp.type2str()}"
                if sig_key in self.notified_signals: continue
                
                self.notified_signals[sig_key] = us_now.strftime("%Y-%m-%d %H:%M:%S")
                self._save_notified_signals()  # 立即持久化，防止崩溃后丢失
                self.log_message.emit(f"🎯 [美股] {code} 发现信号: {bsp.type2str()} @ {bsp.klu.time}")
                
                # 🟢 [排障优化] 在线拉取 5M 数据前，先核对持仓与在单
                symbol = code.split('.')[-1]
                pos_qty = all_pos.get(symbol, 0) if all_pos is not None else self.get_position_quantity(code)
                has_pending = self.check_pending_orders(code, 'BUY' if bsp.is_buy else 'SELL')
                current_total_pos = len(all_pos) if all_pos is not None else 0

                # 1. 持仓方向性拦截
                if bsp.is_buy:
                    if current_total_pos >= TRADING_CONFIG.get('max_total_positions', 10) and pos_qty <= 0:
                        # self.log_message.emit(f"🚫 [美股] {code} 触发持位上限限制 (当前: {current_total_pos})")
                        continue
                    if pos_qty > 0:
                        # self.log_message.emit(f"ℹ️ [美股] {code} 已有持仓 ({pos_qty})，跳过买入")
                        continue
                else:
                    if pos_qty <= 0:
                        # self.log_message.emit(f"ℹ️ [美股] {code} 无持仓，跳过卖出信号")
                        continue

                # 2. 在单拦截
                if has_pending:
                    # self.log_message.emit(f"⏳ [美股] {code} 存在未完成同向订单，跳过当前信号")
                    continue

                chan_5m = None
                try:
                    # 在线获取 5M 数据
                    start_time_5m = end_time - timedelta(days=7)
                    start_5m_str = start_time_5m.strftime("%Y-%m-%d")
                    
                    def create_chan_5m():
                        try:
                            # 💡 [美股-数据源策略+信号一致性] 使用 _us_chan_config，优先本地 SQLite，失败才 fallback Schwab
                            try:
                                r5 = CChan(
                                    code=code,
                                    begin_time=start_5m_str,
                                    end_time=end_time_str,
                                    data_src="custom:SQLiteAPI.SQLiteAPI",
                                    lv_list=[KL_TYPE.K_5M],
                                    config=_us_chan_config,
                                    autype=AUTYPE.QFQ
                                )
                                if r5 and len(r5[0]) >= 10:
                                    return r5
                            except Exception:
                                pass
                            # 兜底: Schwab 在线拉取
                            return CChan(
                                code=code,
                                begin_time=start_5m_str,
                                end_time=end_time_str,
                                data_src=DATA_SRC.SCHWAB,
                                lv_list=[KL_TYPE.K_5M],
                                config=_us_chan_config,
                                autype=AUTYPE.QFQ
                            )
                        except Exception as e:
                            logger.warning(f"Error creating CChan 5M for {code}: {e}")
                            return None
                    async with self.scan_semaphore:
                        chan_5m = await loop.run_in_executor(None, create_chan_5m)
                    if chan_5m:
                        self.log_message.emit(f"   ↳ {code} 5M数据线拉取完成")
                except Exception as e5m:
                    logger.warning(f"5M cache logic failed for {code}: {e5m}")

                self.executor.submit(self._handle_signal_sync, code, bsp, chan_30m, chan_5m, name=name,
                                    pos_qty=pos_qty, has_pending=has_pending, current_total_pos=current_total_pos,
                                    is_valid_time=is_valid_time, window_sec=window_sec)

    async def _update_schwab_cache_async(self):
        """异步更新 Schwab 持仓和订单缓存 (使用线程池防止阻塞)"""
        if not self.schwab_account_hash: return
        loop = asyncio.get_running_loop()
        token = self.schwab_api._get_access_token()
        
        def fetch_schwab():
            p_res, o_res = [], []
            try:
                # Positions
                p_url = f"https://api.schwabapi.com/trader/v1/accounts/{self.schwab_account_hash}"
                resp1 = requests.get(p_url, headers={'Authorization': f'Bearer {token}'}, params={'fields': 'positions'})
                if resp1.status_code == 200:
                    p_res = resp1.json().get('securitiesAccount', {}).get('positions', [])
                
                # Orders
                o_url = f"https://api.schwabapi.com/trader/v1/accounts/{self.schwab_account_hash}/orders"
                resp2 = requests.get(o_url, headers={'Authorization': f'Bearer {token}'})
                if resp2.status_code == 200:
                    o_res = resp2.json()
            except Exception as e:
                logger.warning(f"更新 Schwab 缓存异常: {e}")
            return p_res, o_res

        p, o = await loop.run_in_executor(self.executor, fetch_schwab)
        self.schwab_positions_cache = p
        self.schwab_orders_cache = o if isinstance(o, list) else []

    def get_position_quantity(self, code: str) -> int:
        symbol = code.split('.')[-1]
        if self.venue == "IB":
            if self.ib is None or not self.ib.isConnected(): return 0
            for p in self.ib.positions():
                if p.contract.symbol == symbol: return int(p.position)
        elif self.venue == "SCHWAB":
            for p in self.schwab_positions_cache:
                if p.get('instrument', {}).get('symbol') == symbol:
                    return int(p.get('longQuantity', 0) - p.get('shortQuantity', 0))
        elif self.venue == "FUTU":
            # 🛡️ [风控加固] 实时从富途持仓接口查询，防止缓存脏数据导致 SELL 穿透
            try:
                if hasattr(self, 'trd_ctx') and self.trd_ctx:
                    from futu import TrdEnv
                    refresh = (self.trd_env == TrdEnv.SIMULATE)
                    ret, data = self.trd_ctx.position_list_query(
                        code=f"US.{symbol}",
                        trd_env=self.trd_env,
                        refresh_cache=refresh
                    )
                    if ret == 0 and not data.empty:
                        row = data[data['code'] == f"US.{symbol}"]
                        if not row.empty:
                            return int(row.iloc[0].get('can_sell_qty', row.iloc[0].get('qty', 0)))
            except Exception as e:
                logger.warning(f"[FUTU] get_position_quantity {symbol} 异常: {e}")
        return 0

    def check_pending_orders(self, code: str, side: str) -> bool:
        symbol = code.split('.')[-1]
        if self.venue == "IB":
            if self.ib is None or not self.ib.isConnected(): return False
            for trade in self.ib.openTrades():
                if trade.contract.symbol == symbol and trade.order.action == side.upper():
                    if trade.orderStatus.status in ('PendingSubmit', 'PreSubmitted', 'Submitted'):
                        return True
        elif self.venue == "SCHWAB":
            for order in getattr(self, 'schwab_orders_cache', []):
                for leg in order.get('orderLegCollection', []):
                    if leg.get('instrument', {}).get('symbol') == symbol and leg.get('instruction') == side.upper():
                        # Schwab 订单状态：PENDING_ACTIVATION, PENDING_CANCEL, PENDING_REPLACE, QUEUED, ACCEPTED, WORKING
                        if order.get('status') in ('WORKING', 'ACCEPTED', 'QUEUED'):
                            return True
        elif self.venue == "FUTU":
            try:
                if hasattr(self, 'trd_ctx') and self.trd_ctx:
                    from futu import TrdSide, OrderStatus
                    ret, data = self.trd_ctx.order_list_query(trd_env=getattr(self, 'trd_env', None))
                    if ret == 0 and not data.empty:
                        target_side = TrdSide.BUY if side.upper() == "BUY" else TrdSide.SELL
                        matched = data[(data['code'] == f"US.{symbol}") & (data['trd_side'] == target_side)]
                        for _, row in matched.iterrows():
                            if row['order_status'] in [OrderStatus.SUBMITTED, OrderStatus.WAITING_SUBMIT]:
                                return True
            except Exception as e:
                logger.warning(f"[FUTU] check_pending_orders {symbol} 异常: {e}")
        return False

    async def get_account_assets_async(self) -> Tuple[float, float, list]:
        """异步获取账户资产"""
        if self.venue == "IB":
            if self.ib and self.ib.isConnected():
                return await self._get_ib_assets_async()
        elif self.venue == "SCHWAB":
            if self.schwab_account_hash:
                return await self._get_schwab_assets_async()
        elif self.venue == "FUTU":
            return await self._get_futu_assets_async()
        return 0.0, 0.0, []

    async def _get_ib_assets_async(self) -> Tuple[float, float, list]:
        """原有的 IB 资金获取逻辑"""
        try:
            # 1. 直接获取缓存值 (ib_insync 会自动维护同步)
            vals = self.ib.accountValues()
            port = self.ib.portfolio()
            
            # 2. 如果缓存为空，等待 0.8s 让数据流进来
            if not vals:
                await asyncio.sleep(0.8)
                vals = self.ib.accountValues()
                port = self.ib.portfolio()
            
            available, total = 0.0, 0.0
            found_tags = []
            available_tags = ('AvailableFunds', 'AvailableFunds-S', 'FullAvailableFunds', 'FullAvailableFunds-S', 'CashBalance', 'TotalCashBalance')
            net_liq_tags = ('NetLiquidation', 'NetLiquidation-S', 'NetLiquidationByCurrency', 'EquityWithLoanValue')
            
            for v in vals:
                if v.tag in available_tags or v.tag in net_liq_tags:
                    found_tags.append(f"{v.tag}({v.currency}):{v.value}")
                try: val_f = float(v.value)
                except: continue
                if v.tag in available_tags:
                    if v.currency == 'USD': available = val_f
                    elif v.currency == 'BASE' and available == 0.0: available = val_f
                    elif available == 0.0: available = val_f
                if v.tag in net_liq_tags:
                    if v.currency == 'USD': total = val_f
                    elif v.currency == 'BASE' and total == 0.0: total = val_f
                    elif total == 0.0: total = val_f
            
            positions_data = []
            actual_items = list(port)
            if not actual_items:
                # 💡 [兜底读取] 如果 portfolio() 缓冲尚未同步，尝试调用同步 positions() 列表
                pos_list = self.ib.positions()
                
                # 🛡️ [补救逻辑] 通过 reqTickers 获取实时价格，避免错误地将成本价 (avgCost) 报送为市价
                ticker_contracts = [p.contract for p in pos_list if p.position != 0]
                tickers = {}
                if ticker_contracts:
                    try:
                        ticker_data = self.ib.reqTickers(*ticker_contracts)
                        tickers = {t.contract.symbol: t for t in ticker_data}
                    except: pass

                for p in pos_list:
                    if p.position != 0:
                        symbol = p.contract.symbol
                        ticker = tickers.get(symbol)
                        # 优先取 last, 兜底取 close 或 avgCost (极简兜底)
                        mkt_price = getattr(ticker, 'last', 0) or getattr(ticker, 'close', 0) or p.avgCost
                        
                        positions_data.append({
                            'symbol': symbol,
                            'qty': int(p.position),
                            'mkt_value': round(p.position * mkt_price, 2),
                            'avg_cost': round(p.avgCost, 2),
                            'mkt_price': mkt_price
                        })
            else:
                for item in actual_items:
                    if item.position != 0:
                        positions_data.append({
                            'symbol': item.contract.symbol,
                            'qty': int(item.position),
                            'mkt_value': round(item.marketValue, 2),
                            'avg_cost': round(item.averageCost, 2),
                            'mkt_price': item.marketPrice
                        })
            return available, total, positions_data
        except Exception as e:
            self.log_message.emit(f"❌ IB 账户查询异常: {e}")
            return 0.0, 0.0, []

    async def _get_schwab_assets_async(self) -> Tuple[float, float, list]:
        """通过 Schwab API 获取账户资产"""
        try:
            url = f"https://api.schwabapi.com/trader/v1/accounts/{self.schwab_account_hash}"
            token = self.schwab_api._get_access_token()
            resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, params={'fields': 'positions'})
            if resp.status_code == 401:
                token = self.schwab_api._refresh_access_token()
                resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, params={'fields': 'positions'})
            
            if resp.status_code == 200:
                data = resp.json().get('securitiesAccount', {})
                available = float(data.get('currentBalances', {}).get('buyingPower', 0.0))
                total = float(data.get('currentBalances', {}).get('liquidationValue', 0.0))
                positions = []
                for p in data.get('positions', []):
                    positions.append({
                        'symbol': p['instrument']['symbol'],
                        'qty': int(p['longQuantity'] - p['shortQuantity']),
                        'mkt_value': float(p['marketValue']),
                        'avg_cost': float(p['averagePrice'])
                    })
                return available, total, positions
        except Exception as e:
             self.log_message.emit(f"⚠️ Schwab 账户查询失败: {e}")
        return 0.0, 0.0, []

    def get_account_assets(self) -> Tuple[float, float, list]:
        """同步接口 (GUI 兼容)"""
        # 内部强制使用异步包装以支持多源
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在运行，启动一个线程来执行
                with ThreadPoolExecutor() as pool:
                    return pool.submit(lambda: asyncio.run(self.get_account_assets_async())).result()
            else:
                return asyncio.run(self.get_account_assets_async())
        except:
             return 0.0, 0.0, []

    async def _cancel_all_pending_orders_async(self) -> int:
        """异步撤销所有未成交订单 (US)"""
        count = 0
        try:
            if self.venue == "IB":
                self.ib.reqGlobalCancel()
                await asyncio.sleep(0.5) # 给一点 API 响应时间
                count = len([t for t in self.ib.trades() if not t.isDone()])
                self.log_message.emit(f"✅ [收盘-IB] 已向柜台发送全局撤单指令 (ReqGlobalCancel)")
            elif self.venue == "SCHWAB":
                url = f"https://api.schwabapi.com/trader/v1/accounts/{self.schwab_account_hash}/orders"
                token = self.schwab_api._get_access_token()
                resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, params={'status': 'WORKING'})
                if resp.status_code == 200:
                    orders = resp.json()
                    for o in orders:
                        oid = o['orderId']
                        del_resp = requests.delete(f"{url}/{oid}", headers={'Authorization': f'Bearer {token}'})
                        if del_resp.status_code in (200, 204):
                            count += 1
                    self.log_message.emit(f"✅ [收盘-Schwab] 已清理 {count} 笔 WORKING 状态挂单")
            elif self.venue == "FUTU":
                from futu import OrderStatus
                ret, data = self.trd_ctx.order_list_query(trd_env=self.trd_env)
                if ret == RET_OK and not data.empty:
                    pending = data[data['status'].isin([OrderStatus.SUBMITTING, OrderStatus.SUBMITTED, OrderStatus.WAITING_SUBMIT, OrderStatus.FILLED_PART])]
                    for _, row in pending.iterrows():
                        self.trd_ctx.cancel_order(row['order_id'])
                        count += 1
                self.log_message.emit(f"✅ [收盘-Futu] 已清理 {count} 笔挂单")
            return count
        except Exception as e:
            self.log_message.emit(f"❌ [收盘] 撤单失败: {e}")
            return 0

    async def _on_market_close_async(self):
        """美股收盘异步处理例程"""
        # 周末不执行
        us_now = self.get_us_now()
        if us_now.weekday() >= 5:
            return
        self.log_message.emit("🌆 [系统] 检测到美股收市时间(16:00 ET)，正在执行每日收盘流程...")
        
        # 1. 撤销当日挂单
        cancelled = await self._cancel_all_pending_orders_async()
        
        # 2. 生成结算摘要报告
        available, total, positions = await self.get_account_assets_async()
        report_list = []
        report_list.append(f"\n================== [美股] 每日收盘结算报告 ({self.venue}) ==================")
        
        report_list.append(f"📊 1. 资产全貌")
        report_list.append(f"   • 总资产水位: ${total:,.2f}")
        report_list.append(f"   • 剩余可用资金: ${available:,.2f}")
        report_list.append(f"   • 活跃止损追踪舱: {len(getattr(self, 'position_trackers', {}))} 只标的")
        
        report_list.append(f"\n📈 2. 今日交易清单 (Filled Trades)")
        try:
            import sqlite3
            conn = sqlite3.connect(self.db.db_path)
            cursor = conn.cursor()
            today_str = datetime.now().strftime('%Y-%m-%d')
            
            # 查买入单
            cursor.execute("SELECT code, name, entry_price, quantity FROM live_trades WHERE date(entry_time) = ? AND market = 'US'", (today_str,))
            buys = cursor.fetchall()
            for b in buys:
                report_list.append(f"   • [买入] {b[0]} ({b[1]}) | 成交: ${b[2]:.2f} | 数量: {b[3]}股")
                
            # 查卖出单
            cursor.execute("SELECT code, exit_price, exit_reason, pnl_pct FROM live_trades WHERE date(exit_time) = ? AND market = 'US'", (today_str,))
            sells = cursor.fetchall()
            for s in sells:
                report_list.append(f"   • [卖出/止损] {s[0]} | 出场: ${s[1]:.2f} | 理由: {s[2]} | PnL损耗: {s[3]:.2f}%")
        except Exception as e_db:
             report_list.append(f"   • 获取本地数据库报表异常: {e_db}")

        report_list.append(f"\n🛑 3. 系统除耗")
        report_list.append(f"   • 当日自动撤单: {cancelled} 笔")
        report_list.append(f"   • 处于结构止损锁舱数: {len(getattr(self, 'structure_barrier', {}))} 个")
        report_list.append("==========================================================")
        
        report = "\n".join(report_list)
        self.log_message.emit(report)
        
        # 3. Discord 推送
        if self.discord_bot:
            await self.discord_bot.send_notification(report)
            
        self.log_message.emit(f"✅ [收盘] 美股 {self.venue} 结转动作已完成。")

    async def _execute_trade_async(self, code: str, action: str, price: float, **kwargs):
        """异步下单 - 根据 self.venue 执行"""
        symbol = code.split('.')[-1]
        qty = kwargs.get('qty', 0)
        if qty == 0 and action.upper() == "BUY":
            # 🟢 [风控加固 Phase 9] 对齐港股，使用风险管理器计算动态仓位
            available, total, _ = await self.get_account_assets_async()
            score = kwargs.get('visual_score', 0)
            ml_prob = kwargs.get('ml_prob', 0)
            atr_value = kwargs.get('atr_value', 1.0)
            
            qty = self.risk_manager.calculate_position_size(
                code=code,
                available_funds=available,
                current_price=price,
                signal_score=score,
                risk_factor=1.0,
                atr=atr_value,
                atr_multiplier=2.0,
                total_assets=total,
                lot_size=1, # 美股一手为1股
                ml_prob=ml_prob
            )
            if qty <= 0:
                self.log_message.emit(f"⚠️ [美股] 计算出的买入数量为 0，跳过下单。")
                return
        
        # 预先检查并标准化动作
        action = action.upper()

        # 🟢 [风控加固] 防止没有持仓就发出卖出指令（特别是富途不支持美股空单，会报错持仓不足）
        if action == "SELL":
            _, _, positions = await self.get_account_assets_async()
            current_qty = sum(p.get('can_sell_qty', p['qty']) for p in positions if p['symbol'] == symbol or p.get('code') == code)
            
            if current_qty <= 0:
                self.log_message.emit(f"⚠️ [美股] {code} 触发卖出信号，但账户无可用【可卖持仓】(可能已被止损锁单)，跳过本次下单。")
                return
            
            # 🟢 [风控加固] 止损/平仓单若未显式传参 qty，自动拉满至当前全部可用持仓 
            if qty <= 0:
                qty = current_qty

        # 🛡️ [风控加固 Phase 9] 冷却期激活 (凡是下单，进入 20 分钟观察冷却防止反复进出)
        if hasattr(self, 'trade_cooldown'):
            self.trade_cooldown[code] = time.time()

        if self.venue == "SCHWAB":
            if self.schwab_account_hash:
                # 注意：_execute_schwab_order_async 需要同步更新以支持成功后的 DB 记录
                success = await self._execute_schwab_order_async(code, action, qty, price)
                if success:
                    self._record_trade_to_db(code, action, qty, price, **kwargs)
            else:
                self.log_message.emit("❌ [美股-Schwab] 账户未初始化，无法下单")
            return
            
        if self.venue == "FUTU":
            # 🛡️ [风控加固] SELL 前实时核查持仓，防止无仓卖出
            if action == "SELL":
                curr_qty = self.get_position_quantity(code)
                if curr_qty <= 0:
                    self.log_message.emit(f"ℹ️ [美股-Futu] {symbol} Futu 实际无持仓，跳过卖出指令")
                    return
                qty = min(qty, curr_qty)
                if self.check_pending_orders(code, 'SELL'):
                    self.log_message.emit(f"⏳ [美股-Futu] {symbol} 存在未完成 SELL 订单，跳过当前指令")
                    return
            await self._execute_futu_order_async(code, action, qty, price)
            return

        # IB 下单
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            await self.ib.qualifyContractsAsync(contract)
            
            if price <= 0:
                self.log_message.emit(f"⚠️ {symbol} 价格异常 ({price})，无法计算下单数量")
                return
                
            if action == "SELL":
                curr_qty = self.get_position_quantity(code)
                # 🛡️ [风控加固] 拦截在单，防止队列内高频 or 延迟的双 SELL 击穿持仓
                if self.check_pending_orders(code, 'SELL'):
                    self.log_message.emit(f"⏳ [美股-IB] {symbol} 存在未完成 SELL 订单，跳过当前指令")
                    return
                qty = min(qty, curr_qty)
                if qty <= 0: return

            limit_price = round(price * 1.01, 2) if action == "BUY" else round(price * 0.99, 2)
            
            order = LimitOrder(action, qty, limit_price)
            trade = self.ib.placeOrder(contract, order)
            self.log_message.emit(f"🚀 [美股-IB] 限价单提交成功: {symbol} {action} {qty} @ ${limit_price:.2f}")
            
            # 记录交易
            self._record_trade_to_db(code, action, qty, limit_price, **kwargs)

            # 启动订单跟踪
            asyncio.create_task(
                self._track_order_status_async(None, code, action, qty, limit_price, "IB", trade)
            )
            
        except Exception as e:
            self.log_message.emit(f"❌ [美股-{self.venue}] 下单失败: {e}")

    async def _track_order_status_async(self, order_id: str, code: str, action: str, qty: int, price: float, venue: str, trade_obj=None):
        """轮询订单成交状态，汇报执行情况 (美股多通道)"""
        import time as _time
        import asyncio

        for attempt in range(12):  # 最多 60 秒
            await asyncio.sleep(5)
            try:
                status = ""
                filled_qty = 0
                filled_avg = 0.0
                status_str = ""

                if venue == "FUTU":
                    from futu import OrderStatus, RET_OK
                    futu_acc_id = getattr(self, 'futu_acc_id', 0)
                    ret, data = self.trd_ctx.order_list_query(
                        order_id=order_id, trd_env=self.trd_env, acc_id=futu_acc_id
                    )
                    if ret != RET_OK or data.empty: continue
                    
                    row = data.iloc[0]
                    fut_status = row.get('order_status', '')
                    filled_qty = int(row.get('dealt_qty', 0))
                    filled_avg = float(row.get('dealt_avg_price', 0))
                    
                    status_map = {
                        OrderStatus.SUBMITTED: "已提交",
                        OrderStatus.FILLED_ALL: "全部成交 ✅",
                        OrderStatus.FILLED_PART: "部分成交",
                        OrderStatus.CANCELLED_ALL: "已撤单",
                        OrderStatus.CANCELLED_PART: "部分撤单",
                        OrderStatus.FAILED: "失败 ❌",
                    }
                    status_str = status_map.get(fut_status, str(fut_status))
                    
                    if fut_status in (OrderStatus.FILLED_ALL,):
                        status = "FILLED"
                    elif fut_status in (OrderStatus.CANCELLED_ALL, OrderStatus.CANCELLED_PART, OrderStatus.FAILED):
                        status = "CLOSED"
                    elif fut_status == OrderStatus.FILLED_PART:
                        status = "PARTIAL"

                elif venue == "IB" and trade_obj:
                    # IB 的 Trade 对象属性自动在事件循环中更新
                    ib_status = trade_obj.orderStatus.status
                    filled_qty = int(trade_obj.orderStatus.filled)
                    filled_avg = float(trade_obj.orderStatus.avgFillPrice)
                    
                    # 💡 [DEBUG] 打印 IB 实时状态，帮助排查日志缺失问题
                    if attempt % 3 == 0:
                         print(f"[DEBUG-IB-Track] {code} Status: {ib_status}, Filled: {filled_qty}/{qty}")
                    
                    ib_map = {
                        "ApiPending": "等待提交",
                        "PendingSubmit": "等待提交",
                        "PreSubmitted": "预提交",
                        "Submitted": "已提交",
                        "ApiCancelled": "已撤单",
                        "Cancelled": "已撤单",
                        "Filled": "全部成交 ✅",
                        "Inactive": "已失效 ❌"
                    }
                    status_str = ib_map.get(ib_status, ib_status)
                    
                    if ib_status == "Filled":
                        status = "FILLED"
                    elif ib_status in ("Cancelled", "ApiCancelled", "Inactive"):
                        status = "CLOSED"
                    elif filled_qty > 0 and filled_qty < qty:
                        status = "PARTIAL"

                elif venue == "SCHWAB":
                    # Schwab REST 轮询暂简略处理
                    break

                if status == "FILLED":
                    # 🛡️ [平仓锁定] 如果是卖出平仓，记录到今日锁定名单，防止循环下单
                    if action.upper() == "SELL":
                        self.sold_today.add(code)
                        self.log_message.emit(f"🔒 [单日平仓锁] {code} 已成交平仓，今日锁定卖出逻辑防止循环")
                    
                    self.log_message.emit(
                        f"📋 [美股-成交] {code} {action} {status_str}: "
                        f"{filled_qty}股 @ ${filled_avg:.2f}"
                    )
                    if self.discord_bot and hasattr(self.discord_bot, 'loop') and self.discord_bot.loop and self.discord_bot.loop.is_running():
                        msg = (
                            f"📋 **美股订单成交 ({venue})**\n"
                            f"股票: {code}\n"
                            f"方向: {action}\n"
                            f"成交: {filled_qty}股 @ ${filled_avg:.2f}\n"
                            f"时间: {datetime.now().strftime('%H:%M:%S')}"
                        )
                        await self.discord_bot.send_notification(msg)
                    return

                if status == "CLOSED":
                    self.log_message.emit(
                        f"📋 [美股-订单] {code} {action} {status_str} (已成交: {filled_qty}/{qty}股)"
                    )
                    return

                if status == "PARTIAL":
                    self.log_message.emit(
                        f"⏳ [美股-订单] {code} {action} 部分成交中 ({venue}): {filled_qty}/{qty}股 @ ${filled_avg:.2f}"
                    )

            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"[美股] 订单跟踪异常: {e}")

        self.log_message.emit(f"⏰ [美股-订单] {code} {action} 60秒内未完全成交，请手动检查系统 ({venue})")

    def _record_trade_to_db(self, code: str, action: str, qty: int, price: float, **kwargs):
        """记录交易到数据库 (优化F)"""
        try:
            if action.upper() == "BUY":
                self.db.record_live_trade({
                    'code': code,
                    'name': kwargs.get('name', '美股'),
                    'market': 'US',
                    'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'entry_price': price,
                    'quantity': qty,
                    'signal_type': kwargs.get('signal_type', '未知'),
                    'ml_prob': kwargs.get('ml_prob', 0),
                    'visual_score': kwargs.get('visual_score', 0),
                    'status': 'open'
                })
            else:
                exit_reason = kwargs.get('exit_reason', '信号卖出')
                self.db.close_live_trade(code, price, exit_reason)
        except Exception as e:
            logger.error(f"[美股-DB] 记录交易失败: {e}")

    async def _init_schwab_account_async(self):
        """初始化 Schwab 账户信息 (获取 AccountHash)"""
        try:
            url = "https://api.schwabapi.com/trader/v1/accounts/accountNumbers"
            token = self.schwab_api._get_access_token()
            resp = requests.get(url, headers={'Authorization': f'Bearer {token}'})
            if resp.status_code == 401:
                token = self.schwab_api._refresh_access_token()
                resp = requests.get(url, headers={'Authorization': f'Bearer {token}'})
            
            if resp.status_code == 200:
                accounts = resp.json()
                if accounts:
                    self.schwab_account_hash = accounts[0]['hashValue']
                    self.log_message.emit(f"✅ [美股-Schwab] 账户初始化成功 (Hash: {self.schwab_account_hash[:8]}...)")
                else:
                    self.log_message.emit("⚠️ [美股-Schwab] 未找到可用账户")
            else:
                self.log_message.emit(f"❌ [美股-Schwab] 账户初始化失败: {resp.status_code}")
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股-Schwab] 初始化异常: {e}")

    async def _execute_schwab_order_async(self, code: str, action: str, qty: int, price: float):
        """执行 Schwab 限价单 (带频率限制)"""
        symbol = code.split('.')[-1]
        
        # 频率限制
        if not self.schwab_limiter.can_request():
            self.log_message.emit(f"⏳ [美股-Schwab] 达到频率上限，正在等待令牌...")
            self.schwab_limiter.acquire()
            
        try:
            url = f"https://api.schwabapi.com/trader/v1/accounts/{self.schwab_account_hash}/orders"
            token = self.schwab_api._get_access_token()
            
            limit_price = round(price * 1.01, 2) if action.upper() == "BUY" else round(price * 0.99, 2)
            
            order_payload = {
                "orderType": "LIMIT",
                "session": "NORMAL",
                "duration": "DAY",
                "orderStrategyType": "SINGLE",
                "price": str(limit_price),
                "orderLegCollection": [{
                    "instruction": action.upper(),
                    "quantity": int(qty),
                    "instrument": {
                        "symbol": symbol,
                        "assetType": "EQUITY"
                    }
                }]
            }
            
            resp = requests.post(url, headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }, json=order_payload)
            
            if resp.status_code == 401:
                token = self.schwab_api._refresh_access_token()
                resp = requests.post(url, headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }, json=order_payload)

            if resp.status_code in (200, 201):
                self.log_message.emit(f"🚀 [美股-Schwab] 限价单提交成功: {symbol} {action} {qty} @ ${limit_price:.2f}")
            else:
                self.log_message.emit(f"❌ [美股-Schwab] 下单失败: {resp.status_code} {resp.text}")
        except Exception as e:
            self.log_message.emit(f"❌ [美股-Schwab] 下单异常: {e}")

    async def _close_all_positions_async(self):
        """异步一键清仓"""
        if self.venue == "IB":
            try:
                positions = self.ib.positions()
                count = 0
                for p in positions:
                    qty = int(p.position)
                    if qty == 0: continue
                    # 🛡️ [风控加固] 避免在一键清仓由于网络延迟被重复点击时，提交多个市价单导致形成反向多余头寸
                    if hasattr(self, 'check_pending_orders') and self.check_pending_orders(f"US.{p.contract.symbol}", 'SELL' if qty > 0 else 'BUY'):
                        self.log_message.emit(f"⏳ [美股-IB] {p.contract.symbol} 存在未完成平仓订单，跳过重复提交")
                        continue
                    self.ib.placeOrder(p.contract, MarketOrder("SELL" if qty > 0 else "BUY", abs(qty)))
                    count += 1
                self.log_message.emit(f"🔥 [美股-IB] 已提交 {count} 个清仓订单 (市价单)")
            except Exception as e:
                self.log_message.emit(f"❌ [美股-IB] 清仓失败: {e}")
        elif self.venue == "FUTU":
            try:
                # 重新拉取一次持仓以确保准确
                available, total, positions = await self.get_account_assets_async()
                count = 0
                for p in positions:
                    qty = int(p['qty'])
                    if qty == 0: continue
                    symbol = p['symbol']
                    code = f"US.{symbol}"
                    # 调用已平稳运行的 _execute_trade_async 执行卖出
                    await self._execute_trade_async(
                        code=code, 
                        action="SELL" if qty > 0 else "BUY", 
                        price=p['mkt_price'],
                        qty=abs(qty)
                    )
                    count += 1
                self.log_message.emit(f"🔥 [美股-Futu] 已提交 {count} 个清仓平仓单")
            except Exception as e:
                self.log_message.emit(f"❌ [美股-Futu] 一键清仓异常: {e}")
        elif self.venue == "SCHWAB":
            try:
                count = 0
                # 重新拉取一次持仓
                await self._update_schwab_cache_async()
                for p in self.schwab_positions_cache:
                    qty = int(p.get('longQuantity', 0) - p.get('shortQuantity', 0))
                    if qty == 0: continue
                    symbol = p['instrument']['symbol']
                    action = "SELL" if qty > 0 else "BUY"
                    self.log_message.emit(f"⚠️ [美股-Schwab] 暂不支持自动一键清仓，请手动处理 {symbol}")
                self.log_message.emit(f"🔥 [美股-Schwab] 一键清仓功能受限")
            except Exception as e:
                self.log_message.emit(f"❌ [美股-Schwab] 清仓异常: {e}")

    def _execute_trade(self, code, action, price):
        """同步包装下单"""
        asyncio.run_coroutine_threadsafe(self._execute_trade_async(code, action, price), self.loop)

    def execute_manual_order(self, code, action, price, qty):
        """主入口：执行手工委托订单"""
        if not code: return
        if not code.startswith("US."):
            code = f"US.{code.upper()}"
        else:
            code = code.upper()
            
        self.cmd_queue.put(('MANUAL_TRADE', {
            'code': code,
            'action': action.upper(),
            'price': float(price),
            'qty': int(qty)
        }))

    def close_all_positions(self):
        """主入口：向底层异步队列提交清仓指令"""
        self.cmd_queue.put(('CLOSE_ALL', None))

    def _handle_signal_sync(self, code: str, bsp, chan_30m, chan_5m=None, name: str = "",
                           pos_qty: int = 0, has_pending: bool = False, current_total_pos: int = 0,
                           is_valid_time: bool = True, window_sec: int = 3600):
        """线程池同步处理验证与绘图逻辑"""
        try:
            is_buy = bsp.is_buy
            if is_buy:
                if current_total_pos >= TRADING_CONFIG.get('max_total_positions', 10) and pos_qty <= 0:
                    self.log_message.emit(f"🚫 [美股] {code} 触发持位上限限制 (当前: {current_total_pos})")
                    return
                if pos_qty > 0:
                    self.log_message.emit(f"ℹ️ [美股] {code} 已有持仓 ({pos_qty})，跳过买入")
                    return
            else:
                if pos_qty <= 0:
                    self.log_message.emit(f"ℹ️ [美股] {code} 无持仓，跳过卖出信号")
                    return
            
            if has_pending:
                self.log_message.emit(f"⏳ [美股] {code} 存在未完成订单，跳过当前信号")
                return

            # 🛡️ [风控加固] 冷却期拦截 (对齐下单 20 分钟锁定)
            if hasattr(self, 'trade_cooldown') and code in self.trade_cooldown:
                if (time.time() - self.trade_cooldown[code]) < 1200:
                    self.log_message.emit(f"⏳ [美股] {code} 处于交易冷却期，跳过信号。")
                    return

            # --- 多周期共振过滤 (优化 A: 30M+5M 严苛嵌套) ---
            if chan_5m:
                bsp_5m_list = chan_5m.get_latest_bsp(number=0)
                us_now = self.get_us_now()
                if not bsp_5m_list:
                    logger.debug(f"[美股] {code} {bsp.type2str()} 30M 信号未获得 5M 共振确认 (5M无任何信号)，拦截")
                    return

                # 获取绝对最新的 5M 信号进行验证
                sorted_5m = sorted(bsp_5m_list, key=lambda x: str(x.klu.time), reverse=True)
                latest_b = sorted_5m[0]
                b_dt = datetime(latest_b.klu.time.year, latest_b.klu.time.month, latest_b.klu.time.day, 
                               latest_b.klu.time.hour, latest_b.klu.time.minute, latest_b.klu.time.second)
                
                # 严苛过滤：1. 方向一致; 2. 45分钟(交易时间)内
                from Common.TimeUtils import get_trading_minutes_diff
                max_age = TRADING_CONFIG.get('max_signal_age_minutes', 45)
                
                is_same_dir = (latest_b.is_buy == is_buy)
                trade_diff = get_trading_minutes_diff(b_dt, us_now, market='US')
                is_recent = trade_diff < max_age
                
                if not is_same_dir:
                    self.log_message.emit(f"⚠️ [美股] {code} {bsp.type2str()} 5M 确认失败: 5M 最新信号为反向 {latest_b.type2str()} @ {latest_b.klu.time}")
                    return
                if not is_recent:
                    self.log_message.emit(f"⚠️ [美股] {code} {bsp.type2str()} 5M 确认失败: 5M 最新信号 {latest_b.type2str()} 已过时(>{max_age}min, 实际交易时间:{trade_diff:.1f}min) @ {latest_b.klu.time}")
                    return
                    
                self.log_message.emit(f"💎 [美股] {code} {bsp.type2str()} 30M+5M 多周期共振确认成功 (最新5M信号: {latest_b.type2str()})")

            # --- 0. ML 优先审查 & 一票否决 (P1 加强) ---
            ml_res = {}
            ml_threshold = TRADING_CONFIG.get('ml_threshold', 0.70)
            
            if is_buy:
                ml_res = self.signal_validator.validate_signal(chan_30m, bsp, market_context=getattr(self, 'market_context', {}))
                prob = ml_res.get('prob', 0) if ml_res else 0
                if prob < ml_threshold:
                    self.log_message.emit(f"🤖 [美股] {code} {bsp.type2str()} ML 未达标 ({prob*100:.1f}% < {ml_threshold*100:.0f}%) -> 一票否决")
                    return
                self.log_message.emit(f"🤖 [美股] {code} {bsp.type2str()} ML 校验通过 ({prob*100:.1f}%)")
            else:
                # 优化 D 类似逻辑，同步应用到美股：卖点 0.4 阈值
                ml_res = self.signal_validator.validate_signal(chan_30m, bsp, market_context=getattr(self, 'market_context', {}))
                prob = ml_res.get('prob', 0) if ml_res else 0
                if prob < 0.60:
                    self.log_message.emit(f"🤖 [美股] {code} {bsp.type2str()} ML 概率过低 ({prob*100:.1f}% < 60%) -> 拦截假卖点")
                    return
                self.log_message.emit(f"🤖 [美股] {code} {bsp.type2str()} ML 卖点验证通过 ({prob*100:.1f}%)")

            # 1. 绘图 (为视觉 AI 准备素材) - 使用线程锁保护 matplotlib 全局状态
            chart_paths = []
            with self.chart_generation_lock:
                path_30m = os.path.abspath(os.path.join(self.charts_dir, f"{code.replace('.', '_')}_30m.png"))
                plot_30m = CPlotDriver(chan_30m, plot_config=CHART_CONFIG, plot_para=CHART_PARA)
                plot_30m.figure.savefig(path_30m, bbox_inches='tight', dpi=120)
                plt.close(plot_30m.figure)
                chart_paths.append(path_30m)

                if chan_5m:
                    path_5m = os.path.abspath(os.path.join(self.charts_dir, f"{code.replace('.', '_')}_5m.png"))
                    plot_5m = CPlotDriver(chan_5m, plot_config=CHART_CONFIG, plot_para=CHART_PARA)
                    plot_5m.figure.savefig(path_5m, bbox_inches='tight', dpi=120)
                    plt.close(plot_5m.figure)
                    chart_paths.append(path_5m)

            sig_key = f"{code}_{str(bsp.klu.time)}_{bsp.type2str()}"
            
            # 2. 视觉 AI 验证 (优先执行)
            visual_start = time.perf_counter()
            visual_res = self.visual_judge.evaluate(chart_paths, bsp.type2str())
            visual_time = time.perf_counter() - visual_start
            
            if not visual_res:
                self.log_message.emit(f"⚠️ [美股] {code} 视觉评分返回为空，清除已通知记录以等待重试")
                if sig_key in self.notified_signals:
                    del self.notified_signals[sig_key]
                    self._save_notified_signals()
                return
            
            score = visual_res.get('score', 0)
            reason = visual_res.get('analysis', '无详细分析')
            
            # 3. 视觉验证 (已经过 ML 达标过滤)
            if score < 70:
                is_api_error = '失败' in reason or visual_res.get('identified_signal') == 'ERROR' or score == 0 and '无详细分析' in reason
                if is_api_error:
                    self.log_message.emit(f"⚠️ [美股] {code} {bsp.type2str()} 视觉API调用失败 [{reason}]，清除记录等待重试")
                    if sig_key in self.notified_signals:
                        del self.notified_signals[sig_key]
                        self._save_notified_signals()
                else:
                    self.log_message.emit(f"🤖 [美股] {code} {bsp.type2str()} 拦截 [ML:{ml_res.get('prob', 0):.2f}, Visual:{score}]: {reason}")
                return
            else:
                self.log_message.emit(f"✅ [美股] {code} {bsp.type2str()} 准入 [ML:{ml_res.get('prob', 0):.2f}, Visual:{score}]: 三项阈值均达标 (包含缠论买卖点)")


            if self.discord_bot and score >= self.min_visual_score:
                msg = f"🗽 **美股自动化预警**\n股票: {code}\n信号: {bsp.type2str()}\n评分: **{score}分**\nML概率: {ml_res.get('prob',0)*100:.1f}%"
                if self.discord_bot.loop and self.discord_bot.loop.is_running():
                    asyncio.run_coroutine_threadsafe(self.discord_bot.send_notification(msg, path_30m), self.discord_bot.loop)

            if score >= self.min_visual_score:
                # 🟢 [风控加固] 对齐港股，已有持仓的股票不重复买入
                if bsp.is_buy and pos_qty > 0:
                    self.log_message.emit(f"🛡️ [美股] {code} 触发现点买单信号，但账户已有持仓（{pos_qty} 股），跳过重复买入。")
                    return

                if not is_valid_time:
                    self.log_message.emit(f"⏮️ [美股] {code} {bsp.type2str()} 信号过期(>{window_sec/3600:.1f}h)，跳过下单")
                elif self.dry_run: 
                    self.log_message.emit(f"📝 [美股-模拟] {code} {score}分满足，跳过执行")
                elif not self.is_trading_time():
                    self.log_message.emit(f"⏳ [美股] {code} {bsp.type2str()} 信号满足，但当前非交易时间，仅通告跳过下单。")
                else:
                    # 计算 ATR 辅助动态头寸
                    atr_value = 1.0
                    try:
                        kl_list = list(chan_30m[0].klu_iter())
                        if len(kl_list) >= 14:
                            tr_list = []
                            for i in range(1, len(kl_list)):
                                h, l, pc = kl_list[i].high, kl_list[i].low, kl_list[i-1].close
                                tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
                            atr_value = sum(tr_list[-14:]) / 14
                            atr_value = max(atr_value, bsp.klu.close * 0.015)  # 🛡️ 注入 1.5% 容错防守保底
                    except:
                        pass

                    # 🟢 [风控加固] 队列去重：若指令已在队列中，不重复提交
                    if code in self._pending_execute_codes:
                        self.log_message.emit(f"⏳ [美股] {code} 的交易指令已在等待队列中，跳过。")
                        return
                    self._pending_execute_codes.add(code)

                    self.cmd_queue.put(('EXECUTE_TRADE', {
                        'code': code, 
                        'action': "BUY" if is_buy else "SELL", 
                        'price': bsp.klu.close,
                        'name': name,
                        'signal_type': bsp.type2str(),
                        'ml_prob': ml_res.get('prob', 0),
                        'visual_score': score,
                        'atr_value': atr_value
                    }))
                    self.log_message.emit(f"📩 [美股] {code} 下单指令已发送主线程")
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股] 信号处理异常: {e}")
            print(traceback.format_exc())

    async def _initialize_single_tracker_async(self, p: dict):
        """单只股票持仓风控自愈初始化"""
        try:
            from Chan import CChan, CChanConfig
            from Common.CEnum import DATA_SRC, KL_TYPE
            
            code = f"US.{p['symbol']}" # 构造成标准代码
            if code in self.position_trackers: return
            
            # 计算最新价格 (如果没给 marketPrice，用 mkt_value / qty 估算)
            current = p.get('mkt_price') or (p['mkt_value'] / p['qty'] if p['qty'] != 0 else 0)
            if current <= 0: return
            
            # 从本地库缓存快速提取 30m
            now_t = datetime.now()
            # ⚓ 同样锚定到上一个 30M 周期对齐
            end_time = now_t.replace(minute=(now_t.minute // 30) * 30, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
            start_time = (now_t - timedelta(days=60)).strftime("%Y-%m-%d")
            
            local_chan_config = CHAN_CONFIG.copy()
            # 💡 [数据源自适应] 用户明确 Schwab 具备付费行情，IB / Futu 无订阅。
            # 强制所有历史 K线与 ATR 回测均从 SCHWAB 拉取，绕开订阅黑洞。
            try:
                from Common.CEnum import DATA_SRC
                d_src = DATA_SRC.SCHWAB
            except:
                d_src = DATA_SRC.SCHWAB

            try:
                chan = CChan(
                    code=code,
                    begin_time=start_time,
                    end_time=end_time,
                    data_src=d_src, 
                    lv_list=[KL_TYPE.K_30M],
                    config=CChanConfig(local_chan_config),
                    autype=1 # 默认前复权
                )
            except Exception as e:
                if self.venue == "IB":
                    # 💡 [补救逻辑] 如果 CChan 内部由于 API 异常导致报错，直接降级 Schwab
                    self.log_message.emit(f"📡 [IB-ATR补救] {code} 行情加载异常 ({e})，尝试切换 Schwab 源...")
                    chan = CChan(
                        code=code,
                        begin_time=start_time,
                        end_time=end_time,
                        data_src=DATA_SRC.SCHWAB, 
                        lv_list=[KL_TYPE.K_30M],
                        config=CChanConfig(local_chan_config),
                        autype=1
                    )
                else: raise
            
            # --- 💡 [补救逻辑] 如果 IB 未报错，但由于延迟或订阅原因拉取了空数据，追加降级 Schwab ---
            if not chan[0] or len(list(chan[0].klu_iter())) == 0:
                if self.venue == "IB":
                    self.log_message.emit(f"📡 [IB-ATR补救] {code} 行情数据为空，尝试切换 Schwab 源...")
                    chan = CChan(
                        code=code,
                        begin_time=start_time,
                        end_time=end_time,
                        data_src=DATA_SRC.SCHWAB, 
                        lv_list=[KL_TYPE.K_30M],
                        config=CChanConfig(local_chan_config),
                        autype=1
                    )
            
            if chan[0]:
                kl_list = list(chan[0].klu_iter())
                if len(kl_list) == 0:
                    self.log_message.emit(f"⚠️ {code} 历史 K线数据为空，无法初始化 ATR")
                    return
                    
                close_prices = [k.close for k in kl_list]
                high_prices = [k.high for k in kl_list]
                low_prices = [k.low for k in kl_list]
                
                tr_list = []
                for i in range(1, len(close_prices)):
                    hl = high_prices[i] - low_prices[i]
                    hc = abs(high_prices[i] - close_prices[i-1])
                    lc = abs(low_prices[i] - close_prices[i-1])
                    tr_list.append(max(hl, hc, lc))
            # 安全均值（加入保底：防止极端平盘或买卖点差造成的秒抛）
                atr_val = sum(tr_list[-10:]) / 10 if len(tr_list) >= 10 else (current * 0.02)
                atr_val = max(atr_val, current * 0.015)  # 🛡️ 强制 1.5% 现价的安全垫底限

                signal_type = '未知'
                try:
                    with sqlite3.connect(self.db.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            SELECT signal_type
                            FROM live_trades
                            WHERE code = ? AND market = 'US' AND status = 'open'
                            ORDER BY entry_time DESC
                            LIMIT 1
                            """,
                            (code,)
                        )
                        row = cursor.fetchone()
                        if row and row[0]:
                            signal_type = row[0]
                except Exception as db_ex:
                    self.log_message.emit(f"⚠️ {code} 恢复 signal_type 失败，使用默认风控参数: {db_ex}")
                
                self.position_trackers[code] = {
                    'entry_price': p['avg_cost'],
                    'highest_price': max(current, p['avg_cost']),
                    'atr': atr_val,
                    'trail_active': False,
                    'signal_type': signal_type
                }
                self.log_message.emit(f"✅ {code} 风控载入: 成本=${p['avg_cost']:.2f}, ATR=${atr_val:.3f}, 信号类型={signal_type}")
        except Exception as ex:
             self.log_message.emit(f"⚠️ 初始化 {code} ATR失败: {ex}")

    async def _initialize_position_trackers(self):
        """为现有持仓初始化追踪止损器 (方案丙)"""
        try:
            self.log_message.emit("🛡️ 正在为当前美股持仓拉取快照并初始化风险监控...")
            await asyncio.sleep(3)  # ⏳ 给 3 秒缓冲时间，让 IB 充分同步底层 positions 缓存
            available, total, positions = await self.get_account_assets_async()
            
            # --- 💡 [仓位校准] 遍历当前持仓，挂载/更新止损监控 ---
            if positions:
                # 💡 [性能优化] 并发执行 K 线拉取与 ATR 计算，克服串行加载带来的数分钟卡顿
                tasks = [self._initialize_single_tracker_async(p) for p in positions]
                await asyncio.gather(*tasks)
            
            # --- 💡 [补偿买入自愈] 清除今天已发出「买入」通知、但实际上未进入持仓的标的，让其下轮扫描重新触发 ---
            # ⚠️ sig_key 格式: "US.MU_2026/03/19_1"，需提取股票代码部分才能与 position_trackers 对比
            now_et_str = self.get_us_now().strftime("%Y-%m-%d")
            held_codes = set(self.position_trackers.keys())  # e.g. {"US.MU", "US.AAPL"}
            cleanup_keys = []
            for sig_key, sig_time in list(self.notified_signals.items()):
                if not sig_time.startswith(now_et_str):
                    continue
                # 从 sig_key 提取股票代码: "US.MU_2026/03/19_1" → "US.MU"
                parts = sig_key.split('_')
                if len(parts) < 3:
                    continue  # 格式异常，跳过
                code_from_key = parts[0]  # "US.MU"
                signal_type = parts[-1]   # "1", "2s", "2", etc.
                # 仅对买型信号（非卖点）做漏单自愈；且标的确实不在当前持仓中
                is_buy_signal = not signal_type.endswith('S') and not signal_type.endswith('s')
                if is_buy_signal and code_from_key not in held_codes:
                    cleanup_keys.append(sig_key)

            if cleanup_keys:
                self.log_message.emit(f"♻️ [风控自愈] 发现 {len(cleanup_keys)} 只今天已发出买入通知但尚未成交的标的 ({', '.join(cleanup_keys)})，已从去重池释放，下轮扫描将重新追踪！")
                for k in cleanup_keys:
                    del self.notified_signals[k]
                self._save_notified_signals()

            # 📊 [增强逻辑] 初始化完毕后，自动向面板汇总报告全部监控清单
            if self.position_trackers:
                summary_lines = ["🛡️ **[美股持仓风控监控中]**"]
                for code, tr in self.position_trackers.items():
                    summary_lines.append(f"   • {code}: 成本价 ${tr['entry_price']:.2f}, 当前最高价 ${tr['highest_price']:.2f}, ATR ${tr['atr']:.3f}/股")
                self.log_message.emit("\n".join(summary_lines))
            else:
                self.log_message.emit("🛡️ 当前账户无活跃美股持仓，ATR 止损监控模块暂歇。")
                
            # 自动查询资金以刷新 GUI
            self.cmd_queue.put(('QUERY_FUNDS', None))
            self._trackers_initialized = True
                
        except Exception as e:
            self.log_message.emit(f"🚨 [美股] ATR/持仓监控初始化引发致命异常: {e}")
            import traceback
            print(traceback.format_exc())
        finally:
            self._trackers_initializing = False

    async def _check_trailing_stops(self):
        """活性持仓止损检查算法 (方案丙) - 异步高频安全哨兵"""
        try:
            from datetime import datetime as _dt
            # 🛡️ [每日重置] 开启新的一天时，清空卖出锁定名单
            curr_date = _dt.now().strftime("%Y-%m-%d")
            if curr_date != self._last_reset_date:
                self.log_message.emit(f"📅 [美股-新交易日] 自动清空昨日平仓锁定清单 (曾锁定: {len(self.sold_today)} 只)")
                self.sold_today.clear()
                self._last_reset_date = curr_date

            available, total, positions = await self.get_account_assets_async()
            current_held_codes = {f"US.{p['symbol']}": p for p in positions}
            
            # 🚀 [Phase 12] 统一使用 Schwab 作为美股价格“事实来源”，解决 IB 延迟问题
            schwab_prices = {}
            if self.schwab_api and current_held_codes:
                try:
                    loop = asyncio.get_running_loop()
                    schwab_prices = await loop.run_in_executor(self.executor, self.schwab_api.get_realtime_quotes, list(current_held_codes.keys()))
                except Exception as e_quote:
                    self.log_message.emit(f"⚠️ [美股-风控] 获取 Schwab 实时报价失败: {e_quote}")
            
            # --- 自愈补救机制：为缺失的持仓 cold start 加载 ATR ---
            for code, p in current_held_codes.items():
                if code not in self.position_trackers:
                    # 🛡️ [锁定校验] 若今日已成交平仓，不再重新初始化追踪器
                    if code in self.sold_today: continue
                    # 🛡️ [防卖出循环] 如果该股票最近 10 分钟内有过卖出记录，暂不建立追踪器，防止幽灵持仓复活
                    if code in self.trade_cooldown:
                        if (time.time() - self.trade_cooldown[code]) < 600: # 10分钟保护
                             continue
                    asyncio.create_task(self._initialize_single_tracker_async(p))
            
            for attempt, code in enumerate(list(self.position_trackers.keys()), 1):
                # 1. 检查是否存在持仓
                if code not in current_held_codes:
                    # 🛡️ [安全性检查] 给持仓清空留出 3.5 分钟同步冗余，防止网络颠簸误删追踪器
                    if code in self.trade_cooldown and (time.time() - self.trade_cooldown[code]) < 210:
                        continue
                        
                    self.log_message.emit(f"🔄 {code} 已无持仓，停止移动止损追踪")
                    del self.position_trackers[code]
                    continue
                
                p = current_held_codes[code]
                qty = abs(p['qty'])
                
                # 💡 优先使用 Schwab 价格，兜底使用券商汇报价格
                current_price = schwab_prices.get(code)
                if not current_price:
                    current_price = p.get('mkt_price') or (p['mkt_value'] / p['qty'] if p['qty'] != 0 else 0)
                
                # 2. 获取追踪器
                tracker = self.position_trackers[code]
                
                # 3. 更新最高价
                if current_price > tracker['highest_price']:
                    tracker['highest_price'] = current_price
                    source_tag = " (Schwab)" if code in schwab_prices else ""
                    self.log_message.emit(f"📈 {code} 创美股持仓新高{source_tag}: ${current_price:.2f}")
                
                # 4. 风控条件对齐
                entry_price = tracker.get('entry_price', current_price)
                highest = tracker['highest_price']
                atr = tracker['atr']
                
                # 🛡️ [分档式自适应止损 Phase 8]
                atr_init = TRADING_CONFIG.get('atr_stop_init', 1.2)
                bsp_type_str = tracker.get('signal_type', '未知')
                if "1买" in bsp_type_str:
                    atr_init = 1.5
                elif "2买" in bsp_type_str or "3买" in bsp_type_str:
                    atr_init = 1.2
                    
                # 🚀 [Phase 11] 使用针对美股优化的 3.0 ATR 移动止损
                atr_trail = self.atr_stop_trail
                atr_profit = TRADING_CONFIG.get('atr_profit_threshold', 1.5)
                
                # 触发状态：开启移动止损
                if not tracker.get('trail_active', False):
                    if (current_price - entry_price) >= (atr * atr_profit):
                        tracker['trail_active'] = True
                        self.log_message.emit(f"🔓 {code} 已达获利门槛(+{atr_profit}*ATR)，切换为移动止损模式")
                
                if tracker.get('trail_active', False):
                    stop_price = highest - (atr * atr_trail)
                    stop_type = "ATR移动止盈"
                else:
                    stop_price = entry_price - (atr * atr_init)
                    stop_type = "ATR初始止损"
                
                self.log_message.emit(f"🛡️ [ATR监测] {code}: 现价 ${current_price:.2f}, 止损位 ${stop_price:.2f} ({stop_type}) [最高价 ${highest:.2f}, ATR ${atr:.4f}]")
                
                # 5. 触发则立刻下平仓单
                if current_price < stop_price:
                    # 🛡️ [单日平仓锁] 根本方案：今日已卖，绝不再卖
                    if code in self.sold_today:
                        if attempt % 5 == 0:
                            self.log_message.emit(f"🛡️ [单日平仓锁] {code} 触发止损，但由于今日已执行过平仓，拦截重复下单")
                        continue

                    # 🛡️ [风控加固 Phase 12] 严防死守：止损触发必须验证 20 分钟冷却期
                    if code in self.trade_cooldown:
                        elapsed = time.time() - self.trade_cooldown[code]
                        if elapsed < 1200:
                            if attempt % 5 == 0: # 减少重复日志
                                self.log_message.emit(f"⏳ [美股-风控] {code} 触发止损但我方处于 20min 交易冷却期内({elapsed:.0f}s)，拦截重复触发")
                            continue

                    self.log_message.emit(f"🚨 {code} 触发{stop_type}! 最高价=${highest:.2f}, 现价=${current_price:.2f}, 止损位=${stop_price:.2f}")
                    # 🟢 [风控加固] 队列去重
                    if code in self._pending_execute_codes:
                        continue
                    self._pending_execute_codes.add(code)

                    self.cmd_queue.put(('EXECUTE_TRADE', {
                        'code': code, 
                        'action': 'SELL', 
                        'price': current_price,
                        'exit_reason': stop_type
                    }))
                    del self.position_trackers[code]
                    
                    now = _dt.now()
                    self.structure_barrier[code] = {
                        'lock_time_ts': CTime(now.year, now.month, now.day, now.hour, now.minute).ts
                    }
                    self.log_message.emit(f"🛡️ [美股-风控] {code} 止损出局，锁入结构防护舱。")
        except Exception as e:
             logger.error(f"浮动止损检查异常: {e}")

    async def _get_futu_assets_async(self) -> Tuple[float, float, list]:
        """通过 Futu API 获取美股账户资产及持仓 (支持模拟与真实自适应)"""
        try:
            # 0. [核心修复] 强制刷新模拟盘账户列表同步 (解决模拟盘成交后资金不更新的 OpenD 缓存问题)
            if self.trd_env == TrdEnv.SIMULATE:
                self.trd_ctx.get_acc_list()

            # 1. 自动探查账户环境
            acc_id = 0
            actual_env = 'REAL'
            ret_list, account_list = self.trd_ctx.get_acc_list()
            
            if ret_list == RET_OK and not account_list.empty:
                # 📊 [修正选号] 过滤出与 self.trd_env 相符的账户 (SIMULATE / REAL)
                target_env_str = 'SIMULATE' if self.trd_env == TrdEnv.SIMULATE else 'REAL'
                matched = account_list[account_list['trd_env'] == target_env_str]
                
                # 🛡️ [风控加固] 避免选错到港股/A股账户，强制增加美股卡号或账户类型识别
                sub_matched = matched[(matched.get('sim_acc_type') == 'STOCK') | (matched.get('sim_acc_type') == 2)]
                if sub_matched.empty and 'card_num' in account_list.columns:
                    sub_matched = matched[account_list['card_num'].astype(str).str.contains('美国|US', case=False, na=False)]
                
                if not sub_matched.empty:
                    row = sub_matched.iloc[0]
                elif not matched.empty:
                    row = matched.iloc[0]
                else:
                    row = account_list.iloc[0]
                
                acc_id = row['acc_id']
                actual_env = target_env_str

            # 2. 查询账户资金
            refresh = (self.trd_env == TrdEnv.SIMULATE)
            ret, data = self.trd_ctx.accinfo_query(acc_id=acc_id, trd_env=actual_env, refresh_cache=refresh)
            available, total = 0.0, 0.0
            if ret == RET_OK and not data.empty:
                row = data.iloc[0]
                # [详细调试] 打印所有资金组件
                log_msg = (f"💹 [美股-Futu-资金详情] ID: {acc_id}\n"
                           f"   • 现金(cash): {row.get('cash', 'N/A')}\n"
                           f"   • 总资产(total_assets): {row.get('total_assets', 'N/A')}\n"
                           f"   • 购买力(power): {row.get('power', 'N/A')}\n"
                           f"   • 证券市值(market_val): {row.get('market_val', 'N/A')}")
                self.log_message.emit(log_msg)
                
                available = float(data.iloc[0]['cash'])
                total = float(data.iloc[0].get('total_assets', data.iloc[0].get('power', 0.0)))
            else:
                self.log_message.emit(f"⚠️ [美股-Futu] 资金查询反馈 [{ret}]: {data}")
            
            # 3. 查询持仓
            positions = []
            ret_pos, pos_data = self.trd_ctx.position_list_query(acc_id=acc_id, trd_env=actual_env, refresh_cache=refresh)
            if ret_pos == RET_OK and not pos_data.empty:
                for _, row in pos_data.iterrows():
                    qty = int(row['qty'])
                    can_sell = int(row.get('can_sell_qty', qty))
                    today_qty = int(row.get('today_qty', 0))
                    if qty == 0 and can_sell == 0: continue
                    
                    symbol = row['code'].split('.')[-1]
                    self.log_message.emit(f"📦 [美股-Futu-持仓明细] {symbol}: 总量={qty}, 可卖={can_sell}, 今日买={today_qty}")
                    
                    positions.append({
                        'symbol': symbol,
                        'qty': qty,
                        'can_sell_qty': can_sell,
                        'mkt_value': float(row['market_val']),
                        'avg_cost': float(row['cost_price']),
                        'mkt_price': float(row['nominal_price'])
                    })
            return available, total, positions
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股-Futu] 资金持仓查询失败: {e}")
        return 0.0, 0.0, []

    async def _execute_futu_order_async(self, code: str, action: str, qty: int, price: float):
        """富途美股下单接口"""
        try:
            side = TrdSide.BUY if action == "BUY" else TrdSide.SELL
            limit_price = round(price * 1.01, 2) if action == "BUY" else round(price * 0.99, 2)
            
            # 确保代码带有 US. 前缀
            if not code.startswith("US."):
                code = f"US.{code.split('.')[-1]}"
                
            acc_id = 0
            ret_list, account_list = self.trd_ctx.get_acc_list()
            if ret_list == RET_OK and not account_list.empty:
                from futu import TrdEnv
                target_env_str = 'SIMULATE' if self.trd_env == TrdEnv.SIMULATE else 'REAL'
                matched = account_list[account_list['trd_env'] == target_env_str]

                # 🛡️ [风控加固] 强制锁定美股专属子账户页：避免穿隧到港股或 A股 导致持仓为空
                sub_matched = matched[(matched.get('sim_acc_type') == 'STOCK') | (matched.get('sim_acc_type') == 2)]
                if sub_matched.empty and 'card_num' in account_list.columns:
                    sub_matched = matched[account_list['card_num'].astype(str).str.contains('美国|US', case=False, na=False)]
                
                acc_id = sub_matched.iloc[0]['acc_id'] if not sub_matched.empty else (matched.iloc[0]['acc_id'] if not matched.empty else account_list.iloc[0]['acc_id'])

            # 🛡️ [风控加固] 极速防爆：强制将 Futu 下单间隔拉开到 2.2 秒，对齐 15次/30秒 官方红线
            if hasattr(self, '_last_futu_order_time'):
                 import time
                 elapsed = time.time() - self._last_futu_order_time
                 if elapsed < 2.2:
                      await asyncio.sleep(2.2 - elapsed)
            self._last_futu_order_time = time.time()

            ret, data = self.trd_ctx.place_order(
                price=limit_price,
                qty=qty,
                code=code,
                trd_side=side,
                order_type=OrderType.NORMAL,
                trd_env=self.trd_env,
                acc_id=acc_id  # 🚨 传递底层账户ID
            )
            if ret == RET_OK:
                order_id = data.iloc[0]['order_id']
                self.log_message.emit(f"🚀 [美股-Futu] 限价单提交成功: {code} {action} {qty} @ ${limit_price:.2f} (ID: {order_id})")

                # 启动订单跟踪
                asyncio.create_task(
                    self._track_order_status_async(order_id, code, action, qty, limit_price, "FUTU")
                )
            else:
                self.log_message.emit(f"❌ [美股-Futu] 下单失败: {data}")
        except Exception as e:
             self.log_message.emit(f"❌ [美股-Futu] 下单异常: {e}")
