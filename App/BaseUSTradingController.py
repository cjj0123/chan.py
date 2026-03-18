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
import requests

from PyQt6.QtCore import QObject, pyqtSignal

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TRADING_CONFIG, CHAN_CONFIG, CHART_CONFIG, CHART_PARA
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.SQLiteAPI import SQLiteAPI, download_and_save_all_stocks_multi_timeframe, download_and_save_all_stocks_async
from Trade.db_util import CChanDB
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
from visual_judge import VisualJudge
from DiscordBot import DiscordBot
from Trade.db_util import CChanDB


# --- 配置导入 ---
# Schwab API 与 频率限制器
from DataAPI.SchwabAPI import CSchwabAPI
from Common.SchwabRateLimiter import get_schwab_limiter

# 导入 Futu US 交易
from futu import OpenUSTradeContext, TrdMarket, TrdSide, OrderType, RET_OK, TrdEnv

logger = logging.getLogger(__name__)

class BaseUSTradingController(QObject):
    """
    美股交易控制器 (IB)
    """
    log_message = pyqtSignal(str)
    scan_finished = pyqtSignal(int, int, int, int)
    funds_updated = pyqtSignal(float, float, list) # (available, total, positions)
    
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
        
        self.ib = None
        self.host = os.getenv("IB_HOST", "127.0.0.1")
        self.port = int(os.getenv("IB_PORT", "4002"))
        self.client_id = 10 # 彻底隔离：交易使用 10-20，扫描使用 50-450
        
        self.charts_dir = f"charts_us_{self.venue.lower()}"
        os.makedirs(self.charts_dir, exist_ok=True)
        # 实例化工具组件
        self.signal_validator = SignalValidator()
        self.visual_judge = VisualJudge()
        self.db = CChanDB()
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
        self.retry_orders = {}  # 🚨 [补漏专用] 下单异常重试池，防崩溃漏单
        self._trd_ctx = None
        self._last_close_date = None

    @property
    def trd_ctx(self):
        """延迟初始化 Futu 交易上下文，确保在使用线程上创建"""
        if self._trd_ctx is None:
            self._trd_ctx = OpenUSTradeContext(host='127.0.0.1', port=11111)
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

    def on_ib_error(self, reqId, errorCode, errorString, contract):
        """IB 错误事件回调"""
        # 常见重连相关错误代码:
        # 1100: Connectivity between IB and TWS has been lost.
        # 1101: Connectivity between IB and TWS has been restored- data maintained.
        # 1102: Connectivity between IB and TWS has been restored- data lost.
        if errorCode in (1100, 1101, 1102):
            icon = "📡" if errorCode >= 1101 else "🚨"
            self.log_message.emit(f"{icon} [IB-网络状态] {errorCode}: {errorString}")
        elif errorCode == 2100: # New connection established
             self.log_message.emit(f"✅ [IB-系统] {errorString}")

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
        self._poll_task = asyncio.create_task(self._poll_gui_commands())
        self.ib = IB()
        self.ib.errorEvent += self.on_ib_error
        
        # 避免启动时立即触发全量扫描，初始化为当前 30M Bar 时间，等待下一个周期再触发
        now_et = self.get_us_now()
        last_scan_bar = now_et.replace(minute=(now_et.minute // 30) * 30, second=0, microsecond=0)
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
                            self.ib.reqAccountUpdates(True)
                            # 异步进行仓位风控初始化 (方案丙)
                            asyncio.create_task(self._initialize_position_trackers())
                        except asyncio.TimeoutError:
                            self.log_message.emit("⚠️ [美股] IB 连接超时 (12s)")
                        except Exception as e:
                            import traceback
                            last_exc = traceback.format_exc().splitlines()[-1]
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

                # (指令处理已迁移至 _poll_gui_commands 后台协程)

                # 3. 驱动的心跳
                await asyncio.sleep(0.5)

                # 3.5 活性持仓止损监测 (方案丙)
                if not hasattr(self, '_last_stop_check_time'):
                    self._last_stop_check_time = time.time()
                elif time.time() - self._last_stop_check_time >= 60: # 60秒一检
                    await self._check_trailing_stops()
                    self._last_stop_check_time = time.time()
                    
                    # --- 🚨 [自动促成机制] 对暂存在重试池里的故障单进行全自动二次补救 ---
                    if getattr(self, 'retry_orders', {}):
                        for code, data in list(self.retry_orders.items()):
                            try:
                                self.log_message.emit(f"🔄 [下单自愈] 正在重推之前异常的订单: {code}")
                                await self._execute_trade_async(**data)
                                del self.retry_orders[code]
                            except Exception as er:
                                self.log_message.emit(f"⚠️ [下单自愈] {code} 依旧失败: {er}")

                if self._is_paused:
                    continue

                # 4. 周期扫描逻辑
                now_et = self.get_us_now()
                if now_et.minute != last_heartbeat_min:
                    # 心跳逻辑 (仅更新变量，不再打印日志以减少刷屏)
                    last_heartbeat_min = now_et.minute

                if not self.is_trading_time():
                    await asyncio.sleep(1.0)
                    continue

                # 扫描触发
                current_bar_et = now_et.replace(minute=(now_et.minute // 30) * 30, second=0, microsecond=0)
                should_scan = False
                
                if current_bar_et > last_scan_bar:
                    if now_et.minute % 30 >= 1:
                        should_scan = True
                        self._current_bar_scanned = True # 标记已扫
                elif not getattr(self, '_current_bar_scanned', False):
                    # 💡 补偿刚启动时当前 30M 周期还未跑过扫描的情况(参照港股：前8分钟内允许)
                    if 1 <= (now_et.minute % 30) <= 8:
                        self.log_message.emit("⚡ [美股] 触发补全启动窗口期扫描...")
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
                except Exception as ex:
                    self.log_message.emit(f"⚠️ [指令下单异常] {c} 执行失败: {ex}，已安全载入重试队列。")
                    if not hasattr(self, 'retry_orders'): self.retry_orders = {}
                    self.retry_orders[c] = data
        except asyncio.TimeoutError:
            self.log_message.emit(f"⚠️ [指令] 指令 {cmd_type} 执行超时")

    async def _perform_strategy_scan_async(self, is_force_scan: bool = False):
        """执行异步策略扫描"""
        self.log_message.emit(f"🔍 [美股] 正在获取分组 '{self.watchlist_group}' 代码...")
        us_watchlist = {} # code -> name
        
        try:
            from futu import OpenQuoteContext, RET_OK
            
            def get_futu_watchlist():
                """支持逗号分隔的多分组合并 (如 '美股,热点_实盘')"""
                all_dict = {}
                try:
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
                except:
                    pass
                return all_dict

            # 1. Fetch from Futu via executor (Sync -> Async)
            loop = asyncio.get_running_loop()
            futu_watchlist = await loop.run_in_executor(self.executor, get_futu_watchlist)
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

            # 取出所有的股票代码列表
            us_codes = sorted(list(us_watchlist.keys()))
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

            # 2. 批量极速同步 (Phase 5: Sync-then-Scan) - 移除，改为在线拉取
            # self.log_message.emit(f"🔄 [美股] 执行批量同步 (30m & 5m)...")
            # sync_start = time.perf_counter()
            # try:
            #     # 使用已经实现的 Phase 3 异步下载器
            #     await download_and_save_all_stocks_async(
            #         us_codes, days=60, timeframes=['30m', '5m'],
            #         log_callback=self.log_message.emit,
            #         ib_client=self.ib
            #     )
            #     sync_time = time.perf_counter() - sync_start
            #     self.log_message.emit(f"✅ [美股] 批量同步完成 (耗时: {sync_time:.2f}s)")
            # except Exception as e:
            #     self.log_message.emit(f"⚠️ [美股] 批量同步异常: {e}")

            # 3. 串行分析 (依照港股逻辑，稳定可靠)
            scan_start = time.perf_counter()
            self.log_message.emit(f"🚀 [美股] 开始策略扫描 (共 {len(us_codes)} 只)...")
            
            tasks = []
            for i, code in enumerate(us_codes, 1):
                if not self._is_running: break
                try:
                    symbol = code.split(".")[1] if "." in code else code
                    contract = symbol_to_contract.get(symbol)
                    name = us_watchlist.get(code, "")
                    tasks.append(self._analyze_stock_async(code, name=name, index=i, total=len(us_codes), contract=contract, is_force_scan=is_force_scan))
                except Exception as e:
                    self.log_message.emit(f"❌ [美股] 构建 {code} 任务报错: {e}")
            
            if tasks:
                await asyncio.gather(*tasks)
            
            total_scan_time = time.perf_counter() - scan_start
            self.log_message.emit(f"✅ [美股] 策略扫描完成, 总耗时: {total_scan_time:.2f}s")
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 扫描过程异常: {e}")

    async def _analyze_stock_async(self, code: str, name: str = "", index: int = 0, total: int = 0, contract=None, is_force_scan: bool = False):
        """异步分析单只股票"""
        if contract is None: return
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
            local_chan_config = CHAN_CONFIG.copy()
            # 💡 trigger_step = True 会禁用 CChan 初始化时加载数据，导致 0 根 K线。需移除！
            
            loop = asyncio.get_running_loop()
            def create_chan_30m():
                try:
                    from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE
                    from Chan import CChan, CChanConfig
                    from config import CHAN_CONFIG
                    return CChan(
                        code=code, 
                        begin_time=start_30m_str, 
                        end_time=end_time_str, 
                        data_src=DATA_SRC.SCHWAB, 
                        lv_list=[KL_TYPE.K_30M], 
                        config=CChanConfig(local_chan_config), 
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

            bsp_list = chan_30m.get_latest_bsp(number=0)
            if bsp_list:
                bsp_list = sorted(bsp_list, key=lambda x: str(x.klu.time), reverse=True)[:1]
        except Exception as e_online:
             self.log_message.emit(f"❌ [美股] 在线拉取 {code} 异常: {e_online}")
             return
        
        us_now = self.get_us_now()
        in_market = self.is_trading_time()
        window_sec = 3600 if in_market else 86400
        
        for bsp in bsp_list:
            bsp_dt = datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day, 
                              bsp.klu.time.hour, bsp.klu.time.minute, bsp.klu.time.second)
            is_valid_time = is_force_scan or (us_now - bsp_dt).total_seconds() <= window_sec
            if True: # 保持缩进，下沉时间过滤至下单前以呈现完整日志
                sig_key = f"{code}_{str(bsp.klu.time)}_{bsp.type2str()}"
                if sig_key in self.notified_signals: continue
                
                self.notified_signals[sig_key] = us_now.strftime("%Y-%m-%d %H:%M:%S")
                self._save_notified_signals()  # 立即持久化，防止崩溃后丢失
                self.log_message.emit(f"🎯 [美股] {code} 发现信号: {bsp.type2str()} @ {bsp.klu.time}")
                
                chan_5m = None
                try:
                    # 在线获取 5M 数据
                    start_time_5m = end_time - timedelta(days=7)
                    start_5m_str = start_time_5m.strftime("%Y-%m-%d")
                    
                    def create_chan_5m():
                        try:
                            return CChan(
                                code=code, 
                                begin_time=start_5m_str, 
                                end_time=end_time_str, 
                                data_src=DATA_SRC.SCHWAB, 
                                lv_list=[KL_TYPE.K_5M], 
                                config=CChanConfig(local_chan_config), 
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

                pos_qty = self.get_position_quantity(code)
                has_pending = self.check_pending_orders(code, 'BUY' if bsp.is_buy else 'SELL')
                try:
                    all_pos = self.ib.positions()
                    current_total_pos = len(set([p.contract.symbol for p in all_pos if p.contract.secType == 'STK']))
                except: current_total_pos = 0

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
                for p in pos_list:
                    if p.position != 0:
                        positions_data.append({
                            'symbol': p.contract.symbol,
                            'qty': int(p.position),
                            'mkt_value': round(p.position * p.avgCost, 2),
                            'avg_cost': round(p.avgCost, 2)
                        })
            else:
                for item in actual_items:
                    if item.position != 0:
                        positions_data.append({
                            'symbol': item.contract.symbol,
                            'qty': int(item.position),
                            'mkt_value': round(item.marketValue, 2),
                            'avg_cost': round(item.averageCost, 2)
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
        report = (
            f"🌆 **美股收盘日报 ({self.venue})**\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"账户净值: ${total:,.2f}\n"
            f"可用资金: ${available:,.2f}\n"
            f"当日自动撤单: {cancelled} 笔\n"
            f"当前持仓数量: {len(positions)}\n"
            f"----------------------------------\n"
            f"US 交易模块已进入夜间休眠模式。"
        )
        
        # 3. Discord 推送
        if self.discord_bot:
            await self.discord_bot.send_notification(report)
            
        self.log_message.emit(f"✅ [收盘] 美股 {self.venue} 结转动作已完成。")

    async def _execute_trade_async(self, code: str, action: str, price: float, **kwargs):
        """异步下单 - 根据 self.venue 执行"""
        symbol = code.split('.')[-1]
        qty = kwargs.get('qty', 0)
        if qty == 0:
            # 默认单笔 1W 美金 (优化B将改进此策略)
            available, total, _ = await self.get_account_assets_async()
            qty = max(1, int(10000 / price))
        
        # 预先检查并标准化动作
        action = action.upper()

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
                qty = min(qty, curr_qty)
                if qty <= 0: return

            limit_price = round(price * 1.01, 2) if action == "BUY" else round(price * 0.99, 2)
            
            order = LimitOrder(action, qty, limit_price)
            trade = self.ib.placeOrder(contract, order)
            self.log_message.emit(f"🚀 [美股-IB] 限价单提交成功: {symbol} {action} {qty} @ ${limit_price:.2f}")
            
            # 记录交易
            self._record_trade_to_db(code, action, qty, limit_price, **kwargs)

            # 启动订单跟踪
            threading.Thread(
                target=self._track_order_status,
                args=(None, code, action, qty, limit_price, "IB", trade),
                daemon=True
            ).start()
            
        except Exception as e:
            self.log_message.emit(f"❌ [美股-IB] 下单失败: {e}")

    def _track_order_status(self, order_id: str, code: str, action: str, qty: int, price: float, venue: str, trade_obj=None):
        """轮询订单成交状态，汇报执行情况 (美股多通道)"""
        import time as _time
        import asyncio

        for attempt in range(12):  # 最多 60 秒
            _time.sleep(5)
            try:
                status = ""
                filled_qty = 0
                filled_avg = 0.0
                status_str = ""

                if venue == "FUTU":
                    from futu import OrderStatus, RET_OK
                    ret, data = self.trd_ctx.order_list_query(
                        order_id=order_id, trd_env=self.trd_env
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
                        asyncio.run_coroutine_threadsafe(
                            self.discord_bot.send_notification(msg), self.discord_bot.loop
                        )
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
                    self.ib.placeOrder(p.contract, MarketOrder("SELL" if qty > 0 else "BUY", abs(qty)))
                    count += 1
                self.log_message.emit(f"🔥 [美股-IB] 已提交 {count} 个清仓订单 (市价单)")
            except Exception as e:
                self.log_message.emit(f"❌ [美股-IB] 清仓失败: {e}")
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
                    # 这里为了安全和组件复用，调用 Schwab 的限价单逻辑，价格设为 0 (触发下单逻辑里的价格计算或报错)
                    # 实际上可能需要查实时价，但一键清仓在 Schwab 上通常需要市价单。
                    # 为了不让用户承担过高风险，暂不支持 Schwab 一键清仓，或提示手动操作。
                    self.log_message.emit(f"⚠️ [美股-Schwab] 暂不支持自动一键清仓，请手动处理 {symbol}")
                    # count += 1
                self.log_message.emit(f"🔥 [美股-Schwab] 一键清仓功能受限")
            except Exception as e:
                self.log_message.emit(f"❌ [美股-Schwab] 清仓异常: {e}")

    def _execute_trade(self, code, action, price):
        """同步包装下单"""
        asyncio.run_coroutine_threadsafe(self._execute_trade_async(code, action, price), self.loop)

    def _close_all_positions(self):
        """同步包装清仓"""
        asyncio.run_coroutine_threadsafe(self._close_all_positions_async(), self.loop)

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

            # --- 多周期共振过滤 (优化 A: 30M+5M 严苛嵌套) ---
            if chan_5m:
                bsp_5m_list = chan_5m.get_latest_bsp(number=0)
                us_now = self.get_us_now()
                if not bsp_5m_list:
                    self.log_message.emit(f"⚠️ [美股] {code} {bsp.type2str()} 30M 信号未获得 5M 共振确认 (5M无任何信号)，拦截")
                    return

                # 获取绝对最新的 5M 信号进行验证
                sorted_5m = sorted(bsp_5m_list, key=lambda x: str(x.klu.time), reverse=True)
                latest_b = sorted_5m[0]
                b_dt = datetime(latest_b.klu.time.year, latest_b.klu.time.month, latest_b.klu.time.day, 
                               latest_b.klu.time.hour, latest_b.klu.time.minute, latest_b.klu.time.second)
                
                # 严苛过滤：1. 方向一致; 2. 30分钟内
                is_same_dir = (latest_b.is_buy == is_buy)
                is_recent = (us_now - b_dt).total_seconds() < 1800 # 30分钟
                
                if not is_same_dir:
                    self.log_message.emit(f"⚠️ [美股] {code} {bsp.type2str()} 5M 确认失败: 5M 最新信号为反向 {latest_b.type2str()} @ {latest_b.klu.time}")
                    return
                if not is_recent:
                    self.log_message.emit(f"⚠️ [美股] {code} {bsp.type2str()} 5M 确认失败: 5M 最新信号 {latest_b.type2str()} 已过时(>30min) @ {latest_b.klu.time}")
                    return
                    
                self.log_message.emit(f"💎 [美股] {code} {bsp.type2str()} 30M+5M 多周期共振确认成功 (最新5M信号: {latest_b.type2str()})")

            # --- 0. ML 优先审查 & 一票否决 (P1 加强) ---
            ml_res = {}
            ml_threshold = TRADING_CONFIG.get('ml_threshold', 0.70)
            
            if is_buy:
                ml_res = self.signal_validator.validate_signal(chan_30m, bsp)
                prob = ml_res.get('prob', 0) if ml_res else 0
                if prob < ml_threshold:
                    self.log_message.emit(f"🤖 [美股] {code} {bsp.type2str()} ML 未达标 ({prob*100:.1f}% < {ml_threshold*100:.0f}%) -> 一票否决")
                    return
                self.log_message.emit(f"🤖 [美股] {code} {bsp.type2str()} ML 校验通过 ({prob*100:.1f}%)")
            else:
                # 优化 D 类似逻辑，同步应用到美股：卖点 0.4 阈值
                ml_res = self.signal_validator.validate_signal(chan_30m, bsp)
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
                if not is_valid_time:
                    self.log_message.emit(f"⏮️ [美股] {code} {bsp.type2str()} 信号过期(>{window_sec/3600:.1f}h)，跳过下单")
                elif self.dry_run: 
                    self.log_message.emit(f"📝 [美股-模拟] {code} {score}分满足，跳过执行")
                elif not self.is_trading_time():
                    self.log_message.emit(f"⏳ [美股] {code} {bsp.type2str()} 信号满足，但当前非交易时间，仅通告跳过下单。")
                else:
                    self.cmd_queue.put(('EXECUTE_TRADE', {
                        'code': code, 
                        'action': "BUY" if is_buy else "SELL", 
                        'price': bsp.klu.close,
                        'name': name,
                        'signal_type': bsp.type2str(),
                        'ml_prob': ml_res.get('prob', 0),
                        'visual_score': score
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
            start_time = (now_t - timedelta(days=20)).strftime("%Y-%m-%d")
            
            local_chan_config = CHAN_CONFIG.copy()
            chan = CChan(
                code=code,
                begin_time=start_time,
                end_time=end_time,
                data_src=DATA_SRC.SCHWAB, 
                lv_list=[KL_TYPE.K_30M],
                config=CChanConfig(local_chan_config)
            )
            
            if chan[0]:
                kl_list = list(chan[0].klu_iter())
                if len(kl_list) > 0:
                    close_prices = [k.close for k in kl_list]
                    high_prices = [k.high for k in kl_list]
                    low_prices = [k.low for k in kl_list]
                
                tr_list = []
                for i in range(1, len(close_prices)):
                    hl = high_prices[i] - low_prices[i]
                    hc = abs(high_prices[i] - close_prices[i-1])
                    lc = abs(low_prices[i] - close_prices[i-1])
                    tr_list.append(max(hl, hc, lc))
                
                atr_val = sum(tr_list[-10:]) / 10 if len(tr_list) >= 10 else (current * 0.02)
                
                self.position_trackers[code] = {
                    'entry_price': p['avg_cost'],
                    'highest_price': max(current, p['avg_cost']),
                    'atr': atr_val,
                    'trail_active': False
                }
                self.log_message.emit(f"✅ {code} 风控载入: 成本=${p['avg_cost']:.2f}, ATR=${atr_val:.3f}")
        except Exception as ex:
             self.log_message.emit(f"⚠️ 初始化 {code} ATR失败: {ex}")

    async def _initialize_position_trackers(self):
        """为现有持仓初始化追踪止损器 (方案丙)"""
        self.log_message.emit("🛡️ 正在为当前美股持仓初始化风险监控...")
        await asyncio.sleep(3)  # ⏳ 给 3 秒缓冲时间，让 IB 充分同步底层 positions 缓存
        try:
            available, total, positions = await self.get_account_assets_async()
            if not positions: return
            
            # --- 💡 [补偿买入自愈] 清除今天已发出通知、但实际上「未持仓」的标的，让其可被重新扫描触发 ---
            now_et_str = self.get_us_now().strftime("%Y-%m-%d")
            cleanup_keys = []
            for sig_key, sig_time in list(self.notified_signals.items()):
                if sig_time.startswith(now_et_str):
                    if sig_key not in self.position_trackers:
                        cleanup_keys.append(sig_key)
            
            if cleanup_keys:
                self.log_message.emit(f"♻️ [风控自愈] 发现 {len(cleanup_keys)} 只今天已达标但未成交/漏单的股票 ({', '.join(cleanup_keys)})，已从拦截池释放，下轮扫描将重新追踪补买！")
                for k in cleanup_keys:
                    del self.notified_signals[k]
                self._save_notified_signals()

            # 📊 [增强逻辑] 初始化完毕后，自动向面板汇总报告全部监控清单
            if self.position_trackers:
                 summary_lines = ["🛡️ **[美股持仓风控监控中]**"]
                 for code, tr in self.position_trackers.items():
                     summary_lines.append(f" 📍 **{code}**: 成本价=${tr['entry_price']:.2f} | 止损ATR=${tr['atr']:.3f}")
                 self.log_message.emit("\n".join(summary_lines))
        except Exception as e:
            print(f"初始化持仓风控失败: {e}")

    async def _check_trailing_stops(self):
        """活性持仓止损检查算法 (方案丙) - 异步高频安全哨兵"""
        try:
            available, total, positions = await self.get_account_assets_async()
            current_held_codes = {f"US.{p['symbol']}": p for p in positions}
            
            # --- 自愈补救机制：为缺失的持仓冷启动加载 ATR ---
            for code, p in current_held_codes.items():
                if code not in self.position_trackers:
                    asyncio.create_task(self._initialize_single_tracker_async(p))
            
            for code in list(self.position_trackers.keys()):
                # 1. 检查是否存在持仓
                if code not in current_held_codes:
                    self.log_message.emit(f"🔄 {code} 已无持仓，停止移动止损追踪")
                    del self.position_trackers[code]
                    continue
                
                p = current_held_codes[code]
                qty = abs(p['qty'])
                current_price = p.get('mkt_price') or (p['mkt_value'] / p['qty'] if p['qty'] != 0 else 0)
                
                # 2. 获取追踪器
                tracker = self.position_trackers[code]
                
                # 3. 更新最高价
                if current_price > tracker['highest_price']:
                    tracker['highest_price'] = current_price
                    self.log_message.emit(f"📈 {code} 创美股持仓新高: ${current_price:.2f}")
                
                # 4. 风控条件对齐
                entry_price = tracker.get('entry_price', current_price)
                highest = tracker['highest_price']
                atr = tracker['atr']
                
                atr_init = TRADING_CONFIG.get('atr_stop_init', 1.2)
                atr_trail = TRADING_CONFIG.get('atr_stop_trail', 2.5)
                atr_profit = TRADING_CONFIG.get('atr_profit_threshold', 1.5)
                
                # 触发状态：开启移动止损
                if not tracker.get('trail_active', False):
                    if (current_price - entry_price) >= (atr * atr_profit):
                        tracker['trail_active'] = True
                        self.log_message.emit(f"🔓 {code} 已达获利门槛(+{atr_profit}*ATR)，切换为移动止损模式")
                
                if tracker.get('trail_active', False):
                    stop_price = highest - (atr * atr_trail)
                    stop_type = "移动止损"
                else:
                    stop_price = entry_price - (atr * atr_init)
                    stop_type = "固定止损"
                
                self.log_message.emit(f"🛡️ [ATR监测] {code}: 现价 ${current_price:.2f}, 止损位 ${stop_price:.2f} ({stop_type}) [最高价 ${highest:.2f}, ATR ${atr:.4f}]")
                
                # 5. 触发则立刻下平仓单
                if current_price < stop_price:
                    self.log_message.emit(f"🚨 {code} 触发{stop_type}! 最高价=${highest:.2f}, 现价=${current_price:.2f}, 止损位=${stop_price:.2f}")
                    self.cmd_queue.put(('EXECUTE_TRADE', {
                        'code': code, 
                        'action': 'SELL', 
                        'price': current_price,
                        'exit_reason': stop_type
                    }))
                    del self.position_trackers[code]
        except Exception as e:
             logger.error(f"浮动止损检查异常: {e}")

    async def _get_futu_assets_async(self) -> Tuple[float, float, list]:
        """通过 Futu API 获取美股账户资产及持仓 (支持模拟与真实自适应)"""
        try:
            # 1. 自动探查账户环境
            acc_id = 0
            actual_env = 'REAL'
            ret_list, account_list = self.trd_ctx.get_acc_list()
            
            if ret_list == RET_OK and not account_list.empty:
                # 📊 [修正选号] 过滤出与 self.trd_env 相符的账户 (SIMULATE / REAL)
                target_env_str = 'SIMULATE' if self.trd_env == TrdEnv.SIMULATE else 'REAL'
                matched = account_list[account_list['trd_env'] == target_env_str]
                if not matched.empty:
                    row = matched.iloc[0]
                else:
                    row = account_list.iloc[0]
                
                acc_id = row['acc_id']
                actual_env = target_env_str

            # 2. 查询账户资金
            ret, data = self.trd_ctx.accinfo_query(acc_id=acc_id, trd_env=actual_env)
            available, total = 0.0, 0.0
            if ret == RET_OK and not data.empty:
                available = float(data.iloc[0]['cash'])
                total = float(data.iloc[0].get('total_assets', data.iloc[0].get('power', 0.0)))
            else:
                self.log_message.emit(f"⚠️ [美股-Futu] 资金查询反馈 [{ret}]: {data}")
            
            # 3. 查询持仓
            positions = []
            ret_pos, pos_data = self.trd_ctx.position_list_query(acc_id=acc_id, trd_env=actual_env)
            if ret_pos == RET_OK and not pos_data.empty:
                for _, row in pos_data.iterrows():
                    qty = int(row['qty'])
                    if qty == 0: continue
                    symbol = row['code'].split('.')[-1]
                    positions.append({
                        'symbol': symbol,
                        'qty': qty,
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
                
            ret, data = self.trd_ctx.place_order(
                price=limit_price,
                qty=qty,
                code=code,
                trd_side=side,
                order_type=OrderType.NORMAL,
                trd_env=self.trd_env  # 🚨 传递底层环境变量
            )
            if ret == RET_OK:
                order_id = data.iloc[0]['order_id']
                self.log_message.emit(f"🚀 [美股-Futu] 限价单提交成功: {code} {action} {qty} @ ${limit_price:.2f} (ID: {order_id})")

                # 启动订单跟踪
                threading.Thread(
                    target=self._track_order_status,
                    args=(order_id, code, action, qty, limit_price, "FUTU"),
                    daemon=True
                ).start()
            else:
                self.log_message.emit(f"❌ [美股-Futu] 下单失败: {data}")
        except Exception as e:
             self.log_message.emit(f"❌ [美股-Futu] 下单异常: {e}")
