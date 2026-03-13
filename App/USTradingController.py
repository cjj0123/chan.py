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
        self.client_id = 437
        
        self.charts_dir = "charts_us"
        os.makedirs(self.charts_dir, exist_ok=True)
        
        self.visual_judge = VisualJudge()
        self.ml_validator = SignalValidator()
        self.min_visual_score = TRADING_CONFIG.get('min_visual_score', 70)
        self.dry_run = TRADING_CONFIG.get('us_dry_run', False)
        
        # 信号历史，用于去重
        self.notified_signals = {}
        self.visual_score_cache = {}
        
        # 线程池：用于执行耗时的 AI 评分和绘图任务，防止阻塞 IB 驱动循环
        self.executor = ThreadPoolExecutor(max_workers=10)

        self.us_tz = pytz.timezone('America/New_York')
        
        # 并发控制：美股扫描使用信号量限制同时请求 IB 数据的人数，防止被封 IP 或限流
        self.scan_semaphore = asyncio.Semaphore(8)

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
        # Apply nest_asyncio to allow nested loops and better thread handling
        nest_asyncio.apply(self.loop)
        
        try:
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

    async def _async_main(self):
        """真正的异步主循环"""
        self.ib = IB()
        last_scan_bar = self.get_us_now() - timedelta(minutes=60)
        last_heartbeat_min = -1
        last_reconnect_time = 0
        
        while self._is_running:
            try:
                # 1. 连接维护
                if not self.ib.isConnected():
                    now_ts = time.time()
                    if now_ts - last_reconnect_time > 15:
                        last_reconnect_time = now_ts
                        try:
                            # Randomize clientId to avoid conflicts on restart
                            target_client_id = self.client_id + random.randint(0, 1000)
                            self.log_message.emit(f"🔄 [美股] 正在发起异步连接 ({self.host}:{self.port}, ID:{target_client_id})...")
                            await self.ib.connectAsync(self.host, self.port, clientId=target_client_id, timeout=10)
                            self.log_message.emit(f"🔌 [美股] IB 连接成功 (ID:{target_client_id})，同步实时数据流")
                            self.ib.reqAccountUpdates(True)
                        except Exception as e:
                            self.log_message.emit(f"⚠️ [美股] 连接失败: {e}")
                            if "loop is closed" in str(e).lower():
                                self.log_message.emit("♻️ [美股] 检测到事件循环异常，正在重建 IB 客户端...")
                                self.ib = IB() # Force recreate instance to pick up current loop
                    await asyncio.sleep(1)
                    continue

                # 2. 处理 GUI 指令
                while not self.cmd_queue.empty():
                    try:
                        cmd_type, data = self.cmd_queue.get_nowait()
                        self.log_message.emit(f"📥 [指令] 正在执行: {cmd_type}")
                        await self._handle_gui_command(cmd_type, data)
                    except Exception as ce:
                        self.log_message.emit(f"⚠️ [指令] 响应失败: {ce}")

                # 3. 驱动的心跳
                await asyncio.sleep(0.5)

                if self._is_paused:
                    continue

                # 4. 周期扫描逻辑
                now_et = self.get_us_now()
                if now_et.minute != last_heartbeat_min:
                    status = "监控心跳" if self.is_trading_time() else "非交易时段"
                    self.log_message.emit(f"💖 {status} (NY: {now_et.strftime('%H:%M')})")
                    last_heartbeat_min = now_et.minute

                if not self.is_trading_time():
                    await asyncio.sleep(1.0)
                    continue

                # 扫描触发
                current_bar_et = now_et.replace(minute=(now_et.minute // 30) * 30, second=0, microsecond=0)
                if current_bar_et > last_scan_bar:
                    if now_et.minute % 30 >= 1:
                        self.log_message.emit(f"⚡ [美股] 触发周期扫描 (Async Mode)")
                        try:
                            await self._perform_strategy_scan_async()
                        except Exception as e:
                            self.log_message.emit(f"❌ [美股] 异步扫描异常: {e}")
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
                asyncio.create_task(self._perform_strategy_scan_async())
            elif cmd_type == 'QUERY_FUNDS':
                available, total, positions = await asyncio.wait_for(self.get_account_assets_async(), timeout=15)
                self.funds_updated.emit(available, total, positions)
            elif cmd_type == 'CLOSE_ALL':
                await asyncio.wait_for(self._close_all_positions_async(), timeout=30)
            elif cmd_type == 'EXECUTE_TRADE':
                c, a, p = data['code'], data['action'], data['price']
                self.log_message.emit(f"🚀 [美股] 执行验证指令: {c} {a}")
                await asyncio.wait_for(self._execute_trade_async(c, a, p), timeout=20)
        except asyncio.TimeoutError:
            self.log_message.emit(f"⚠️ [指令] 指令 {cmd_type} 执行超时")

    async def _perform_strategy_scan_async(self):
        """执行异步策略扫描"""
        self.log_message.emit(f"🔍 [美股] 正在获取分组 '{self.watchlist_group}' 代码...")
        us_codes_set = set()
        
        try:
            from futu import OpenQuoteContext, RET_OK
            
            def get_futu_codes():
                try:
                    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
                    ret, data = ctx.get_user_security(group_name=self.watchlist_group)
                    ctx.close()
                    if ret == RET_OK and not data.empty:
                        return [c for c in data['code'].tolist() if c.startswith("US.")]
                except:
                    pass
                return []

            # 1. Fetch from Futu via executor (Sync -> Async)
            loop = asyncio.get_running_loop()
            futu_codes = await loop.run_in_executor(self.executor, get_futu_codes)
            us_codes_set.update(futu_codes)

            if self.ib and self.ib.isConnected():
                us_codes_set.update([f"US.{p.contract.symbol}" for p in self.ib.positions() if p.contract.secType == 'STK'])

            us_codes = sorted(list(us_codes_set))
            if not us_codes: us_codes = ['US.AAPL', 'US.TSLA', 'US.NVDA']
            
            self.log_message.emit(f"📡 [美股] 异步并行扫描开始 (共 {len(us_codes)} 只, 并发: 5)...")
            
            # 1. 批量验证合约
            contracts = []
            for code in us_codes:
                symbol = code.split(".")[1] if "." in code else code
                contracts.append(Stock(symbol, 'SMART', 'USD'))
            
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

            # 2. 批量极速同步 (Phase 5: Sync-then-Scan)
            self.log_message.emit(f"🔄 [美股] 执行批量同步 (30m & 5m)...")
            sync_start = time.perf_counter()
            try:
                # 使用已经实现的 Phase 3 异步下载器
                await download_and_save_all_stocks_async(
                    us_codes, days=60, timeframes=['30m', '5m'], 
                    log_callback=self.log_message.emit, 
                    ib_client=self.ib
                )
                sync_time = time.perf_counter() - sync_start
                self.log_message.emit(f"✅ [美股] 批量同步完成 (耗时: {sync_time:.2f}s)")
            except Exception as e:
                self.log_message.emit(f"⚠️ [美股] 批量同步异常: {e}")

            # 3. 并行分析 (使用同步后的本地数据)
            scan_start = time.perf_counter()
            self.log_message.emit(f"🚀 [美股] 开始异步并行扫描 (共 {len(us_codes)} 只)...")
            async def semaphore_analyze(code, idx, total):
                async with self.scan_semaphore:
                    try:
                        symbol = code.split(".")[1] if "." in code else code
                        contract = symbol_to_contract.get(symbol)
                        await self._analyze_stock_async(code, index=idx, total=total, contract=contract)
                    except Exception as e:
                        self.log_message.emit(f"❌ [美股] 分析 {code} 报错: {e}")

            tasks = [semaphore_analyze(code, i + 1, len(us_codes)) for i, code in enumerate(us_codes)]
            await asyncio.gather(*tasks)

            total_scan_time = time.perf_counter() - scan_start
            self.log_message.emit(f"✅ [美股] 异步并行扫描完成, 总耗时: {total_scan_time:.2f}s")
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 扫描过程异常: {e}")

    async def _analyze_stock_async(self, code: str, index: int = 0, total: int = 0, contract=None):
        """异步分析单只股票"""
        if contract is None: return
        prefix = f"[{index}/{total}] "
        db = CChanDB()
        table_name = "kline_30m"
        
        # Phase 5: 移除逐个扫描时的网络请求，直接使用预同步好的本地数据
        network_time = 0.0
        
        # 1. 检查本地数据库是否有历史数据
        sql_check = f"SELECT MAX(date) as last_date FROM {table_name} WHERE code = '{code}'"
        res = db.execute_query(sql_check)
        if res.empty or not res.iloc[0]['last_date']:
            return # 无数据可供分析

        # 4. 从本地数据库加载完整 60 天数据供分析 (保证 Chan 分析的条数)
        sixty_days_ago = (datetime.now() - timedelta(days=63)).strftime("%Y-%m-%d")
        sql_load = f"SELECT * FROM {table_name} WHERE code = '{code}' AND date >= '{sixty_days_ago}' ORDER BY date"
        df_all = db.execute_query(sql_load)
        
        if df_all.empty: return
        
        # 强制排序并去重，保证时间严格单调递增
        df_all['date_dt'] = pd.to_datetime(df_all['date'])
        df_all = df_all.sort_values('date_dt').drop_duplicates(subset=['date'], keep='last').reset_index(drop=True)
        
        units = []
        for _, row in df_all.iterrows():
            dt_val = row['date_dt']
            
            # 增加鲁棒性：处理可能出现的非数值/二进制垃圾数据
            def safe_float(val):
                if isinstance(val, (bytes, bytearray)):
                    return 0.0
                try:
                    return float(val)
                except:
                    return 0.0

            units.append(CKLine_Unit({
                DATA_FIELD.FIELD_TIME: CTime(dt_val.year, dt_val.month, dt_val.day, dt_val.hour, dt_val.minute),
                DATA_FIELD.FIELD_OPEN: safe_float(row['open']), DATA_FIELD.FIELD_HIGH: safe_float(row['high']),
                DATA_FIELD.FIELD_LOW: safe_float(row['low']), DATA_FIELD.FIELD_CLOSE: safe_float(row['close']),
                DATA_FIELD.FIELD_VOLUME: safe_float(row['volume']), DATA_FIELD.FIELD_TURNOVER: 0.0, DATA_FIELD.FIELD_TURNRATE: 0.0
            }))

        analysis_start = time.perf_counter()
        local_chan_config = CHAN_CONFIG.copy()
        local_chan_config['trigger_step'] = True
        chan_30m = CChan(code=code, data_src=DATA_SRC.IB, lv_list=[KL_TYPE.K_30M], config=CChanConfig(local_chan_config), autype=AUTYPE.QFQ)
        chan_30m.trigger_load({KL_TYPE.K_30M: units})
        analysis_time = time.perf_counter() - analysis_start
        
        self.log_message.emit(f"📊 {prefix}{code} [网络: {network_time:.2f}s, 分析: {analysis_time:.2f}s]")
        
        if len(chan_30m[0]) == 0: return

        bsp_list = chan_30m.get_latest_bsp(number=0)
        # 仅取最新的一个信号 (按时间排序)
        if bsp_list:
            bsp_list = sorted(bsp_list, key=lambda x: str(x.klu.time), reverse=True)[:1]
            
        us_now = self.get_us_now()
        in_market = self.is_trading_time()
        window_sec = 3600 if in_market else 86400
        
        for bsp in bsp_list:
            bsp_dt = datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day, 
                              bsp.klu.time.hour, bsp.klu.time.minute, bsp.klu.time.second)
            if (us_now - bsp_dt).total_seconds() <= window_sec: 
                sig_key = f"{code}_{str(bsp.klu.time)}_{bsp.type2str()}"
                if sig_key in self.notified_signals: continue
                
                self.notified_signals[sig_key] = us_now.strftime("%Y-%m-%d %H:%M:%S")
                self.log_message.emit(f"🎯 [美股] {code} 发现信号: {bsp.type2str()} @ {bsp.klu.time}")
                
                chan_5m = None
                try:
                    # Phase 5: 移除 5M 网络请求，直接从预同步好的本地库加载
                    net_5m_time = 0.0
                    table_5m = "kline_5m"
                    
                    # 从本地加载 10 天 5M 数据
                    ten_days_ago = (datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d")
                    sql_load_5m = f"SELECT * FROM {table_5m} WHERE code = '{code}' AND date >= '{ten_days_ago}' ORDER BY date"
                    df_all_5m = db.execute_query(sql_load_5m)
                    
                    if not df_all_5m.empty:
                        # 强制排序并去重
                        df_all_5m['date_dt'] = pd.to_datetime(df_all_5m['date'])
                        df_all_5m = df_all_5m.sort_values('date_dt').drop_duplicates(subset=['date'], keep='last').reset_index(drop=True)
                        
                        units_5m = []
                        for _, row in df_all_5m.iterrows():
                            dt_val_5m = row['date_dt']
                            units_5m.append(CKLine_Unit({
                                DATA_FIELD.FIELD_TIME: CTime(dt_val_5m.year, dt_val_5m.month, dt_val_5m.day, dt_val_5m.hour, dt_val_5m.minute),
                                DATA_FIELD.FIELD_OPEN: safe_float(row['open']), DATA_FIELD.FIELD_HIGH: safe_float(row['high']),
                                DATA_FIELD.FIELD_LOW: safe_float(row['low']), DATA_FIELD.FIELD_CLOSE: safe_float(row['close']),
                                DATA_FIELD.FIELD_VOLUME: safe_float(row['volume']), DATA_FIELD.FIELD_TURNOVER: 0.0, DATA_FIELD.FIELD_TURNRATE: 0.0
                            }))
                        chan_5m = CChan(code=code, data_src=DATA_SRC.IB, lv_list=[KL_TYPE.K_5M], config=CChanConfig(local_chan_config), autype=AUTYPE.QFQ)
                        chan_5m.trigger_load({KL_TYPE.K_5M: units_5m})
                    self.log_message.emit(f"   ↳ {code} 5M数据获取完成 [网络: {net_5m_time:.2f}s]")
                except Exception as e5m:
                    logger.warning(f"5M cache logic failed for {code}: {e5m}")

                pos_qty = self.get_position_quantity(code)
                has_pending = self.check_pending_orders(code, 'BUY' if bsp.is_buy else 'SELL')
                try:
                    all_pos = self.ib.positions()
                    current_total_pos = len(set([p.contract.symbol for p in all_pos if p.contract.secType == 'STK']))
                except: current_total_pos = 0

                self.executor.submit(self._handle_signal_sync, code, bsp, chan_30m, chan_5m, 
                                    pos_qty=pos_qty, has_pending=has_pending, current_total_pos=current_total_pos)

    def get_position_quantity(self, code: str) -> int:
        if self.ib is None or not self.ib.isConnected(): return 0
        symbol = code.split('.')[-1]
        for p in self.ib.positions():
            if p.contract.symbol == symbol: return int(p.position)
        return 0

    def check_pending_orders(self, code: str, side: str) -> bool:
        if self.ib is None or not self.ib.isConnected(): return False
        symbol = code.split('.')[-1]
        for trade in self.ib.openTrades():
            if trade.contract.symbol == symbol and trade.order.action == side.upper():
                if trade.orderStatus.status in ('PendingSubmit', 'PreSubmitted', 'Submitted'):
                    return True
        return False

    async def get_account_assets_async(self) -> Tuple[float, float, list]:
        """异步获取账户资产 (使用线程池执行同步 IB 调用)"""
        if self.ib is None or not self.ib.isConnected(): 
            self.log_message.emit("⚠️ IB 未连接，无法查询资金")
            return 0.0, 0.0, []
        try:
            loop = asyncio.get_running_loop()
            vals = await loop.run_in_executor(self.executor, self.ib.accountValues)
            port = await loop.run_in_executor(self.executor, self.ib.portfolio)
            
            available, total = 0.0, 0.0
            found_tags = []
            
            # 常见标签集合
            available_tags = ('AvailableFunds', 'AvailableFunds-S', 'FullAvailableFunds', 'FullAvailableFunds-S')
            net_liq_tags = ('NetLiquidation', 'NetLiquidation-S', 'NetLiquidationByCurrency')
            
            for v in vals:
                # 记录找到的标签，方便调试
                if v.tag in available_tags or v.tag in net_liq_tags:
                    found_tags.append(f"{v.tag}({v.currency}):{v.value}")

                if v.tag in available_tags and v.currency in ('USD', '', 'BASE'):
                    available = max(available, float(v.value))
                if v.tag in net_liq_tags and v.currency in ('USD', '', 'BASE'):
                    total = max(total, float(v.value))
            
            if available == 0.0 and total == 0.0:
                self.log_message.emit(f"⚠️ 未能从账户获取到资金信息。找到的标签: {', '.join(found_tags[:5])}...")
            
            positions_data = []
            for item in port:
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
            self.log_message.emit(f"❌ 账户资金查询异常: {e}")
            return 0.0, 0.0, []

    def get_account_assets(self) -> Tuple[float, float, list]:
        """同步接口 (GUI 兼容)"""
        if self.ib is None or not self.ib.isConnected(): return 0.0, 0.0, []
        try:
            available, total = 0.0, 0.0
            for v in self.ib.accountValues():
                if v.tag == 'AvailableFunds' and (v.currency in ('USD', '')): available = float(v.value)
                if v.tag == 'NetLiquidation' and (v.currency in ('USD', '')): total = float(v.value)
            
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
        except: return 0.0, 0.0, []

    async def _execute_trade_async(self, code: str, action: str, price: float):
        """异步下单"""
        try:
            symbol = code.split('.')[-1]
            contract = Stock(symbol, 'SMART', 'USD')
            await self.ib.qualifyContractsAsync(contract)
            
            if price <= 0:
                self.log_message.emit(f"⚠️ {symbol} 价格异常 ({price})，无法计算下单数量")
                return
                
            qty = max(1, int(10000 / price))
            
            if action == "SELL":
                curr_qty = self.get_position_quantity(code)
                qty = min(qty, curr_qty)
                if qty <= 0: return

            order = MarketOrder(action, qty)
            await self.ib.placeOrderAsync(contract, order)
            self.log_message.emit(f"🚀 [美股] 订单提交成功: {symbol} {action} {qty}")
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 下单失败: {e}")

    async def _close_all_positions_async(self):
        """异步一键清仓"""
        try:
            positions = self.ib.positions()
            count = 0
            for p in positions:
                qty = int(p.position)
                if qty == 0: continue
                await self.ib.placeOrderAsync(p.contract, MarketOrder("SELL" if qty > 0 else "BUY", abs(qty)))
                count += 1
            self.log_message.emit(f"🔥 [美股] 已提交 {count} 个清仓订单")
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 清仓失败: {e}")

    def _execute_trade(self, code, action, price):
        """同步包装下单"""
        asyncio.run_coroutine_threadsafe(self._execute_trade_async(code, action, price), self.loop)

    def _close_all_positions(self):
        """同步包装清仓"""
        asyncio.run_coroutine_threadsafe(self._close_all_positions_async(), self.loop)

    def _handle_signal_sync(self, code: str, bsp, chan_30m, chan_5m=None, 
                           pos_qty: int = 0, has_pending: bool = False, current_total_pos: int = 0):
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

            # 1. 绘图 (为视觉 AI 准备素材)
            chart_paths = []
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

            # 2. 视觉 AI 验证 (优先执行)
            visual_start = time.perf_counter()
            visual_res = self.visual_judge.evaluate(chart_paths, bsp.type2str())
            visual_time = time.perf_counter() - visual_start
            
            if not visual_res:
                self.log_message.emit(f"⚠️ [美股] {code} 视觉评分返回为空")
                return
            
            score = visual_res.get('score', 0)
            
            # 3. ML 验证 (混合评分策略)
            ml_start = time.perf_counter()
            ml_res = self.ml_validator.validate_signal(chan_30m, bsp)
            ml_time = time.perf_counter() - ml_start
            
            prob = ml_res.get('prob', 0) if ml_res else 0
            final_pass = ml_res.get('is_valid', False) if ml_res else False
            override_msg = ""
            
            if score >= 90:
                if prob >= 0.20:
                    final_pass = True
                    override_msg = f"🌟 触发高分视觉覆盖 (Visual:{score}, ML:{prob:.2f})"
                elif prob < 0.10:
                    final_pass = False
                    override_msg = "🚨 ML 概率极低 (<10%)，视觉覆盖失效"
            elif score < 70:
                final_pass = False
                override_msg = f"📉 视觉得分不及格 ({score})"
            
            if not final_pass:
                fail_reason = override_msg if override_msg else ml_res.get('msg', 'No ML result') if ml_res else "ML Data Missing"
                self.log_message.emit(f"🤖 [美股] {code} {bsp.type2str()} 拦截 [Visual:{score}, ML:{prob:.2f}]: {fail_reason}")
                return

            if override_msg:
                self.log_message.emit(f"✅ [美股] {code} {bsp.type2str()} 最终综合评分: {score} | {override_msg}")
            else:
                self.log_message.emit(f"✅ [美股] {code} 最终综合评分: {score} | ML 校验通过")

            if self.discord_bot and score >= self.min_visual_score:
                msg = f"🗽 **美股自动化预警**\n股票: {code}\n信号: {bsp.type2str()}\n评分: **{score}分**\nML概率: {ml_res.get('prob',0)*100:.1f}%"
                if self.discord_bot.loop and self.discord_bot.loop.is_running():
                    asyncio.run_coroutine_threadsafe(self.discord_bot.send_notification(msg, path_30m), self.discord_bot.loop)

            if score >= self.min_visual_score:
                if self.dry_run: 
                    self.log_message.emit(f"📝 [美股-模拟] {code} {score}分满足，跳过执行")
                else:
                    self.cmd_queue.put(('EXECUTE_TRADE', {'code': code, 'action': "BUY" if is_buy else "SELL", 'price': bsp.klu.close}))
                    self.log_message.emit(f"📩 [美股] {code} 下单指令已发送主线程")
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股] 信号处理异常: {e}")
            print(traceback.format_exc())
