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
import nest_asyncio
from concurrent.futures import ThreadPoolExecutor

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
        
        # 线程池：用于执行耗时的 AI 评分和绘图任务，防止阻塞 IB 驱动循环
        self.executor = ThreadPoolExecutor(max_workers=3)

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
                self.ib.reqAccountUpdates(True) # 强制订阅账户更新，确保市值实时同步
                self.log_message.emit(f"🔌 [美股] 已连接 IB Gateway 并开启同步接口 ({self.host}:{self.port})")
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
        """主交易循环 - 真正高频响应非阻塞版 (增强恢复能力)"""
        print(f"\n[DEBUG] {datetime.now()} US Trading Thread START for group {self.watchlist_group}")
        self._is_running = True
        
        while self._is_running:
            loop = None
            try:
                self.log_message.emit(f"🚀 [美股] 正在初始化驱动环境...")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                nest_asyncio.apply(loop) # 针对当前循环应用补丁
                self.loop = loop  # 存储当前活动循环
                self.ib = IB()
                
                last_reconnect_time = 0
                last_scan_bar = self.get_us_now() - timedelta(minutes=60)
                last_heartbeat_min = -1
                _is_connecting = False
                
                while self._is_running:
                    # 1. 优先级 A: GUI 指令队列 (绝对非阻塞，且每次循环必跑)
                    while not self.cmd_queue.empty():
                        try:
                            cmd_type, data = self.cmd_queue.get_nowait()
                            self.log_message.emit(f"📥 [指令] 正在执行: {cmd_type}")
                            self._handle_gui_command(cmd_type, data)
                        except Exception as ce:
                            self.log_message.emit(f"⚠️ [指令] 响应失败: {ce}")

                    if self._is_paused:
                        self.log_message.emit("⏸️ [美股] 监控暂停中...")
                        time.sleep(1.0)
                        continue

                    # 2. 优先级 B: 连接维护 (非阻塞触发)
                    if not self.ib.isConnected():
                        now_ts = time.time()
                        if not _is_connecting and now_ts - last_reconnect_time > 15:
                            last_reconnect_time = now_ts
                            _is_connecting = True
                            self.log_message.emit(f"🔄 [美股] 发起后台连接请求 ({self.host}:{self.port})...")
                            loop.create_task(self.ib.connectAsync(self.host, self.port, clientId=self.client_id, timeout=10))
                        
                        try:
                            loop.run_until_complete(asyncio.sleep(0.2))
                        except Exception as e:
                            if "closed" in str(e).lower(): break
                            
                        if self.ib.isConnected():
                            self.log_message.emit("🔌 [美股] IB 连接成功，同步实时数据流")
                            self.ib.reqAccountUpdates(True)
                            _is_connecting = False
                        continue

                    # 3. 优先级 C: 正常交易驱动
                    try:
                        self.ib.sleep(0.5) # 驱动 asyncio 心跳 (加大间隔减少压力)
                    except Exception as e:
                        self.log_message.emit(f"⚠️ [驱动] 循环异常: {e}")
                        if "closed" in str(e).lower(): 
                            break # 跳出内循环
                        time.sleep(1.0)
                        continue

                    # 交易逻辑
                    now_et = self.get_us_now()
                    if now_et.minute != last_heartbeat_min:
                        if self.is_trading_time():
                            self.log_message.emit(f"💖 监控心跳 (NY: {now_et.strftime('%H:%M')})")
                        else:
                            self.log_message.emit(f"💤 非交易时段 (NY: {now_et.strftime('%H:%M')})")
                        last_heartbeat_min = now_et.minute

                    if not self.is_trading_time():
                        time.sleep(1.0) # 非交易时段增加休眠，防止 CPU 占用
                        continue

                    # 周期扫描
                    current_bar_et = now_et.replace(minute=(now_et.minute // 30) * 30, second=0, microsecond=0)
                    if current_bar_et > last_scan_bar:
                        if now_et.minute % 30 >= 2:
                            self.log_message.emit(f"⚡ [美股] 触发周期扫描")
                            try:
                                self._perform_strategy_scan()
                            except Exception as e:
                                self.log_message.emit(f"❌ [美股] 扫描中断: {e}")
                                if "closed" in str(e).lower(): break
                            last_scan_bar = current_bar_et

            except Exception as outer_e:
                print(f"[CRITICAL] US Thread Inner Crash: {outer_e}")
                self.log_message.emit(f"🚨 [美股] 运行环境异常，5秒后重启: {outer_e}")
                if not self._is_running: break
                time.sleep(5)
            finally:
                if self.ib:
                    try: self.ib.disconnect()
                    except: pass
                if loop and not loop.is_closed():
                    try: loop.close()
                    except: pass
                if hasattr(self, 'loop') and self.loop == loop:
                    self.loop = None
                    
        self.log_message.emit("🛑 [美股] 交易驱动线程已正常终止")
        print("[DEBUG] US Trading Thread EXIT.")


    def _handle_gui_command(self, cmd_type, data):
        """处理来自 GUI 的指令 (在 IB 线程执行)"""
        try:
            self.log_message.emit(f"⚙️ [美股] 正在处理内部指令: {cmd_type}")
            if cmd_type == 'FORCE_SCAN':
                self._perform_strategy_scan()
            elif cmd_type == 'QUERY_FUNDS':
                self.log_message.emit("💰 [美股] 正在向 IB 请求资金与持仓数据...")
                available, total, positions = self.get_account_assets()
                self.funds_updated.emit(available, total, positions)
                self.log_message.emit("✅ [美股] 资金查询完成")
            elif cmd_type == 'CLOSE_ALL':
                self.log_message.emit("🔥 [美股] 正在执行全账户清仓...")
                self._close_all_positions()
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
        """执行策略扫描 (自选股源自富途，数据源和执行源自 IB)"""
        self.log_message.emit(f"🔍 [美股] 正在从自选股分组 '{self.watchlist_group}' 获取代码...")
        us_codes_set = set()
        
        try:
            # 1. 从富途获取自选股清单 (用户偏好源)
            from futu import OpenQuoteContext, RET_OK
            try:
                # 建立瞬时连接，用完即关
                ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
                ret, data = ctx.get_user_security(group_name=self.watchlist_group)
                ctx.close()
                if ret == RET_OK and not data.empty:
                    futu_codes = [c for c in data['code'].tolist() if c.startswith("US.")]
                    us_codes_set.update(futu_codes)
                    self.log_message.emit(f"✅ [美股] 从富途获取了 {len(futu_codes)} 只自选股")
            except Exception as fe:
                self.log_message.emit(f"⚠️ [美股] 富途自选股获取异常: {fe}")

            # 2. 强制合并 IB 实际持仓 (确保监控已有头寸)
            if self.ib and self.ib.isConnected():
                try:
                    positions = self.ib.positions()
                    if positions:
                        ib_pos_codes = [f"US.{p.contract.symbol}" for p in positions if p.contract.secType == 'STK']
                        us_codes_set.update(ib_pos_codes)
                        self.log_message.emit(f"🔌 [美股] 已自动关联 {len(ib_pos_codes)} 只 IB 持仓股票进入监控")
                except Exception as ie:
                    self.log_message.emit(f"⚠️ [美股] IB 持仓同步异常: {ie}")
            
            # 3. 如果依然为空，执行 Config 兜底
            if not us_codes_set:
                import yaml
                cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Config", "database_config.yaml")
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        cfg = yaml.safe_load(f)
                        us_codes_set.update(cfg.get('default_stocks', {}).get('us', []))
                
                if not us_codes_set:
                    us_codes_set.update(['US.AAPL', 'US.TSLA', 'US.NVDA', 'US.MSFT', 'US.AMZN', 'US.GOOG', 'US.META'])
                self.log_message.emit(f"📋 [美股] 使用兜底清单共 {len(us_codes_set)} 只股票")

            us_codes = sorted(list(us_codes_set))
            self.log_message.emit(f"📡 [美股] 扫描队列就绪 (共 {len(us_codes)} 只)，开始分析...")
            
            for i, code in enumerate(us_codes):
                if not self._is_running: break
                
                # 检查事件循环状态，如果已关闭则抛出异常以触发外层重启
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise Exception("Event loop is closed during scan")
                try:
                    self._analyze_stock(code, i + 1, len(us_codes))
                    self.ib.sleep(0.1)
                except Exception as e:
                    self.log_message.emit(f"❌ [美股] 分析 {code} 报错: {e}")
                    if "closed" in str(e).lower():
                        raise e
            
            self.log_message.emit("✅ [美股] 本轮策略扫描完成.")
        except asyncio.CancelledError:
            self.log_message.emit("⚠️ [美股] 扫描任务被取消")
            raise
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 扫描过程异常: {e}")
            if "closed" in str(e).lower() or "loop" in str(e).lower():
                raise

    def _analyze_stock(self, code: str, index: int = 0, total: int = 0):
        """分析单只股票"""
        try:
            prefix = f"[{index}/{total}] " if total > 0 else ""
            self.log_message.emit(f"⏳ {prefix}正在获取 {code} 历史数据...")
            
            symbol = code.split(".")[1] if "." in code else code
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            bars = self.ib.reqHistoricalData(
                contract, endDateTime='', durationStr='90 D',
                barSizeSetting='30 mins', whatToShow='TRADES', useRTH=True
            )
            
            if not bars:
                self.log_message.emit(f"ℹ️ {prefix}{code} 未能获取历史数据，跳过")
                return
            
            self.log_message.emit(f"📊 {prefix}{code} 数据获取成功 ({len(bars)} 根K线)，执行缠论分析...")

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

                    # 捕获当前环境状态（持仓、挂单等），确保线程池任务有最新的基准数据
                    # 避免在子线程中直接访问非线程安全的 IB 对象
                    pos_qty = self.get_position_quantity(code)
                    has_pending = self.check_pending_orders(code, 'BUY' if bsp.is_buy else 'SELL')
                    
                    try:
                        all_pos = self.ib.positions()
                        current_total_pos = len(set([p.contract.symbol for p in all_pos if p.contract.secType == 'STK']))
                    except:
                        current_total_pos = 0

                    # 将后续耗时的验证、绘图、AI评分、下单逻辑移至线程池执行
                    self.executor.submit(self._handle_signal_sync, code, bsp, chan_30m, chan_5m, 
                                        pos_qty=pos_qty, has_pending=has_pending, current_total_pos=current_total_pos)
            
            if not found_any and bsp_list:
                 logger.debug(f"{code} no new signal, latest at {bsp_list[-1].klu.time}")

        except Exception as e:
            logger.error(f"Analysis error {code}: {e}")
            if "closed" in str(e).lower():
                raise e

    def _handle_signal_sync(self, code: str, bsp, chan_30m, chan_5m=None, 
                           pos_qty: int = 0, has_pending: bool = False, current_total_pos: int = 0):
        """处理信号的同步入口（在线程池中运行）"""
        try:
            is_buy = bsp.is_buy
            bsp_type = bsp.type2str()
            bsp_display = f"{'b' if is_buy else 's'}{bsp_type}"
            
            if is_buy:
                # 1. 持仓上限校验 (使用预捕获的状态)
                max_positions = TRADING_CONFIG.get('max_total_positions', 10)
                if current_total_pos >= max_positions and pos_qty <= 0:
                    self.log_message.emit(f"⏭️ [美股] 已达最大持仓上限({max_positions})，跳过 {code} 买入信号")
                    return

                # 2. 个股已有持仓校验
                if pos_qty > 0:
                    self.log_message.emit(f"⏭️ [美股] {code} {bsp_display} 已有持仓({pos_qty})，跳过买入信号")
                    return
            else:
                # 卖出信号：若无持仓，则跳过
                if pos_qty <= 0:
                    self.log_message.emit(f"⏭️ [美股] {code} {bsp_display} 无持仓，跳过卖出信号")
                    return

            # 3. 挂单校验 (使用预捕获的状态)
            if has_pending:
                self.log_message.emit(f"⏭️ [美股] {code} {bsp_display} 已有相同方向挂单，跳过")
                return

        # 4. ML 验证 (Phase 4: Buy/Sell 均获取评分，但 Sell 不拦截)
        ml_res = self.ml_validator.validate_signal(chan_30m, bsp)
        ml_valid = ml_res.get('is_valid', True)
        ml_prob = ml_res.get('prob', 0)
        ml_msg = ml_res.get('msg', 'N/A')
        
        self.log_message.emit(f"🤖 [美股] {code} ML 评分: {ml_prob*100:.1f}%, 验证: {'✅ 通过' if ml_valid else '❌ 拦截'}, 原因: {ml_msg}")
        
        if not ml_valid:
            return

        # 5. 生成图表并进行视觉评分
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
            msg = f"🗽 **美股自动化预警**\n股票: {code}\n信号: {bsp.type2str()}\n评分: **{score}分**\nML概率: {ml_prob*100:.1f}%"
            # 发送到 Discord (确保 Discord 机器人的事件循环依然存活)
            if self.discord_bot.loop and self.discord_bot.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.discord_bot.send_notification(msg, path_30m), self.discord_bot.loop)
            else:
                self.log_message.emit("⚠️ [美股] Discord 机器人循环未运行，无法发送通知")

        if score >= self.min_visual_score:
            if self.dry_run:
                self.log_message.emit(f"📝 [美股-模拟] {code} 满足条件({score}分)，跳过实盘下单")
            else:
                self._execute_trade(code, "BUY" if bsp.is_buy else "SELL", bsp.klu.close)
        else:
            self.log_message.emit(f"⏭️ [美股] {code} 评分({score}) 低于阈值({self.min_visual_score})，跳过")

    def _handle_signal(self, code: str, bsp, chan_30m, chan_5m=None):
        """兼容性别名"""
        self.executor.submit(self._handle_signal_sync, code, bsp, chan_30m, chan_5m)

    def get_account_assets(self) -> Tuple[float, float, list]:
        """获取资金和持仓信息 (增加日志与超时预防)"""
        if self.ib is None or not self.ib.isConnected(): return 0.0, 0.0, []
        try:
            available = 0.0
            total = 0.0
            
            # 1. 优先从 accountValues 提取 (最快且不产生网络请求)
            vals = self.ib.accountValues()
            for v in vals:
                if v.tag == 'AvailableFunds' and (v.currency == 'USD' or v.currency == ''):
                    available = float(v.value)
                if v.tag == 'NetLiquidation' and (v.currency == 'USD' or v.currency == ''):
                    total = float(v.value)
            
            # 2. 如果数据未就绪，使用 accountSummary (可能会产生的网络往返)
            if total == 0:
                self.log_message.emit("⏳ [美股] 即时数据未就绪，尝试请求账户摘要 (AccountSummary)...")
                summary = self.ib.accountSummary()
                for item in summary:
                    if item.tag == 'AvailableFunds': available = float(item.value)
                    elif item.tag == 'NetLiquidation': total = float(item.value)
            
            # 3. 获取持仓 (使用 Portfolio 获取包含市值的最新视图)
            positions_data = []
            portfolio = self.ib.portfolio()
            for item in portfolio:
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
            self.log_message.emit(f"❌ [美股] 资金查询异常: {e}")
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

    def close_all_positions(self):
        """一键清仓所有美股持仓"""
        if self.ib is None or not self.ib.isConnected():
            self.log_message.emit("⚠️ [美股] IB 未连接，无法清仓")
            return
            
        try:
            positions = self.ib.positions()
            if not positions:
                self.log_message.emit("ℹ️ [美股] 当前无持仓，无需清仓")
                return
                
            self.log_message.emit(f"🔥 [美股] 开始清仓 {len(positions)} 个持仓...")
            for p in positions:
                contract = p.contract
                qty = int(p.position)
                if qty == 0: continue
                
                action = "SELL" if qty > 0 else "BUY"
                abs_qty = abs(qty)
                
                order = MarketOrder(action, abs_qty)
                self.ib.placeOrder(contract, order)
                self.log_message.emit(f"🚀 [美股] 已提交清仓订单: {contract.symbol} {action} {abs_qty}")
                
            self.log_message.emit("✅ [美股] 所有清仓订单已提交")
        except Exception as e:
            self.log_message.emit(f"❌ [美股] 清仓操作失败: {e}")
