#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股自动化交易控制器 (Phase 5 重构版)

以 USTradingController 的 asyncio 架构为模板，重构 A 股 MonitorController，
实现异步非阻塞的扫描、风控、下单、收盘处理全流程。

核心改进:
1. asyncio 事件循环驱动 → 彻底消除单线程串行阻塞
2. 指令队列 (queue.Queue) → GUI 线程安全
3. asyncio.Semaphore 并发限流 → 防止 Futu API 频率封控
4. ATR 移动追踪止损 → 补齐 A 股风控短板
5. 集中式交易时间校验 → 非盘中绝对不下单
"""

import os
import sys
import time
import json
import logging
import threading
import asyncio
import traceback
import queue
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, pyqtSignal

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TRADING_CONFIG, CHAN_CONFIG, CHART_CONFIG, CHART_PARA
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC, AUTYPE
from Plot.PlotDriver import CPlotDriver
from App.ScannerThreads import LEVEL_DATA_DAYS
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 导入 Futu
from futu import OpenQuoteContext, OpenSecTradeContext, RET_OK, TrdMarket, TrdEnv, TrdSide, OrderType, RET_ERROR

# 导入 DiscordBot (复用现有逻辑)
from App.DiscordBot import DiscordBot

# 导入 机器学习验证器
from ML.SignalValidator import SignalValidator
# 导入 视觉评分器
from visual_judge import VisualJudge
from Trade.db_util import CChanDB


logger = logging.getLogger(__name__)


class MarketMonitorController(QObject):
    """
    A股自动化交易控制器 (asyncio 版)
    """
    log_message = pyqtSignal(str)
    funds_updated = pyqtSignal(float, float, list)  # available, total, positions

    def __init__(self, watchlist_group: str, discord_bot: DiscordBot = None, parent=None):
        super().__init__(parent)
        self.watchlist_group = watchlist_group
        self._is_running = False
        self._is_paused = False
        self.quote_ctx = None
        self.trd_ctx = None
        self.trd_env = TrdEnv.SIMULATE
        self.trading_enabled = False  # 默认只监控，不交易
        self.discord_bot = discord_bot

        # 指令队列，用于处理 GUI 线程发来的请求 (线程安全)
        self.cmd_queue = queue.Queue()

        # 创建图表临时存放目录
        self.charts_dir = "charts_monitor"
        os.makedirs(self.charts_dir, exist_ok=True)

        # 信号历史记录，用于去重
        self.notified_signals_file = "monitor_notified_signals.json"
        self.notified_signals = self._load_notified_signals()

        # 实例化工具组件
        self.signal_validator = SignalValidator()
        self.visual_judge = VisualJudge()
        self.db = CChanDB()
        self.discord_bot = discord_bot or None

        # 图表生成锁，防止多线程 matplotlib 状态泄漏
        self.chart_generation_lock = threading.Lock()

        # 线程池：用于执行耗时的 绘图 + 缠论分析 任务
        self.executor = ThreadPoolExecutor(max_workers=6)

        # 并发限流信号量 (控制同时请求 Futu API 和视觉 AI 的数量)
        self.scan_semaphore = asyncio.Semaphore(3)

        self._force_scan = False      # 强制扫描标志
        self._current_bar_scanned = True  # 启动时不触发补偿扫描，等待下一个30M周期
        self._last_close_date = None  # 收盘运行标记

        # ATR 移动追踪止损器
        self.position_trackers = self.db.get_all_stop_loss_trackers() if hasattr(self, 'db') else {}
        if self.position_trackers:
            # self.log_message.emit(f"🔄 [A股-风控] 从数据库载入并初始化 {len(self.position_trackers)} 只持仓的止损锚点。")
            for c, t in self.position_trackers.items():
                self.log_message.emit(f"🛡️ {c} 已加载移动止损监控: 现价={t['entry_price']:.3f}, ATR={t['atr']:.3f}")
        
        # 🛡️ [风控加固] 结构锁区字典，防止在同一个下行笔延续段多次重复下单
        self.structure_barrier = {}

        # 视觉/AI 评分缓存 {cache_key: {"score", "analysis"}}
        self.visual_score_cache = {}

    # ============================= 交易时间判定 =============================

    def is_trading_time(self) -> bool:
        """
        检查当前是否在 A股 交易时间内。
        上午：09:30 - 11:30
        下午：13:00 - 15:00
        周六日不交易。
        """
        now = datetime.now()
        if now.weekday() >= 5:
            return False

        current_time = now.time()
        morning_start = datetime.strptime("09:30", "%H:%M").time()
        morning_end = datetime.strptime("11:30", "%H:%M").time()
        afternoon_start = datetime.strptime("13:00", "%H:%M").time()
        afternoon_end = datetime.strptime("15:00", "%H:%M").time()

        if morning_start <= current_time <= morning_end:
            return True
        if afternoon_start <= current_time <= afternoon_end:
            return True

        return False

    # ============================= 信号去重持久化 =============================

    def _load_notified_signals(self) -> Dict:
        if os.path.exists(self.notified_signals_file):
            try:
                with open(self.notified_signals_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 清理超过 24 小时的旧记录
                cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
                return {k: v for k, v in data.items() if v >= cutoff}
            except Exception as e:
                logger.error(f"加载监控信号记录失败: {e}")
        return {}

    def _save_notified_signals(self):
        try:
            cutoff = datetime.now() - timedelta(days=3)
            cleaned = {}
            for k, v in self.notified_signals.items():
                try:
                    t = datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
                    if t > cutoff:
                        cleaned[k] = v
                except:
                    cleaned[k] = v
            self.notified_signals = cleaned
            with open(self.notified_signals_file, 'w', encoding='utf-8') as f:
                json.dump(self.notified_signals, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存监控信号记录失败: {e}")

    # ============================= 基础设施初始化 =============================

    def _init_futu(self):
        if self.quote_ctx is None:
            futu_config = TRADING_CONFIG.get('futu', {})
            host = futu_config.get('host', '127.0.0.1')
            port = futu_config.get('port', 11111)
            self.quote_ctx = OpenQuoteContext(host=host, port=port)
            self.log_message.emit(f"🔌 [A股] 已连接富途行情接口 ({host}:{port})")

    def _init_trd_ctx(self):
        if self.trd_ctx is None:
            futu_config = TRADING_CONFIG.get('futu', {})
            host = futu_config.get('host', '127.0.0.1')
            port = futu_config.get('port', 11111)
            self.trd_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.CN, host=host, port=port)
            self.log_message.emit(f"💰 [A股] 交易接口已就绪 (环境: {'模拟' if self.trd_env == TrdEnv.SIMULATE else '实盘'})")

    def _init_discord(self):
        if self.discord_bot is None and TRADING_CONFIG.get('discord') and TRADING_CONFIG['discord'].get('token'):
            try:
                self.discord_bot = DiscordBot(
                    token=TRADING_CONFIG['discord']['token'],
                    channel_id=TRADING_CONFIG['discord']['channel_id'],
                    allowed_user_ids=TRADING_CONFIG['discord']['allowed_user_ids'],
                    controller=None
                )
                self.discord_bot.start()
                self.log_message.emit("🤖 [A股] Discord 推送已就绪")
            except Exception as e:
                self.log_message.emit(f"⚠️ [A股] Discord 启动失败: {e}")
        elif self.discord_bot:
            self.log_message.emit("🤖 [A股] 已关联现有 Discord 推送服务")

    # ============================= GUI 指令接口 =============================

    def stop(self):
        self._is_running = False
        if self.quote_ctx:
            self.quote_ctx.close()
            self.quote_ctx = None
        if self.trd_ctx:
            self.trd_ctx.close()
            self.trd_ctx = None
        self.log_message.emit("🛑 [A股] 监控与交易进程已停止")

    def force_scan(self):
        self.cmd_queue.put(('FORCE_SCAN', None))
        self.log_message.emit("⚡ [A股] 已加入强制扫描队列")

    def query_account_funds(self):
        self.cmd_queue.put(('QUERY_FUNDS', None))

    def close_all_positions(self):
        self.cmd_queue.put(('CLOSE_ALL', None))

    def get_status_summary(self) -> str:
        run_status = "🟢 正在运行" if self._is_running else "🛑 已停止"
        tracker_count = len(self.position_trackers)
        return (
            f"🔍 **A股交易状态摘要**\n"
            f"----------------------------------\n"
            f"▸ 监控状态: {run_status}\n"
            f"▸ 监控分组: `{self.watchlist_group}`\n"
            f"▸ 移动止损追踪: {tracker_count} 只\n"
            f"▸ 交易时间: {'⏰ 盘中' if self.is_trading_time() else '💤 休市'}\n"
            f"▸ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    # ============================= 数据获取 =============================

    def get_watchlist_data(self) -> Dict[str, str]:
        if not self.quote_ctx:
            self._init_futu()

        group = self.watchlist_group if self.watchlist_group not in ["全部", "All", ""] else ""
        ret, data = self.quote_ctx.get_user_security(group_name=group)
        if ret == RET_OK:
            name_col = 'name' if 'name' in data.columns else 'stock_name'
            return dict(zip(data['code'].tolist(), data[name_col].tolist()))
        else:
            self.log_message.emit(f"❌ [A股] 获取分组 {self.watchlist_group} 失败: {data}")
            return {}

    # ============================= 交易执行 =============================

    def execute_trade(self, code: str, action: str, price: float, qty: int = 0, **kwargs):
        """执行A股下单 (带交易时间保护)"""
        # 核心时间锁
        if not self.is_trading_time():
            self.log_message.emit(f"⏳ [A股] {code} 触发交易指令 {action}，但当前非交易时间，已拦截。")
            return

        if not self.trading_enabled:
            return
        self._init_trd_ctx()

        try:
            # --- 动态仓位计算 (对齐港股 risk_manager 模型) ---
            if action.upper() == "BUY" and qty <= 0:
                # 查询账户可用资金
                ret_acct, acct_data = self.trd_ctx.accinfo_query(trd_env=self.trd_env)
                available = float(acct_data.iloc[0]['cash']) if ret_acct == RET_OK and not acct_data.empty else 0
                
                if available < 5000:
                    self.log_message.emit(f"💰 [A股-交易] 可用资金({available:.0f})不足5000元，跳过买入")
                    return
                
                # 单笔最大使用可用资金的 20%
                max_position_value = available * 0.20
                
                # 用 ATR 限制风险: 单笔最大亏损 = 总资产的 2%
                atr = self._calculate_atr(code)
                if atr > 0 and price > 0:
                    total_assets = float(acct_data.iloc[0].get('total_assets', available))
                    risk_per_trade = total_assets * 0.02  # 每笔最多亏 2%
                    atr_limited_qty = int(risk_per_trade / (atr * 1.2))  # 1.2 ATR止损
                    fund_limited_qty = int(max_position_value / price)
                    qty = min(atr_limited_qty, fund_limited_qty)
                    self.log_message.emit(f"📊 [A股-交易] {code} 动态仓位: ATR限={atr_limited_qty}, 资金限={fund_limited_qty} -> 取{qty}股")
                else:
                    qty = int(max_position_value / price) if price > 0 else 100
                    self.log_message.emit(f"📊 [A股-交易] {code} 固定20%仓位: {qty}股")
            elif qty <= 0:
                qty = 100  # 卖出默认回退

            # A股最小手数 100 股对齐
            qty = (qty // 100) * 100
            if qty <= 0:
                self.log_message.emit(f"⚠️ [A股-交易] {code} 数量不足 100 股，跳过")
                return

            side = TrdSide.BUY if action.upper() == "BUY" else TrdSide.SELL
            limit_price = round(price * 1.01, 2) if action.upper() == "BUY" else round(price * 0.99, 2)

            self.log_message.emit(f"🚀 [A股-交易] 正在提交订单: {code} {action} {qty}股 @ {limit_price}")

            ret, data = self.trd_ctx.place_order(
                price=limit_price,
                qty=qty,
                code=code,
                trd_side=side,
                order_type=OrderType.NORMAL,
                trd_env=self.trd_env
            )

            if ret == RET_OK:
                order_id = data.iloc[0]['order_id']
                self.log_message.emit(f"✅ [A股-交易] 订单提交成功! ID: {order_id}")

                # 记录实盘数据库 (优化F)
                try:
                    if action.upper() == "BUY":
                        trade_data = {
                            'code': code,
                            'name': kwargs.get('name', 'A股股票'),
                            'market': 'CN',
                            'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'entry_price': limit_price,
                            'quantity': qty,
                            'signal_type': kwargs.get('signal_type', '未知'),
                            'ml_prob': kwargs.get('ml_prob', 0),
                            'visual_score': kwargs.get('visual_score', 0),
                            'status': 'open'
                        }
                        self.db.record_live_trade(trade_data)
                    else:
                        # 卖出记录 (更新对应的开仓订单)
                        exit_reason = kwargs.get('exit_reason', '信号卖出')
                        self.db.close_live_trade(code, limit_price, exit_reason)
                except Exception as e:
                    logger.error(f"[A股-DB] 记录交易失败: {e}")

                # 买入成功后初始化止损追踪器
                if action.upper() == "BUY":
                    atr = self._calculate_atr(code)
                    if atr > 0:
                        self.position_trackers[code] = {
                            'entry_price': limit_price,
                            'highest_price': limit_price,
                            'atr': atr,
                            'trail_active': False,
                            'signal_type': kwargs.get('signal_type', '未知') # 🛡️ 保留买点类别用于分档止损
                        }
                        self.db.save_stop_loss_tracker(code, limit_price, limit_price, atr, 0)  # 🛡️ 辅助持久化
                        self.log_message.emit(f"🛡️ [A股-风控] {code} 已初始化 ATR 止损追踪 (ATR={atr:.4f})")

                # 启动异步订单跟踪
                self.cmd_queue.put(('TRACK_ORDER', {'order_id': order_id, 'code': code, 'action': action, 'qty': qty, 'price': limit_price}))

            else:
                self.log_message.emit(f"❌ [A股-交易] 下单失败: {data}")

        except Exception as e:
            self.log_message.emit(f"❌ [A股-交易] 下单异常: {e}")

    def _track_order_status(self, order_id: str, code: str, action: str, qty: int, price: float):
        """轮询订单成交状态，汇报执行情况"""
        from futu import OrderStatus
        import time as _time

        status_map = {
            OrderStatus.SUBMITTED: "已提交",
            OrderStatus.FILLED_ALL: "全部成交 ✅",
            OrderStatus.FILLED_PART: "部分成交",
            OrderStatus.CANCELLED_ALL: "已撤单",
            OrderStatus.CANCELLED_PART: "部分撤单",
            OrderStatus.FAILED: "失败 ❌",
        }

        for attempt in range(12):  # 最多轮询 60 秒
            _time.sleep(5)
            try:
                ret, data = self.trd_ctx.order_list_query(
                    order_id=order_id, trd_env=self.trd_env
                )
                if ret != RET_OK or data.empty:
                    continue

                row = data.iloc[0]
                status = row.get('order_status', '')
                filled_qty = int(row.get('dealt_qty', 0))
                filled_avg = float(row.get('dealt_avg_price', 0))

                status_str = status_map.get(status, str(status))

                if status in (OrderStatus.FILLED_ALL,):
                    self.log_message.emit(
                        f"📋 [A股-成交] {code} {action} 订单 {status_str}: "
                        f"{filled_qty}股 @ ¥{filled_avg:.2f}"
                    )
                    # Discord 推送成交通知
                    if self.discord_bot:
                        msg = (
                            f"📋 **A股订单成交**\n"
                            f"股票: {code}\n"
                            f"方向: {action}\n"
                            f"成交: {filled_qty}股 @ ¥{filled_avg:.2f}\n"
                            f"时间: {datetime.now().strftime('%H:%M:%S')}"
                        )
                        if hasattr(self.discord_bot, 'loop') and self.discord_bot.loop and self.discord_bot.loop.is_running():
                            asyncio.run_coroutine_threadsafe(
                                self.discord_bot.send_notification(msg), self.discord_bot.loop
                            )
                    return

                if status in (OrderStatus.CANCELLED_ALL, OrderStatus.CANCELLED_PART, OrderStatus.FAILED):
                    self.log_message.emit(
                        f"📋 [A股-订单] {code} {action} {status_str} "
                        f"(已成交: {filled_qty}/{qty}股)"
                    )
                    return

                if status == OrderStatus.FILLED_PART:
                    self.log_message.emit(
                        f"⏳ [A股-订单] {code} {action} 部分成交中: {filled_qty}/{qty}股 @ ¥{filled_avg:.2f}"
                    )

            except Exception as e:
                logger.error(f"订单跟踪异常: {e}")

        # 超时仍未完全成交
        self.log_message.emit(f"⏰ [A股-订单] {code} {action} 60秒内未完全成交，请手动检查订单 {order_id}")

    def _calculate_atr(self, code: str, period: int = 14) -> float:
        """计算 ATR (Average True Range) 用于止损"""
        try:
            from futu import KLType, AuType
            ret, klines, _ = self.quote_ctx.request_history_kline(
                code, start=None, end=None, ktype=KLType.K_DAY,
                autype=AuType.QFQ, max_count=period + 5
            )
            if ret != RET_OK or klines.empty or len(klines) < period:
                self.log_message.emit(f"⚠️ [A股-ATR] {code} 日线拉取失败: ret={ret}, empty={(klines.empty if not klines.empty else 'True') if 'klines' in locals() else 'Unknown'}, len={len(klines) if 'klines' in locals() else 0}")
                return 0.0

            tr_list = []
            for i in range(1, len(klines)):
                high = float(klines.iloc[i]['high'])
                low = float(klines.iloc[i]['low'])
                prev_close = float(klines.iloc[i - 1]['close'])
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                tr_list.append(tr)

            if len(tr_list) < period:
                return sum(tr_list) / len(tr_list) if tr_list else 0.0
            return sum(tr_list[-period:]) / period
        except Exception as e:
            logger.error(f"ATR 计算失败 {code}: {e}")
            return 0.0

    # ============================= 资金与持仓查询 =============================

    def _do_query_funds(self):
        if not getattr(self, 'trading_enabled', False):
            return
        self._init_trd_ctx()
        try:
            ret, data = self.trd_ctx.accinfo_query(trd_env=self.trd_env)
            available, total = 0.0, 0.0
            if ret == RET_OK:
                available = float(data.iloc[0]['cash'])
                total = float(data.iloc[0].get('total_assets', data.iloc[0].get('power', 0.0)))

            positions = []
            ret_pos, pos_data = self.trd_ctx.position_list_query(trd_env=self.trd_env)
            if ret_pos == RET_OK and not pos_data.empty:
                for _, row in pos_data.iterrows():
                    qty = int(row['qty'])
                    if qty == 0:
                        continue
                    positions.append({
                        'symbol': row['code'],
                        'qty': qty,
                        'mkt_value': float(row['market_val']),
                        'avg_cost': float(row['cost_price']),
                        'mkt_price': float(row['nominal_price']),
                        'can_sell_qty': int(row.get('can_sell_qty', qty))
                    })

            self.funds_updated.emit(available, total, positions)
        except Exception as e:
            self.log_message.emit(f"⚠️ [A股-交易] 资产查询失败: {e}")

    def _do_liquidate(self):
        if not getattr(self, 'trading_enabled', False):
            return
        self._init_trd_ctx()
        self.log_message.emit("🔥 [A股-交易] 正在尝试清空所有可卖持仓...")

        try:
            ret, data = self.trd_ctx.position_list_query(trd_env=self.trd_env)
            if ret == RET_OK and not data.empty:
                count = 0
                for _, row in data.iterrows():
                    qty = int(row.get('can_sell_qty', 0))
                    if qty <= 0:
                        continue
                    code = row['code']
                    self.execute_trade(code, "SELL", float(row['nominal_price']), qty=qty)
                    count += 1
                self.log_message.emit(f"✅ [A股-交易] 已下达 {count} 个清仓卖单 (T+1受限部分除外)")
            else:
                self.log_message.emit("📊 [A股-交易] 当前无持仓可卖。")
        except Exception as e:
            self.log_message.emit(f"❌ [A股-交易] 清仓操作异常: {e}")

    # ============================= ATR 移动止损监控 =============================

    def _check_trailing_stops(self):
        """
        检查所有持仓是否触发移动止损 (方案丙对齐 HK/US)
        """
        if not self.position_trackers:
            return

        # 查询当前实际持仓
        self._init_trd_ctx()
        try:
            ret, pos_data = self.trd_ctx.position_list_query(trd_env=self.trd_env)
            current_positions = {}
            if ret == RET_OK and not pos_data.empty:
                for _, row in pos_data.iterrows():
                    qty = int(row['qty'])
                    if qty > 0:
                        current_positions[row['code']] = {
                            'qty': qty,
                            'price': float(row['nominal_price']),
                            'can_sell_qty': int(row.get('can_sell_qty', qty))
                        }
        except Exception as e:
            logger.error(f"止损检查: 持仓查询失败: {e}")
            return

        for code in list(self.position_trackers.keys()):
            if code not in current_positions:
                self.log_message.emit(f"🔄 [A股-风控] {code} 已无持仓，停止止损追踪")
                del self.position_trackers[code]
                self.db.delete_stop_loss_tracker(code) # 清除持久化
                continue

            pos = current_positions[code]
            current_price = pos['price']
            can_sell = pos['can_sell_qty']
            tracker = self.position_trackers[code]

            # 更新最高价
            if current_price > tracker['highest_price']:
                tracker['highest_price'] = current_price
                self.log_message.emit(f"📈 [A股-风控] {code} 创持仓新高: {current_price:.2f}")

            entry_price = tracker.get('entry_price', current_price)
            highest = tracker['highest_price']
            atr = tracker['atr']

            # 🛡️ [风控加固 Phase 8] 分档式动态 ATR 止损锚定
            bsp_type_str = tracker.get('signal_type', '未知')
            atr_init = TRADING_CONFIG.get('atr_stop_init', 1.2)
            if "1买" in bsp_type_str:
                atr_init = 1.5 # 1买属于左侧信号，止损放大至 1.5x 防针穿
            elif "2买" in bsp_type_str or "3买" in bsp_type_str:
                atr_init = 1.2 # 2/3买右侧确认，严格控损 1.2x

            atr_trail = TRADING_CONFIG.get('atr_stop_trail', 2.5)
            atr_profit = TRADING_CONFIG.get('atr_profit_threshold', 1.5)

            # 触发移动止损
            if not tracker.get('trail_active', False):
                if (current_price - entry_price) >= (atr * atr_profit):
                    tracker['trail_active'] = True
                    self.log_message.emit(f"🔓 [A股-风控] {code} 已达获利门槛(+{atr_profit}*ATR)，切换为移动止损模式")

            if tracker.get('trail_active', False):
                stop_price = highest - (atr * atr_trail)
                stop_type = "移动止损"
            else:
                stop_price = entry_price - (atr * atr_init)
                stop_type = "固定止损"

            # 触发则立刻下平仓单 (受 T+1 限制，只卖可卖数量)
            if current_price < stop_price:
                self.log_message.emit(
                    f"🚨 [A股-风控] {code} 触发{stop_type}! "
                    f"最高价={highest:.2f}, 现价={current_price:.2f}, 止损位={stop_price:.2f}"
                )
                
                # 🛡️ 触发后根据交易开关决定是否实际下单
                if not getattr(self, 'trading_enabled', False):
                    self.log_message.emit(f"⚠️ [A股-风控] {code} 满足平仓，但“开启交易”未勾选，仅报警。")
                elif can_sell > 0:
                    self.execute_trade(code, "SELL", current_price, qty=can_sell, exit_reason=stop_type)
                    del self.position_trackers[code]
                    self.db.delete_stop_loss_tracker(code) # 清除持久化
                    
                    # 🛡️ [风控加固 Phase 8] 录入锁区锚点：记录锁区触发时的 CTime 戳记
                    from Common.CTime import CTime
                    if code not in getattr(self, 'structure_barrier', {}):
                        from datetime import datetime
                        now = datetime.now()
                        self.structure_barrier[code] = {
                            'lock_time_ts': CTime(now.year, now.month, now.day, now.hour, now.minute).ts
                        }
                        self.log_message.emit(f"🛡️ [A股-风控] {code} 止损出局，锁入结构防护舱，直到生成新中枢为止。")
                else:
                    self.log_message.emit(f"⚠️ [A股-风控] {code} T+1 限制，当日买入不可卖出，下一交易日将继续监控。")
                    
            # 🔄 同步更新最高价与移动止损状态到数据库
            if code in self.position_trackers:
                tracker = self.position_trackers[code]
                self.db.save_stop_loss_tracker(
                    code, tracker['entry_price'], tracker['highest_price'], 
                    tracker['atr'], 1 if tracker.get('trail_active', False) else 0
                )

    # ============================= 收盘处理 =============================

    def on_market_close(self):
        if datetime.now().weekday() >= 5:
            return
        # 🟢 [风控加固 Phase 9] 优化收盘总帐报告
        self.log_message.emit("🌆 [A股] 检测到收市时间(15:00)，启动每日结算审计...")

        cancel_count = 0
        if self.trd_ctx:
            try:
                from futu import OrderStatus, RET_OK
                ret, data = self.trd_ctx.order_list_query(trd_env=self.trd_env)
                if ret == RET_OK and not data.empty:
                    pending = data[data['status'].isin([
                        OrderStatus.SUBMITTING,
                        OrderStatus.SUBMITTED,
                        OrderStatus.WAITING_SUBMIT,
                        OrderStatus.FILLED_PART
                    ])]
                    for _, row in pending.iterrows():
                        self.trd_ctx.cancel_order(row['order_id'], trd_env=self.trd_env)
                        cancel_count += 1
            except Exception as e_cancel:
                logger.error(f"A股收盘撤单异常: {e_cancel}")

        # 1. 组装今日结算战报
        import sqlite3
        report = []
        report.append("\n================== [A股] 每日收盘结算报告 ==================")
        
        total_assets = 0
        available_cash = 0
        try:
            ret_acct, acct_data = self.trd_ctx.accinfo_query(trd_env=self.trd_env)
            if ret_acct == 0 and not acct_data.empty:
                total_assets = float(acct_data.iloc[0].get('total_assets', 0))
                available_cash = float(acct_data.iloc[0].get('cash', 0))
        except:
            pass
            
        report.append(f"📊 1. 资产全貌")
        report.append(f"   • 总资产水位: ¥{total_assets:.2f}")
        report.append(f"   • 剩余可用资金: ¥{available_cash:.2f}")
        report.append(f"   • 活跃止损追踪舱: {len(getattr(self, 'position_trackers', {}))} 只标的 ")
        
        report.append(f"\n📈 2. 今日交易清单 (Filled Trades)")
        
        try:
            conn = sqlite3.connect(self.db.db_path)
            cursor = conn.cursor()
            today_str = datetime.now().strftime('%Y-%m-%d')
            
            # 查买入单
            cursor.execute("SELECT code, name, entry_price, quantity FROM live_trades WHERE date(entry_time) = ?", (today_str,))
            buys = cursor.fetchall()
            for b in buys:
                report.append(f"   • [买入] {b[0]} ({b[1]}) | 成交: ¥{b[2]:.2f} | 数量: {b[3]}股")
                
            # 查卖出单
            cursor.execute("SELECT code, exit_price, exit_reason, pnl_pct FROM live_trades WHERE date(exit_time) = ?", (today_str,))
            sells = cursor.fetchall()
            for s in sells:
                report.append(f"   • [卖出/止损] {s[0]} | 出场: ¥{s[1]:.2f} | 理由: {s[2]} | PnL损耗: {s[3]:.2f}%")
        except Exception as e_db:
             report.append(f"   • 获取本地数据库报表异常: {e_db}")
            
        report.append(f"\n🛑 3. 系统除耗")
        report.append(f"   • 自动撤销挂单: {cancel_count} 笔")
        report.append(f"   • 开启结构止损防护标的: {len(getattr(self, 'structure_barrier', {}))} 个")
        report.append("==========================================================")
        
        final_msg = "\n".join(report)
        self.log_message.emit(final_msg)
        
        # Discord 推送
        if self.discord_bot:
            if hasattr(self.discord_bot, 'loop') and self.discord_bot.loop and self.discord_bot.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.discord_bot.send_notification(final_msg),
                    self.discord_bot.loop
                )



        self._cleanup_charts()
        self.log_message.emit("✅ [A股] 每日结算完成。")

    # ============================= 主异步循环 =============================

    def run_monitor_loop(self):
        """主线程入口 - 设置异步环境并运行 _async_main"""
        self._is_running = True
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._async_main())
        except Exception as e:
            self.log_message.emit(f"❌ [A股] 主循环异常退出: {e}")
        finally:
            self.loop.close()

    async def _async_main(self):
        """真正的异步主循环"""
        self._init_futu()
        self._init_discord()

        # 🛡️ [风控加固] 启动时常驻校准并补齐现有实际持仓的 ATR 止损锚点
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._initialize_position_trackers)
        except Exception as e:
            self.log_message.emit(f"⚠️ [A股-风控] 加载现有持仓的 ATR 失败: {e}")

        # 启动 GUI 指令轮询后台任务
        poll_task = asyncio.create_task(self._poll_gui_commands())

        self.log_message.emit(f"🚀 [A股] 异步监控引擎已启动 (分组: {self.watchlist_group}, 周期: 30m)")

        now = datetime.now()
        last_scan_bar = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
        last_heartbeat_min = -1
        last_stop_check_time = time.time()

        while self._is_running:
            try:
                now = datetime.now()

                # --- 每日收盘逻辑 ---
                current_date = now.date()
                if self._last_close_date != current_date:
                    if now.hour == 15 and now.minute >= 0:
                        self.on_market_close()
                        self._last_close_date = current_date

                # 热加载 ML 模型
                self.signal_validator.check_and_reload()

                # 心跳日志 (每分钟一次)
                # 心跳逻辑 (仅更新内部变量，不再打印日志以减少刷屏)
                if now.minute != last_heartbeat_min:
                    last_heartbeat_min = now.minute

                # ATR 移动止损检查 (每 60 秒，仅交易时间内)
                if self.is_trading_time() and time.time() - last_stop_check_time >= 60:
                    self._check_trailing_stops()
                    last_stop_check_time = time.time()

                # --- 扫描触发逻辑 ---
                current_bar = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)

                if self._force_scan:
                    self.log_message.emit("🔍 [A股] 捕获到强制扫描指令，启动分析 (非交易时间仅预警不下单)...")
                    await self._perform_scan_async()
                    self._force_scan = False
                    last_scan_bar = current_bar
                elif current_bar > last_scan_bar:
                    if self.is_trading_time():
                        if now.minute % 30 >= 5:
                            self.log_message.emit(f"🔍 [A股] 触发定时扫描 ({current_bar.strftime('%H:%M')})...")
                            await self._perform_scan_async()
                            last_scan_bar = current_bar
                    else:
                        last_scan_bar = current_bar
                elif not self._current_bar_scanned:
                    if self.is_trading_time() and now.minute % 30 >= 5:
                        self.log_message.emit(f"🔍 [A股] 首周期补偿扫描 ({current_bar.strftime('%H:%M')})...")
                        await self._perform_scan_async()
                        self._current_bar_scanned = True

                # 主循环睡眠 (0.5 秒精细度)
                await asyncio.sleep(0.5)

            except Exception as e:
                self.log_message.emit(f"⚠️ [A股] 循环遇到异常: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(10)

        poll_task.cancel()

    async def _poll_gui_commands(self):
        """后台协程: 持续轮询 GUI 指令队列"""
        while self._is_running:
            try:
                while not self.cmd_queue.empty():
                    cmd_type, data = self.cmd_queue.get_nowait()
                    self.log_message.emit(f"📥 [A股-指令] 正在执行: {cmd_type}")
                    try:
                        if cmd_type == 'FORCE_SCAN':
                            self._force_scan = True
                        elif cmd_type == 'QUERY_FUNDS':
                            await asyncio.get_event_loop().run_in_executor(None, self._do_query_funds)
                        elif cmd_type == 'CLOSE_ALL':
                            await asyncio.get_event_loop().run_in_executor(None, self._do_liquidate)
                        elif cmd_type == 'EXECUTE_TRADE':
                            c, a, p = data['code'], data['action'], data['price']
                            q = data.get('qty', 0)
                            self.log_message.emit(f"🚀 [A股] 执行验证指令: {c} {a}")
                            try:
                                await asyncio.get_event_loop().run_in_executor(
                                    None, lambda: self.execute_trade(**data)
                                )
                            except Exception as ex:
                                if not hasattr(self, 'retry_orders'): self.retry_orders = {}
                                self.retry_orders[c] = data
                                self.log_message.emit(f"⚠️ [A股-指令异常] {c} 执行失败: {ex}，已入自愈补单池。")
                        elif cmd_type == 'TRACK_ORDER':
                            asyncio.get_event_loop().run_in_executor(
                                None, self._track_order_status,
                                data['order_id'], data['code'], data['action'], data['qty'], data['price']
                            )
                    except Exception as e:
                        self.log_message.emit(f"⚠️ [A股-指令异常] 管道崩塌故障: {e}")
                        
                # 🔄 [自愈补偿机制] 定期检查未完成并补充执行的指令
                if hasattr(self, 'retry_orders') and self.retry_orders:
                    for c, r_data in list(self.retry_orders.items()):
                        self.log_message.emit(f"♻️ [A股-自愈] 正在发起重试补偿：{c} 的执行单...")
                        self.cmd_queue.put(('EXECUTE_TRADE', r_data))
                        del self.retry_orders[c]

                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"GUI 指令轮询异常: {e}")
                await asyncio.sleep(1)

    # ============================= 异步并发扫描 =============================

    async def _perform_scan_async(self):
        """执行异步并发扫描"""
        loop = asyncio.get_event_loop()
        watchlist = await loop.run_in_executor(None, self.get_watchlist_data)
        if not watchlist:
            return

        codes = list(watchlist.items())
        total = len(codes)
        self.log_message.emit(f"📋 [A股] 开始扫描 {total} 只股票 (并发限流: {self.scan_semaphore._value})...")

        # 🟢 [风控加固 Phase 9] 提取大盘上下文环境 (大盘动量/波动率)
        self.market_context = {}
        try:
            from Common.CEnum import KL_TYPE, AUTYPE
            from Chan import CChan
            from ChanConfig import CChanConfig
            idx_code = "SZ.399001" if TRADING_CONFIG.get("market_index_type") == "SZ" else "SH.510300"
            chan_idx = CChan(
                code=idx_code,
                begin_time=(datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d"),
                data_src="CUSTOM", # A股使用本地缓存
                lv_list=[KL_TYPE.K_30M],
                config=CChanConfig(CHAN_CONFIG),
                autype=AUTYPE.QFQ
            )
            if chan_idx.lv_list and len(list(chan_idx[0].klu_iter())) >= 10:
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
                self.log_message.emit(f"🌏 大盘状态诊断 ({idx_code}): 5周期动量={self.market_context.get('index_roc_5', 0):.4f}, 动能方差={self.market_context.get('index_volatility', 0):.4f}")
        except Exception as e_idx:
             self.log_message.emit(f"⚠️ 提取大盘环境特征失败: {e_idx}")

        start_time = time.time()

        # 使用 asyncio.gather 并发分析
        tasks = [
            self._analyze_single_stock_async(code, name, i + 1, total)
            for i, (code, name) in enumerate(codes)
        ]
        await asyncio.gather(*tasks)

        duration = time.time() - start_time
        self.log_message.emit(f"✅ [A股] 本轮扫描完成，耗时 {duration:.1f} 秒。")

    async def _analyze_single_stock_async(self, code: str, name: str, index: int, total: int):
        """并发分析单只股票 (受信号量限流保护)"""
        async with self.scan_semaphore:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    self._scan_single_stock_sync, code, name
                )
                if result:
                    chan, signals = result
                    for bsp in signals:
                        await loop.run_in_executor(
                            self.executor,
                            self._process_signal_sync, code, bsp, chan, name
                        )
            except Exception as e:
                logger.error(f"分析 {code} 异常: {e}")

    def _scan_single_stock_sync(self, code: str, name: str):
        """同步扫描单只股票 (在线程池中运行)"""
        days = LEVEL_DATA_DAYS.get(KL_TYPE.K_30M, 90)
        begin_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        from Common.StockUtils import get_default_data_sources
        data_sources = get_default_data_sources(code)

        chan = None
        for src in data_sources:
            try:
                chan = CChan(
                    code=code,
                    begin_time=begin_time,
                    data_src=src,
                    lv_list=[KL_TYPE.K_30M],
                    config=CChanConfig(CHAN_CONFIG),
                    autype=AUTYPE.QFQ
                )
                if chan.lv_list and len(chan[chan.lv_list[0]]) > 0:
                    break
            except Exception:
                continue

        if chan is None:
            return None

        bsp_list = chan.get_latest_bsp(number=0)
        now = datetime.now()

        new_signals = []
        for bsp in bsp_list:
            b_time = bsp.klu.time
            bsp_dt = datetime(b_time.year, b_time.month, b_time.day, b_time.hour, b_time.minute, b_time.second)
            # --- 3. 信号时效性过滤 (优化 E: 对齐港美股 1 小时窗口) ---
            diff_sec = (now - bsp_dt).total_seconds()
            if diff_sec <= 3600:
                # 去重检查
                sig_key_strict = f"{code}_{str(bsp.klu.time)}_{bsp.type2str()}"
                sig_key_loose = f"{code}_{bsp.type2str()}"

                if sig_key_strict in self.notified_signals:
                    continue

                if sig_key_loose in self.notified_signals:
                    last_info = self.notified_signals[sig_key_loose]
                    if isinstance(last_info, str):
                        try:
                            last_time = datetime.strptime(last_info, "%Y-%m-%d %H:%M:%S")
                            if (now - last_time).total_seconds() < 14400:
                                continue
                        except:
                            pass

                new_signals.append(bsp)

        if new_signals:
            # 记录信号
            for sig in new_signals:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sig_key_strict = f"{code}_{str(sig.klu.time)}_{sig.type2str()}"
                sig_key_loose = f"{code}_{sig.type2str()}"
                self.notified_signals[sig_key_strict] = now_str
                self.notified_signals[sig_key_loose] = now_str
            self._save_notified_signals()

            self.log_message.emit(
                f"🎯 [A股] {code} {name} 发现 {len(new_signals)} 个信号: "
                + ", ".join(s.type2str() for s in new_signals)
            )
            return (chan, new_signals)

        return None

    def _process_signal_sync(self, code: str, bsp, chan, name: str = ""):
        """同步处理单个信号 (ML → 绘图 → 视觉 → 交易) 在线程池中运行"""
        try:
            sig_type = "买点" if bsp.is_buy else "卖点"
            bsp_type_str = bsp.type2str()
            is_buy = bsp.is_buy
            now = datetime.now()

            # --- 0. [风控加固 Phase 8] 结构锁区拦截 (防下探拉锯) ---
            if is_buy and hasattr(self, 'structure_barrier') and code in self.structure_barrier:
                barrier_ts = self.structure_barrier[code]['lock_time_ts']
                has_new_pivot = False
                if hasattr(chan[0], 'zs_list'):
                    for zs in chan[0].zs_list:
                        if zs.begin.time.ts > barrier_ts:
                            has_new_pivot = True
                            break
                if not has_new_pivot:
                    self.log_message.emit(f"🛑 [A股-风控] {code} 触发过止损，当前下行下探笔未形成【新中枢】，拦截重复开仓。")
                    return
                else:
                    self.log_message.emit(f"🔓 [A股-风控] {code} 脱离旧止损笔段，发现新中枢结构，解锁准入。")
                    del self.structure_barrier[code]

            # --- 0. 多周期共振过滤 (优化 A: 30M+5M 严苛嵌套) ---
            chan_5m = None
            try:
                begin_5m = (now - timedelta(days=7)).strftime("%Y-%m-%d")
                # 使用与 30M 相同的 Data Source 拉取 5M
                chan_5m = CChan(
                    code=code,
                    begin_time=begin_5m,
                    data_src=chan.data_src,
                    lv_list=[KL_TYPE.K_5M],
                    config=CChanConfig(CHAN_CONFIG),
                    autype=AUTYPE.QFQ
                )
                
                if chan_5m:
                    bsp_5m_list = chan_5m.get_latest_bsp(number=0)
                    if not bsp_5m_list:
                         self.log_message.emit(f"⚠️ [A股] {code} {bsp_type_str} 30M 信号未获得 5M 共振确认 (5M无任何信号)，拦截")
                         return

                    # 验证最新 5M 信号
                    sorted_5m = sorted(bsp_5m_list, key=lambda x: str(x.klu.time), reverse=True)
                    latest_b = sorted_5m[0]
                    b_dt = datetime(latest_b.klu.time.year, latest_b.klu.time.month, latest_b.klu.time.day, 
                                   latest_b.klu.time.hour, latest_b.klu.time.minute, latest_b.klu.time.second)
                    
                    is_same_dir = (latest_b.is_buy == is_buy)
                    is_recent = (now - b_dt).total_seconds() < 1800 # 30min
                    
                    if not is_same_dir:
                        logger.debug(f"[A股] {code} {bsp_type_str} 5M 确认失败: 5M 最新信号为反向")
                        return
                    if not is_recent:
                        logger.debug(f"[A股] {code} {bsp_type_str} 5M 确认失败: 5M 最新信号已过时(>30min)")
                        return
                        
                    logger.debug(f"[A股] {code} {bsp_type_str} 30M+5M 多周期共振确认成功 (最新5M信号: {latest_b.type2str()})")
            except Exception as e_5m:
                logger.error(f"[A股] 5M 共振数据获取异常 {code}: {e_5m}")
                # 如果拉不到 5M 数据，为了严谨，选择拦截
                self.log_message.emit(f"⚠️ [A股] {code} 无法拉取 5M 数据进行共振验证，为保安全已拦截")
                return

            # --- 1. ML 校验 (买卖信号均需验证) ---
            ml_result = self.signal_validator.validate_signal(chan, bsp, market_context=getattr(self, 'market_context', {}))
            prob = ml_result.get('prob', 0)
            ml_threshold = TRADING_CONFIG.get('ml_threshold', 0.70)

            if bsp.is_buy:
                if prob < ml_threshold:
                    logger.debug(f"[A股] {code} ML 未达标 ({prob * 100:.1f}%) → 一票否决")
                    return
            else:
                # 卖出信号: 使用较低阈值 (0.4) 过滤假卖点
                if prob < 0.60:
                    self.log_message.emit(
                        f"🤖 [A股] {code} 卖出信号 ML 概率过低 ({prob * 100:.1f}% < 60%) → 拦截假卖点"
                    )
                    return
                else:
                    self.log_message.emit(f"🤖 [A股] {code} 卖出 ML 验证通过 ({prob * 100:.1f}%)")

            # --- 2. 绘图 (线程锁保护 matplotlib) ---
            chart_path = os.path.abspath(os.path.join(
                self.charts_dir,
                f"{code.replace('.', '_')}_{datetime.now().strftime('%H%M%S')}.png"
            ))
            with self.chart_generation_lock:
                plot_driver = CPlotDriver(chan, plot_config=CHART_CONFIG, plot_para=CHART_PARA)
                plot_driver.figure.savefig(chart_path, bbox_inches='tight', dpi=120, facecolor='white')
                plt.close(plot_driver.figure)

            # --- 3. 视觉评分 ---
            score = 0
            analysis = ""
            cache_key = f"{code}_{str(bsp.klu.time)}_{bsp_type_str}"

            if cache_key in self.visual_score_cache:
                cached = self.visual_score_cache[cache_key]
                score = cached.get('score', 0)
                analysis = cached.get('analysis', "缓存")
                self.log_message.emit(f"💾 [A股] {code} 命中视觉缓存: {score}分")
            else:
                self.log_message.emit(f"🧠 [A股] 正在对 {code} 进行视觉评分...")
                visual_result = self.visual_judge.evaluate([chart_path], bsp_type_str)

                if visual_result is None:
                    self.log_message.emit(f"⚠️ [A股] {code} 视觉评分返回为空，清除记录等待重试")
                    sig_key = f"{code}_{str(bsp.klu.time)}_{bsp_type_str}"
                    if sig_key in self.notified_signals:
                        del self.notified_signals[sig_key]
                        self._save_notified_signals()
                    return

                score = visual_result.get('score', 0)
                analysis = visual_result.get('analysis', "")

                # 检查是否为 API 错误
                is_api_error = (
                    '失败' in analysis
                    or visual_result.get('identified_signal') == 'ERROR'
                    or (score == 0 and '无详细分析' in analysis)
                )
                if is_api_error:
                    self.log_message.emit(f"⚠️ [A股] {code} 视觉API调用失败，清除记录等待重试")
                    sig_key = f"{code}_{str(bsp.klu.time)}_{bsp_type_str}"
                    if sig_key in self.notified_signals:
                        del self.notified_signals[sig_key]
                        self._save_notified_signals()
                    return

                self.visual_score_cache[cache_key] = {"score": score, "analysis": analysis}
                self.log_message.emit(f"✅ [A股] {code} 评分完成: {score}分")

            # --- 4. 综合准入判定 (严格模式: 无高分视觉覆盖) ---
            final_pass = ml_result.get('is_valid', False)

            if score < 70:
                self.log_message.emit(f"🚫 [A股] {code} 信号被拦截 [Visual: {score}, ML: {prob:.2f}]: 视觉得分不及格 ({score})")
                return

            if bsp.is_buy and not final_pass:
                fail_reason = ml_result.get('msg', 'ML 未达标')
                self.log_message.emit(f"🚫 [A股] {code} 信号被拦截 [Visual: {score}, ML: {prob:.2f}]: {fail_reason}")
                return

            self.log_message.emit(f"✅ [A股] {code} {sig_type} {bsp_type_str} 准入 [ML:{prob:.2f}, Visual:{score}]")

            # --- 5. Discord 推送 ---
            min_score = TRADING_CONFIG.get('min_visual_score', 70)
            if self.discord_bot and score >= min_score:
                ml_str = f"{prob * 100:.1f}分" if prob else "N/A"
                full_msg = (
                    f"📈 **A股自动化预警**\n"
                    f"股票: {code} ({name})\n"
                    f"信号: {sig_type} {bsp_type_str}\n"
                    f"价格: {bsp.klu.close:.2f}\n"
                    f"ML评分: **{ml_str}**\n"
                    f"视觉评分: **{score}分**\n"
                    f"分析: {analysis[:200]}..."
                )
                if hasattr(self.discord_bot, 'loop') and self.discord_bot.loop and self.discord_bot.loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self.discord_bot.send_notification(full_msg, chart_path),
                        self.discord_bot.loop
                    )

            # --- 6. 自动交易执行 (带交易时间保护) ---
            if self.trading_enabled:
                if not self.is_trading_time():
                    self.log_message.emit(f"⏳ [A股-交易] {code} 发现信号，但当前非交易时间，仅通报跳过下单。")
                else:
                    if score >= min_score:
                        if bsp.is_buy:
                            if final_pass:
                                self.log_message.emit(f"📩 [A股-交易] 信号通过全部校验，触发买入执行...")
                                self.cmd_queue.put(('EXECUTE_TRADE', {
                                    'code': code, 
                                    'action': 'BUY', 
                                    'price': bsp.klu.close,
                                    'signal_type': bsp_type_str,
                                    'ml_prob': prob,
                                    'visual_score': score,
                                    'name': name
                                }))
                        else:
                            self.log_message.emit(f"📩 [A股-交易] 发现卖出信号，触发执行...")
                            self.cmd_queue.put(('EXECUTE_TRADE', {
                                'code': code, 
                                'action': 'SELL', 
                                'price': bsp.klu.close,
                                'signal_type': sig_type,
                                'ml_prob': prob,
                                'visual_score': score,
                                'name': name
                            }))
                    else:
                        self.log_message.emit(f"⏭️ [A股] {code} 评分({score})低于交易阈值({min_score})，仅通报")

        except Exception as e:
            self.log_message.emit(f"⚠️ [A股] 信号处理失败 {code}: {e}")
            logger.error(f"_process_signal_sync error: {e}\n{traceback.format_exc()}")

    # ============================= 工具方法 =============================

    def _cleanup_charts(self):
        try:
            now = time.time()
            count = 0
            if not os.path.exists(self.charts_dir):
                return
            for f in os.listdir(self.charts_dir):
                path = os.path.join(self.charts_dir, f)
                try:
                    if os.path.isfile(path) and os.stat(path).st_mtime < now - 86400:
                        os.remove(path)
                        count += 1
                except OSError:
                    pass
            if count > 0:
                self.log_message.emit(f"♻️ [A股] 已清理 {count} 张过期图表")
        except Exception as e:
            logger.error(f"清理图表失败: {e}")

    def _initialize_position_trackers(self):
        """
        [启动拉起] 从 Futu 同步最新的实际账户持仓，
        对那些缺失 ATR 状态的任何个股，一站式拉取日线算好 ATR 并追溯载入监控池。
        """
        from futu import RET_OK
        try:
            self._init_trd_ctx()
            ret, data = self.trd_ctx.position_list_query(trd_env=self.trd_env)
            if ret != RET_OK or data.empty:
                return
                
            count = 0
            for _, row in data.iterrows():
                code = row['code']
                qty = int(row['qty'])
                if qty <= 0:
                    continue
                price = float(row['nominal_price'])
                cost = float(row.get('avg_cost', price))
                
                # 如果这个 code 还不受 self.position_trackers 保护
                if code not in self.position_trackers:
                    atr = self._calculate_atr(code)
                    if atr > 0:
                        self.position_trackers[code] = {
                            'entry_price': cost,  # 以持仓均价为基准成本
                            'highest_price': max(cost, price), 
                            'atr': atr,
                            'trail_active': False
                        }
                        # 同步数据库防止丢失
                        self.db.save_stop_loss_tracker(code, cost, max(cost, price), atr, 0)
                        self.log_message.emit(f"🛡️ [A股-风控] 发现遗漏持仓 {code}，追溯自愈开启 ATR 止损监控: 成本价={cost:.2f}, ATR={atr:.3f}")
                        count += 1
                        
            if count > 0:
                self.log_message.emit(f"✅ [A股-风控] 成功追溯开启了 {count} 只个股的原始 ATR 止损阀值。")
        except Exception as e:
            logger.error(f"A股初始化全仓位ATR止损异常: {e}")
