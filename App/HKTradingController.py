#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股自动化交易控制器

此模块将 `futu_hk_visual_trading_fixed.py` 中的核心逻辑封装为一个独立的、可被 GUI 调用的类。
它负责处理从信号收集、图表生成、视觉评分到最终交易执行的完整流程。
"""

import os
import sys
import time
import json
import logging
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Callable
from pathlib import Path
import asyncio
import queue

import os
if os.environ.get('WEB_MODE') == '1':
    from App.WebControllerAdapter import WebSignal as pyqtSignal, WebObject as QObject, pyqtSlot
else:
    try:
        from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
    except ImportError:
        from App.WebControllerAdapter import WebSignal as pyqtSignal, WebObject as QObject, pyqtSlot

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 解决 Matplotlib 与 GUI session 的冲突 ([Errno 5] I/O error)
import matplotlib
matplotlib.use('Agg')

# 导入配置和核心库
from config import TRADING_CONFIG, CHAN_CONFIG, CHART_PARA, MARKET_SPECIFIC_CONFIG
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib.pyplot as plt
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# 导入 Futu 和视觉评分
from futu import *
from visual_judge import VisualJudge
import aiohttp

# 导入风险管理
from Trade.RiskManager import get_risk_manager
from Trade.db_util import CChanDB
from Common.TimeUtils import get_trading_duration_hours as calc_trading_duration

# 导入本地评分
from Trade.LocalScorer import get_local_scorer

# 导入性能监控
from Monitoring.PerformanceMonitor import get_performance_monitor

# 导入ML信号验证器
from ML.SignalValidator import SignalValidator

# 导入 DiscordBot
from App.DiscordBot import DiscordBot

# 配置日志
logger = logging.getLogger(__name__)


class HKTradingController(QObject):
    """
    港股交易控制器，用于在 GUI 应用中集成自动化交易功能。
    该类继承自 QObject，以便可以使用 Qt 的信号机制与 GUI 主线程通信。
    """

    # 定义信号，用于向 GUI 主线程发送消息
    log_message = pyqtSignal(str)
    scan_progress = pyqtSignal(int, int, str)  # 当前进度, 总数, 消息
    trade_signal_found = pyqtSignal(dict)      # 发现交易信号
    scan_finished = pyqtSignal(int, int, int, int)  # 成功卖出, 成功买入, 失败卖出, 失败买入
    trade_executed = pyqtSignal(dict)          # 交易执行结果
    funds_updated = pyqtSignal(float, float, float, list)      # 资金持仓更新: 可用, 总资产, 今日盈亏, 持仓列表

    def __init__(self,
                 hk_watchlist_group: str = None,
                 min_visual_score: int = None,
                 max_position_ratio: float = None,
                 dry_run: bool = None,
                 discord_bot: DiscordBot = None,
                 parent=None):
        """
        初始化港股交易控制器。
        """
        super().__init__(parent)
        self.log_message.emit("🚀 正在初始化交易控制器...")
        self.hk_watchlist_group = hk_watchlist_group or TRADING_CONFIG['hk_watchlist_group']
        self.min_visual_score = min_visual_score or TRADING_CONFIG['min_visual_score']
        self.max_position_ratio = max_position_ratio or TRADING_CONFIG['max_position_ratio']
        self.dry_run = dry_run if dry_run is not None else TRADING_CONFIG.get('hk_dry_run', True)

        # 创建图表目录
        self.charts_dir = "charts"
        os.makedirs(self.charts_dir, exist_ok=True)

        # 延迟初始化富途连接 (在后台线程首次使用时创建，确保 socket 线程亲和性)
        self._quote_ctx = None
        self._trd_ctx = None
        self._trd_acc_id = None # 🟢 [核心补强] 用于锁定目标账号 ID
        self.trd_env = TrdEnv.SIMULATE if self.dry_run else TrdEnv.REAL

        # 初始化 Discord Bot (将在启动扫描时真正启动)
        self.discord_bot = discord_bot

        # 缠论配置
        self.chan_config = CChanConfig(CHAN_CONFIG)
        self.chan_config.kl_data_check = False  # 彻底关闭次级别强制对齐校验，防止 Hybrid 历史断层阻断扫描。

        # 视觉评分器
        self.visual_judge = VisualJudge()

        # 绘图锁和 API 锁
        self.chart_generation_lock = threading.Lock()
        self.futu_api_lock = threading.Lock()

        # 信号历史记录
        self.executed_signals_file = "executed_signals.json"
        self.executed_signals = self._load_executed_signals()
        self.discovered_signals_file = "discovered_signals.json"
        self.discovered_signals = self._load_discovered_signals()

        # 风险管理器
        self.risk_manager = get_risk_manager()
        
        # 本地评分器
        self.local_scorer = get_local_scorer()
        
        # 性能监控器
        self.performance_monitor = get_performance_monitor()

        # 用于停止和暂停扫描的标志
        self._is_running = False
        self._is_paused = False
        self._current_bar_scanned = False  # 初始设为 False，允许启动后的第一次补偿扫描判断 (仅在窗口内)
        self._force_scan = False  # 标志是否需要强制执行下一次扫描
        
        # 视觉评分缓存 (code_time_type -> score_dict)
        self.visual_score_cache = {}

        self.last_login_time = None
        
        # 记录持仓的追踪止损状态: { 'HK.00700': {'highest_price': 300.5, 'atr': 5.2, 'atr_multiplier': 2.0} }
        self.position_trackers = {}
        self.position_cache = {} # { 'HK.00700': 100 }
        self.last_pos_sync_time = 0
        self.structure_barrier = {}  # 🛡️ [风控锁区 Phase 8] 用于防止同一大下行笔延续段多次止损重复下单损耗
        
        # --- 队列缓冲与风控加固 ---
        import queue
        self.cmd_queue = queue.PriorityQueue()
        self.trade_cooldown = {} # {code: timestamp}
        
        # --- ML Validation ---
        self.signal_validator = SignalValidator()
        self.db = CChanDB()
        self.ml_threshold = 0.70
        self._last_close_date = None
        
        # 🚀 [Phase 11] 应用针对 港股 优化的专属参数
        hk_cfg = MARKET_SPECIFIC_CONFIG.get('HK', {})
        if 'bs_type' in hk_cfg:
            self.chan_config.bs_point_conf.b_conf.tmp_target_types = hk_cfg['bs_type']
            self.chan_config.bs_point_conf.b_conf.parse_target_type()
            self.chan_config.bs_point_conf.s_conf.tmp_target_types = hk_cfg['bs_type']
            self.chan_config.bs_point_conf.s_conf.parse_target_type()
        
        self.atr_stop_trail = hk_cfg.get('atr_stop_trail', TRADING_CONFIG.get('atr_stop_trail', 2.5))

        # 记录最近分析过的信号日志时间，防止重复刷屏: { 'HK.09959_2s': timestamp }
        self.last_analysis_log_time = {}

        # 并发基础设施 (对齐 A 股 MonitorController)
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.scan_semaphore = asyncio.Semaphore(3)
        
        # --- UI Callbacks ---
        self.log_message.emit("✅ 港股交易控制器初始化完成")

    @property
    def quote_ctx(self):
        """延迟初始化 Futu 行情上下文，确保在使用线程上创建"""
        if self._quote_ctx is None:
            self._quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        return self._quote_ctx

    @property
    def trd_ctx(self):
        """延迟初始化 Futu 交易上下文，确保在使用线程上创建，并锁定活跃账号"""
        if self._trd_ctx is None:
            self._trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
            
            # 🚀 [核心补强] 自动锁定有资产的港股模拟账户 ID
            ret, data = self._trd_ctx.get_acc_list()
            if ret == RET_OK and not data.empty:
                env_str = 'SIMULATE' if self.trd_env == TrdEnv.SIMULATE else 'REAL'
                # 💡 [关键修正] 港股 simulation 需筛选适当的 sim_acc_type (STOCK)
                filtered = data[data['trd_env'] == env_str]
                if self.trd_env == TrdEnv.SIMULATE:
                    # 模拟环境下可能有 OPTION, STOCK 等，选 STOCK 且 ID 比较靠后的(通常是最新的)
                    filtered = filtered[filtered['sim_acc_type'] == 'STOCK']
                
                if not filtered.empty:
                    self._trd_acc_id = int(filtered.iloc[0]['acc_id'])
                    self.log_message.emit(f"🎯 [HK-账户自检] 已锁定账户: {self._trd_acc_id} ({env_str})")
            
            # 🚀 [核心补强] 绑定成交与成交明细异步推送监听器 (影子账本)
            if self._trd_ctx:
                from futu import TradeOrderHandlerBase, TradeDealHandlerBase
                class HKTradePushHandler(TradeOrderHandlerBase):
                    def __init__(self, controller):
                        super().__init__()
                        self.controller = controller
                    def on_recv_rsp(self, rsp_str):
                        ret, data = super().on_recv_rsp(rsp_str)
                        if ret == RET_OK:
                            row = data.iloc[0]
                            status = row['order_status']
                            from futu import OrderStatus
                            if status in [OrderStatus.FILLED_ALL, OrderStatus.FILLED_PART]:
                                # 订单状态用于触发资产 UI 刷新 (大资金变动)
                                asyncio.run_coroutine_threadsafe(self.controller._sync_positions_async(), asyncio.get_event_loop())
                        return ret, data

                class HKTradeDealHandler(TradeDealHandlerBase):
                    def __init__(self, controller):
                        super().__init__()
                        self.controller = controller
                    def on_recv_rsp(self, rsp_str):
                        ret, data = super().on_recv_rsp(rsp_str)
                        if ret == RET_OK:
                            for _, row in data.iterrows():
                                code = row['code']
                                side = row['trd_side']
                                qty = int(row['qty'])
                                with self.controller.futu_api_lock:
                                    old_val = self.controller.position_cache.get(code, 0)
                                    if side == TrdSide.BUY:
                                        self.controller.position_cache[code] = old_val + qty
                                    elif side == TrdSide.SELL:
                                        self.controller.position_cache[code] = max(0, old_val - qty)
                                    self.controller.log_message.emit(f"✅ [HK-影子账本] {code} {side} {qty}股，更新仓位: {old_val} -> {self.controller.position_cache[code]}")
                        return ret, data
                
                self._trade_handler = HKTradePushHandler(self)
                self._deal_handler = HKTradeDealHandler(self)
                self._trd_ctx.set_handler(self._trade_handler)
                self._trd_ctx.set_handler(self._deal_handler)
                self.log_message.emit("🛡️ [HK-推送] 影子账本双监听服务已开启")
        return self._trd_ctx

    def _subscribe_stock_quote(self, code: str):
        """📡 [极速风控] 为持仓股订阅实时行情推送"""
        if not hasattr(self, 'live_prices'):
            self.live_prices = {}
        try:
            from futu import SubType, RET_OK
            
            # 1. 懒惰初始化 Handler
            if not hasattr(self, '_quote_handler') or self._quote_handler is None:
                from futu import StockQuoteHandlerBase
                class RTQuoteHandler(StockQuoteHandlerBase):
                    def __init__(self, controller):
                        super().__init__()
                        self.controller = controller
                    def on_recv_rsp(self, rsp_pb):
                        ret_code, content = super().on_recv_rsp(rsp_pb)
                        if ret_code == RET_OK:
                            for _, row in content.iterrows():
                                c = row['code']
                                if 'nominal_price' in row:
                                    cur_price = float(row['nominal_price'])
                                    self.controller.live_prices[c] = cur_price
                        return ret_code, content
                
                self._quote_handler = RTQuoteHandler(self)
                self.quote_ctx.set_handler(self._quote_handler)

            # 2. 启动长连接推送
            ret, data = self.quote_ctx.subscribe([code], [SubType.QUOTE], is_first_push=True)
            if ret == RET_OK:
                 # self.log_message.emit(f"📡 [风控-订阅] {code} 实时行情推送开启")
                 pass
        except Exception as e:
            logger.error(f"📡 [风控-订阅] {code} 开启失败: {e}")

    def _unsubscribe_stock_quote(self, code: str):
        """🚫 [极速风控] 取消单只股票实时推送(释放分配配额)"""
        try:
            from futu import SubType
            self.quote_ctx.unsubscribe([code], [SubType.QUOTE])
        except Exception:
            pass

    def _load_executed_signals(self) -> Dict:
        """加载已执行信号记录"""
        if os.path.exists(self.executed_signals_file):
            try:
                with open(self.executed_signals_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载已执行信号记录失败: {e}")
        return {}

    def _save_executed_signals(self):
        """保存已执行信号记录"""
        try:
            with open(self.executed_signals_file, 'w') as f:
                json.dump(self.executed_signals, f, indent=4)
        except Exception as e:
            logger.error(f"保存已执行信号记录失败: {e}")

    def _load_discovered_signals(self) -> Dict:
        """加载已发现信号记录"""
        if os.path.exists(self.discovered_signals_file):
            try:
                with open(self.discovered_signals_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载已发现信号记录失败: {e}")
        return {}

    def _save_discovered_signals(self):
        """保存已发现信号记录"""
        try:
            with open(self.discovered_signals_file, 'w') as f:
                json.dump(self.discovered_signals, f, indent=4)
        except Exception as e:
            logger.error(f"保存已发现信号记录失败: {e}")

    def stop(self):
        """停止当前的扫描和交易流程"""
        self._is_running = False
        if self.discord_bot:
            try:
                self.discord_bot.stop_sync()
            except:
                pass
        self.log_message.emit("🛑 收到停止信号，正在安全退出...")

    def force_scan(self):
        """外部触发：强制立即执行一轮完整策略扫描"""
        self._force_scan = True
        self.log_message.emit("⚡ 收到强制扫描指令，将在下一次心跳时触发完整扫描")

    def execute_manual_order(self, code, action, price, qty):
        """外部接口：执行港股手动交易指令 (统一入口)"""
        if not code: return
        # 标准化代码 (如 700 -> HK.00700)
        if not code.startswith("HK."):
            if code.isdigit():
                code = f"HK.{code.zfill(5)}"
            else:
                code = f"HK.{code.upper()}"
        else:
            code = code.upper()
            
        # 存入队列，使用高优先级 (0)
        import time
        self.cmd_queue.put((0, time.time(), 'MANUAL_TRADE', {
            'code': code,
            'action': action.upper(),
            'price': float(price),
            'quantity': int(qty),
            'urgent': True
        }))
        self.log_message.emit(f"🕹️ [手动-港股] 指令已入队: {action} {code} {qty}股 @ ${price}")

    def get_watchlist_data(self) -> Dict[str, str]:
        """获取所选自选股分组的代码和名称清单（支持港/美/A全市场自选股同步）"""
        try:
            # 支持多分组合并: "港股,热点_实盘" -> 分别拉取再合并
            # 如果配置为 "全部" 或 ""，则拉取全量自选股
            groups = [g.strip() for g in self.hk_watchlist_group.split(',') if g.strip()]
            if not groups or any(g in ["全部", "All", "自选股"] for g in groups):
                groups = [""] # 富途 API 空字符串表示全量自选股
            
            merged_watchlist = {}
            for group in groups:
                with self.futu_api_lock:
                    ret, data = self.quote_ctx.get_user_security(group_name=group)
                    if ret == RET_OK and not data.empty:
                        # 不再仅限于 'HK.'，支持 'US.', 'SH.', 'SZ.' 以及港股
                        name_col = 'name' if 'name' in data.columns else 'stock_name'
                        partial = dict(zip(data['code'].tolist(), data[name_col].tolist()))
                        merged_watchlist.update(partial)
                        # self.log_message.emit(f"✅ 分组 [{group or '全量自选'}] 获取到 {len(partial)} 只证券")
                    else:
                        self.log_message.emit(f"⚠️ 获取分组 [{group}] 失败: {data}")
            
            return merged_watchlist
        except Exception as e:
            self.log_message.emit(f"❌ 获取自选股列表异常: {e}")
            return {}

    def get_stock_info(self, code: str) -> Optional[Dict]:
        """获取单个股票的详细信息 (受 API 锁保护)"""
        try:
            with self.futu_api_lock:
                ret, data = self.quote_ctx.get_stock_basicinfo(Market.HK, code_list=[code])
                if ret == RET_OK and not data.empty:
                    info = data.iloc[0].to_dict()
                    ret_snap, snap_data = self.quote_ctx.get_market_snapshot([code])
                    if ret_snap == RET_OK and not snap_data.empty:
                        quote = snap_data.iloc[0]
                        info['current_price'] = quote['last_price']
                        info['lot_size'] = quote.get('lot_size', info.get('lot_size', 100))
                    else:
                        info['current_price'] = info.get('price', 0.0)
                        info['lot_size'] = info.get('lot_size', 100)
                    return info
            return None
        except Exception as e:
            logger.error(f"获取股票信息失败 {code}: {e}")
            return None

    def analyze_with_chan(self, code: str) -> Optional[Dict]:
        """
        对单个股票进行缠论分析。

        Args:
            code: 股票代码

        Returns:
            包含分析结果的字典，如果失败则返回 None
        """
        # [风控加固 Phase 8] 拦截模块平移至下方 K线 chan[0].zs_list 判定中提高判定精度

        try:
            # 获取30分钟和5分钟K线数据（分别获取，使用不同的时间范围）
            end_time = datetime.now()
            
            # ⚓ 对应 30M 和 5M 周期自适应对账，多端共享绝不动摇
            minutes_30m = (end_time.minute // 30) * 30
            end_time_30m = end_time.replace(minute=minutes_30m, second=0, microsecond=0)
            end_time_30m_str = end_time_30m.strftime("%Y-%m-%d %H:%M:%S")

            minutes_5m = (end_time.minute // 5) * 5
            end_time_5m = end_time.replace(minute=minutes_5m, second=0, microsecond=0)
            end_time_5m_str = end_time_5m.strftime("%Y-%m-%d %H:%M:%S")
            
            # 30M数据使用30天范围（历史数据充足）
            start_time_30m = end_time - timedelta(days=30)
            start_time_30m_str = start_time_30m.strftime("%Y-%m-%d")
            
            # 5M数据使用7天范围（避免Futu API的1000根K线限制）
            start_time_5m = end_time - timedelta(days=7)
            start_time_5m_str = start_time_5m.strftime("%Y-%m-%d")
            
            # 顺序获取30M数据
            try:
                # 默认数据源 使用 Hybrid 混合动力模型
                data_src = "custom:HybridFutuAPI.HybridFutuAPI"
                if code.upper().startswith("US.") and os.getenv("IB_HOST"):
                    data_src = DATA_SRC.IB
                
                # 获取30M数据 (加锁保护 Futu API 基础连接)
                chan_30m = None
                import time
                for attempt in range(3):
                    try:
                        chan_30m = CChan(
                            code=code,
                            begin_time=start_time_30m_str,
                            end_time=end_time_30m_str,
                            data_src=data_src,
                            lv_list=[KL_TYPE.K_30M],
                            config=self.chan_config
                        )
                        break
                    except Exception as e_c:
                        if attempt < 2:
                            time.sleep(1.5)  # 频控避让
                        else:
                            raise e_c
            except Exception as e:
                import traceback
                self.log_message.emit(f"⚠️ 获取K线数据异常 {code}: {e}")
                # logger.error(f"Futu Error for {code}: {traceback.format_exc()}")
                return None
            
            # 检查30M数据是否足够
            if chan_30m is None:
                self.log_message.emit(f"{code} 30分钟K线数据获取失败，跳过分析")
                return None
                
            kline_30m_count = 0
            for _ in chan_30m[0].klu_iter():
                kline_30m_count += 1
            if kline_30m_count < 10:  # 如果30M数据少于10根K线，则认为数据不足
                # self.log_message.emit(f"{code} 30分钟K线数据不足({kline_30m_count}根)，跳过分析")
                return None
            
            # 从30M级别获取最新的买卖点（主分析基于30M）
            latest_bsps = chan_30m.get_latest_bsp(idx=0, number=1)
            
            # ⚓ [防套牢加固 Phase 9] 针对持仓股，或者 30M 有买点信号的股，都必须排查 5M 逃顶卖点
            has_30M_buy = latest_bsps and latest_bsps[0].is_buy
            # 🔥 [自愈修复] 使用真实持仓数量，不再依赖可能残留僵尸持仓的 position_trackers
            position_qty = self.get_position_quantity(code)
            is_holding = position_qty > 0
            if is_holding or has_30M_buy:
                try:
                    chan_5m_escape = CChan(
                        code=code,
                        begin_time=start_time_5m_str,
                        end_time=end_time_5m_str,
                        data_src="custom:HybridFutuAPI.HybridFutuAPI",
                        lv_list=[KL_TYPE.K_5M],
                        config=self.chan_config
                    )
                    latest_bsps_5m = chan_5m_escape.get_latest_bsp(idx=0, number=1)
                    if latest_bsps_5m:
                        bsp_5m = latest_bsps_5m[0]
                        if not bsp_5m.is_buy:  # 5M卖点
                            bsp_ctime_5m = bsp_5m.klu.time
                            bsp_time_5m = datetime(bsp_ctime_5m.year, bsp_ctime_5m.month, bsp_ctime_5m.day,
                                                   bsp_ctime_5m.hour, bsp_ctime_5m.minute, bsp_ctime_5m.second)
                            # 🔑 重复逃顶保护：同一根 5M K 线只触发一次
                            escape_key = f"ESCAPE_{code}_{bsp_time_5m.strftime('%Y%m%d%H%M')}"
                            if escape_key not in self.discovered_signals:
                                self.discovered_signals[escape_key] = bsp_time_5m.strftime("%Y-%m-%d %H:%M:%S")
                                self._save_discovered_signals()
                                self.log_message.emit(f"🚨🚨 [5M 逃顶探测] {code} 触发 5M 级别卖点 ({bsp_5m.type2str()}) @ 价格={bsp_5m.klu.close}，启动逃逸！")
                                return {
                                    'code': code,
                                    'bsp_type': bsp_5m.type2str(),
                                    'is_buy_signal': False,
                                    'bsp_price': bsp_5m.klu.close,
                                    'bsp_datetime': bsp_5m.klu.time,
                                    'bsp_datetime_str': bsp_time_5m.strftime("%Y-%m-%d %H:%M:%S"),
                                    'is_escape_exit': True,
                                    'chan_analysis': {
                                        'chan_30m': chan_30m,
                                        'chan_5m': chan_5m_escape
                                    }
                                }
                            else:
                                # 🛡️ [风控加固] 如果前面已经报过，但【没有真实在单】，强制再一次释放！（防止假死漏单）
                                # 🔥 [自愈修复] 只有在真实有持仓时才触发自愈，避免 0 股信号无限重试
                                if is_holding and not self.check_pending_orders(code, 'SELL'):
                                    self.log_message.emit(f"🚨🚨 [5M 逃顶自愈] {code} 曾报过逃顶锁，但检测到无在单，强制再次逃逸！")
                                    return {
                                        'code': code, 'bsp_type': bsp_5m.type2str(), 'is_buy_signal': False,
                                        'bsp_price': bsp_5m.klu.close, 'bsp_datetime': bsp_5m.klu.time,
                                        'bsp_datetime_str': bsp_time_5m.strftime("%Y-%m-%d %H:%M:%S"),
                                        'is_escape_exit': True, 'chan_analysis': {'chan_30m': chan_30m, 'chan_5m': chan_5m_escape}
                                    }
                                self.log_message.emit(f"⏭️ [5M 逃顶] {code} 卖点 {bsp_time_5m} 已处理且在单中，跳过。")
                except Exception as e_5m:
                    self.log_message.emit(f"⚠️ [5M 逃顶] {code} 独立 5M 数据加载异常(非致命): {e_5m}")
            
            if not latest_bsps:
                return None  # 无信号，不再继续获取 5M 数据
            
            # 🛡️ [风控加固 Phase 8] 结构锁区检查 (防下探拉锯)
            if hasattr(self, 'structure_barrier') and code in self.structure_barrier:
                barrier_ts = self.structure_barrier[code]['lock_time_ts']
                has_new_pivot = False
                if hasattr(chan_30m[0], 'zs_list'):
                    for zs in chan_30m[0].zs_list:
                        if zs.begin.time.ts > barrier_ts:
                            has_new_pivot = True
                            break
                if not has_new_pivot:
                    return None
                else:
                    self.log_message.emit(f"🔓 [HK-风控] {code} 脱离旧止损笔段，发现新中枢结构，解锁准入。")
                    del self.structure_barrier[code]
            
            bsp = latest_bsps[0]
            bsp_type = bsp.type2str()
            is_buy = bsp.is_buy  # 信任 CChan 的 is_buy 判断
            price = bsp.klu.close
            
            # ====== 时间过滤【优化前置】：只交易最近配置小时内的信号 ======
            bsp_ctime = bsp.klu.time
            bsp_time = datetime(bsp_ctime.year, bsp_ctime.month, bsp_ctime.day,
                               bsp_ctime.hour, bsp_ctime.minute, bsp_ctime.second)
            
            now = datetime.now()
            trading_hours = self.calculate_trading_hours(bsp_time, now)
            
            if trading_hours > TRADING_CONFIG['max_signal_age_hours']:
                # 超时信号，直接丢弃，不加载5M
                return None
            
            # ====== [排障优化] 按需拉取 5M 前，先检查持仓、在单与历史去重，杜绝无效拉取 ======
            bsp_time_str = bsp_time.strftime("%Y-%m-%d %H:%M:%S")
            
            # 1. 历史去重 (对齐主循环)
            if self.executed_signals.get(code, "") == bsp_time_str:
                return None
            if self.discovered_signals.get(code, "") == bsp_time_str:
                return None
                
            # 2. 持仓过滤器
            pos_qty = self.get_position_quantity(code)
            if is_buy:
                if pos_qty > 0:
                    # self.log_message.emit(f"🛡️ {code} 已有持仓 ({pos_qty})，跳过买点 5M 拉取")
                    return None
            else:
                if pos_qty <= 0:
                    # self.log_message.emit(f"🛡️ {code} 无持仓，跳过卖点 5M 拉取")
                    return None
                    
            # 3. 在单过滤器
            if self.check_pending_orders(code, 'BUY' if is_buy else 'SELL'):
                # self.log_message.emit(f"⏳ {code} 存在未成交订单，跳过 5M 拉取")
                return None

            self.log_message.emit(f"{code} {bsp_type} {'买入' if is_buy else '卖出'}信号在有效窗口内 ({trading_hours:.1f}小时前)，按需加载 5M")

            # ====== 条件达标，按需获取 5M 数据（用于后续图表生成） ======
            chan_5m = None
            try:
                import time
                for attempt in range(3):
                    try:
                        chan_5m = CChan(
                            code=code,
                            begin_time=start_time_5m_str,
                            end_time=end_time_5m_str,
                            data_src="custom:HybridFutuAPI.HybridFutuAPI",
                            lv_list=[KL_TYPE.K_5M],
                            config=self.chan_config
                        )
                        break
                    except Exception as e_c:
                        if attempt < 2:
                            time.sleep(1.5)  # 频控避让
                        else:
                            raise e_c
                # 检查5M数据是否足够
                if chan_5m is not None:
                    kline_5m_count = 0
                    for _ in chan_5m[0].klu_iter():
                        kline_5m_count += 1
                    if kline_5m_count < 20:
                        chan_5m = None
            except Exception as e:
                self.log_message.emit(f"{code} 获取5M次级别数据失败 (非致命): {e}")
            
            result = {
                'code': code,
                'bsp_type': bsp_type,
                'is_buy_signal': is_buy,
                'bsp_price': price,
                'bsp_datetime': bsp.klu.time,
                'bsp_datetime_str': bsp_time.strftime("%Y-%m-%d %H:%M:%S"),
                'chan_analysis': {
                    'chan_30m': chan_30m,  # 30M分析对象
                    'chan_5m': chan_5m     # 5M分析对象（可能为None）
                }
            }
            
            # 仅在日志中打印一次（1小时内不重复打印相同代码和类型的分析日志）
            log_key = f"{code}_{bsp_type}"
            if log_key not in self.last_analysis_log_time or (now - self.last_analysis_log_time[log_key]).total_seconds() > 3600:
                # self.log_message.emit(f"{code} 缠论分析: {bsp_type} {'买入' if is_buy else '卖出'}信号, 价格: {price}")
                self.last_analysis_log_time[log_key] = now
                
            return result
            
        except Exception as e:
            self.log_message.emit(f"CChan分析异常 {code}: {e}")
            # 捕获特定的K线数据不足错误
            if "在次级别找不到K线条数超过" in str(e) or "次级别" in str(e):
                # self.log_message.emit(f"{code} 因K线数据不足跳过分析")
                pass
            return None

    def generate_charts(self, code: str, chan_analysis: Dict) -> List[str]:
        """
        生成技术分析图表。

        Args:
            code: 股票代码
            chan_analysis: 缠论分析结果

        Returns:
            图表文件路径列表
        """
        chart_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_code = code.replace('.', '_').replace('-', '_')
        
        # 使用线程锁确保matplotlib操作的线程安全性
        with self.chart_generation_lock:
            try:
                # 生成30M图表
                chan_30m = chan_analysis.get('chan_30m')
                if chan_30m:
                    plot_driver_30m = CPlotDriver(
                        chan_30m,
                        plot_config={
                            "plot_kline": True, "plot_bi": True, "plot_seg": True,
                            "plot_zs": True, "plot_bsp": True, "plot_macd": True
                        },
                        plot_para=CHART_PARA
                    )
                    
                    chart_path_30m = f"{self.charts_dir}/{safe_code}_{timestamp}_30M.png"
                    plt.savefig(chart_path_30m, bbox_inches='tight', dpi=120, facecolor='white')
                    plt.close('all')
                    chart_paths.append(chart_path_30m)
                    self.log_message.emit(f"✅ 生成30M图表: {chart_path_30m}")
                
                # 生成5M图表（如果存在）
                chan_5m = chan_analysis.get('chan_5m')
                if chan_5m:
                    plot_driver_5m = CPlotDriver(
                        chan_5m,
                        plot_config={
                            "plot_kline": True, "plot_bi": True, "plot_seg": True,
                            "plot_zs": True, "plot_bsp": True, "plot_macd": True
                        },
                        plot_para=CHART_PARA
                    )
                    
                    chart_path_5m = f"{self.charts_dir}/{safe_code}_{timestamp}_5M.png"
                    plt.savefig(chart_path_5m, bbox_inches='tight', dpi=120, facecolor='white')
                    plt.close('all')
                    chart_paths.append(chart_path_5m)
                    self.log_message.emit(f"✅ 生成5M图表: {chart_path_5m}")
                else:
                    self.log_message.emit(f"{code} 5M数据不可用，仅生成30M图表")
                
                return chart_paths
            except Exception as e:
                self.log_message.emit(f"生成图表异常 {code}: {e}")
                return []

    def is_in_continuous_trading_session(self) -> bool:
        """
        判断当前是否处于港股持续交易时段 (CTS)
        上午: 09:30 - 12:00
        下午: 13:00 - 16:00
        """
        now = datetime.now()
        # 港股交易日判断 (简单版，实际可结合 market_calendars)
        if now.weekday() >= 5:  # 周六日不交易
            return False
            
        current_time = now.time()
        morning_start = datetime.strptime("09:30", "%H:%M").time()
        morning_end = datetime.strptime("12:00", "%H:%M").time()
        afternoon_start = datetime.strptime("13:00", "%H:%M").time()
        afternoon_end = datetime.strptime("16:00", "%H:%M").time()
        
        is_morning = morning_start <= current_time <= morning_end
        is_afternoon = afternoon_start <= current_time <= afternoon_end
        
        return is_morning or is_afternoon

    def execute_trade(self, code: str, action: str, quantity: int, price: float, urgent: bool = False, exit_reason: str = "", score: float = 0.0, risk_params: dict = None) -> bool:
        """【管道桥接】将下单动作塞入队列进行并发缓冲，保证吞吐安全"""
        self.log_message.emit(f"📥 [港股-队列] 塞入指令: {code} {action} {quantity}股 @ {price:.2f} ({exit_reason})")
        priority = -score if score > 0 else 0
        self.cmd_queue.put((priority, time.time(), 'EXECUTE_TRADE', {
            'code': code, 'action': action, 'quantity': quantity, 'price': price, 'urgent': urgent, 'exit_reason': exit_reason, 'risk_params': risk_params
        }))
        return True # Asynchronous dispatch

    def _round_to_hk_tick(self, price: float, is_buy: bool) -> float:
        """
        [港股] 严格修正报单价格至允许的价位表 (Tick Size)
        防范富途因非标准价位导致模拟盘挂单永远不撮合。
        """
        if price <= 0: return 0.0
        
        if price < 0.25: tick = 0.001
        elif price < 0.5: tick = 0.005
        elif price < 10: tick = 0.01
        elif price < 20: tick = 0.02
        elif price < 100: tick = 0.05
        elif price < 200: tick = 0.1
        elif price < 500: tick = 0.2
        elif price < 1000: tick = 0.5
        elif price < 2000: tick = 1.0
        elif price < 5000: tick = 2.0
        else: tick = 5.0
        
        import math
        return float(round(math.ceil(price / tick) * tick if is_buy else math.floor(price / tick) * tick, 3))

    def _execute_trade_sync(self, code: str, action: str, quantity: int, price: float, urgent: bool = False, exit_reason: str = "", risk_params: dict = None) -> bool:
        """
        [原 execute_trade 降级为同步端] 执行交易 (带交易时间保护)
        """
        # --- 核心时间锁: 非交易时间禁止下单 (除非是模拟盘或者您明确想支持盘后，但用户要求禁止) ---
        if not self.is_trading_time():
             self.log_message.emit(f"⏳ [港股] {code} 触发交易指令 {action}，但当前非交易时间，已拦截。")
             return False

        # --- Lazy Recalculation inside single threaded consumer ---
        if risk_params and action.upper() == 'BUY':
            try:
                current_cash, total_assets = self.get_account_assets()
                if current_cash > 0:
                    quantity = self.risk_manager.calculate_position_size(
                        code=code, available_funds=current_cash, current_price=price,
                        total_assets=total_assets, **risk_params
                    )
                    self.log_message.emit(f"🔄 [港股] 并发缓冲重算: {code} 依据最新余额={current_cash:.0f}，重新分配量 = {quantity}股")
            except Exception as e_recalc:
                self.log_message.emit(f"⚠️ [港股] 重算仓位失败: {e_recalc}")

        if quantity <= 0:
            self.log_message.emit(f"无效数量 {quantity}，跳过交易 {code}")
            return False
        
        try:
            # 📡 [实时报价修正] 交易执行前拉取最新的现价，杜绝跨期价格断层导致的穿透方向错配
            try:
                ret_snap, snap_data = self.quote_ctx.get_market_snapshot([code])
                if ret_snap == RET_OK and not snap_data.empty:
                    current_market_price = float(snap_data.iloc[0]['last_price'])
                    if current_market_price > 0:
                        self.log_message.emit(f"📡 [实时报价] {code} 修正价格: {price:.2f} -> {current_market_price:.2f}")
                        price = current_market_price
            except Exception as e_snap:
                self.log_message.emit(f"⚠️ [实时报价] 刷新报价失败: {e_snap}")

            is_cts = self.is_in_continuous_trading_session()
            is_buy = action.upper() == 'BUY'
            trd_side = TrdSide.BUY if is_buy else TrdSide.SELL
            
            # 🚀 [优化建议 Phase 8] 紧急模式下，使用【穿透限价单】取代【市价单】，提高通道兼容性防拒单
            if urgent and is_cts:
                buffer = 0.05  # 5% 的穿透保护缓冲区
                raw_price = price * (1 + buffer) if is_buy else price * (1 - buffer)
                order_price = self._round_to_hk_tick(raw_price, is_buy)
                    
                self.log_message.emit(f"🚀 {code} 触发紧急模式，使用【5% 穿透限价单】执行 {action}: 数量={quantity}, 价格={order_price}")
                
                # 🛡️ [风控加固] 极速防爆：强制将 Futu 下单间隔拉开到 2.2 秒，对齐 15次/30秒 官方红线
                if hasattr(self, '_last_futu_order_time'):
                     elapsed = time.time() - self._last_futu_order_time
                     if elapsed < 2.2:
                          time.sleep(2.2 - elapsed)
                self._last_futu_order_time = time.time()

                ret, data = self.trd_ctx.place_order(
                    price=order_price,
                    qty=quantity,
                    code=code,
                    trd_side=trd_side,
                    order_type=OrderType.NORMAL,
                    trd_env=self.trd_env
                )
            else:
                # 常规模式或非交易时段，使用增强限价单
                # 如果是紧急模式但不在 CTS，缓冲区从 1% 扩大到 3%
                buffer = 0.03 if urgent else 0.01
                raw_price = price * (1 + buffer) if is_buy else price * (1 - buffer)
                order_price = self._round_to_hk_tick(raw_price, is_buy)
                
                mode_str = "紧急(回退)" if urgent else "常规"
                self.log_message.emit(f"📝 {code} 使用【增强限价单】({mode_str}) 执行 {action}: 数量={quantity}, 价格={order_price}")
                
                # 🛡️ [风控加固] 极速防爆：强制将 Futu 下单间隔拉开到 2.2 秒，对齐 15次/30秒 官方红线
                if hasattr(self, '_last_futu_order_time'):
                     elapsed = time.time() - self._last_futu_order_time
                     if elapsed < 2.2:
                          time.sleep(2.2 - elapsed)
                self._last_futu_order_time = time.time()

                ret, data = self.trd_ctx.place_order(
                    price=order_price,
                    qty=quantity,
                    code=code,
                    trd_side=trd_side,
                    order_type=OrderType.NORMAL,
                    trd_env=self.trd_env
                )
            
            if ret == RET_OK:
                order_id = data.iloc[0]['order_id']
                self.log_message.emit(f"✅ {action} 订单已提交 {code}: 订单ID={order_id}")
                
                # --- 记录实盘数据库 (优化 F) ---
                try:
                    from Trade.db_util import CChanDB
                    db = CChanDB()
                    actual_price = price if not urgent else price  # 市价单用当前价近似
                    if action.upper() == "BUY":
                        db.record_live_trade({
                            'code': code,
                            'name': getattr(self, '_last_stock_name', ''),
                            'market': 'HK',
                            'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'entry_price': actual_price,
                            'quantity': quantity,
                            'signal_type': getattr(self, '_last_signal_type', '未知'),
                            'ml_prob': getattr(self, '_last_ml_prob', 0),
                            'visual_score': getattr(self, '_last_visual_score', 0),
                            'status': 'open'
                        })
                    else:
                        actual_exit_reason = exit_reason if exit_reason else getattr(self, '_last_exit_reason', '信号卖出')
                        db.close_live_trade(code, actual_price, actual_exit_reason)
                except Exception as e:
                    logger.error(f"[HK-DB] 记录交易失败: {e}")

                # 启动订单跟踪
                threading.Thread(
                    target=self._track_order_status,
                    args=(order_id, code, action, quantity, price),
                    daemon=True
                ).start()

                return True
            else:
                self.log_message.emit(f"❌ {action} 订单失败 {code}: {data}")
                return False
                
        except Exception as e:
            self.log_message.emit(f"执行交易异常 {code}: {e}")
            return False

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

        for attempt in range(12):  # 最多 60 秒
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
                        f"📋 [港股-成交] {code} {action} {status_str}: "
                        f"{filled_qty}股 @ HK${filled_avg:.3f}"
                    )
                    if self.discord_bot and hasattr(self.discord_bot, 'loop') and self.discord_bot.loop and self.discord_bot.loop.is_running():
                        msg = (
                            f"📋 **港股订单成交**\n"
                            f"股票: {code}\n"
                            f"方向: {action}\n"
                            f"成交: {filled_qty}股 @ HK${filled_avg:.3f}\n"
                            f"时间: {datetime.now().strftime('%H:%M:%S')}"
                        )
                        asyncio.run_coroutine_threadsafe(
                            self.discord_bot.send_notification(msg), self.discord_bot.loop
                        )
                    return

                if status in (OrderStatus.CANCELLED_ALL, OrderStatus.CANCELLED_PART, OrderStatus.FAILED):
                    self.log_message.emit(
                        f"📋 [港股-订单] {code} {action} {status_str} (已成交: {filled_qty}/{qty}股)"
                    )
                    return

                if status == OrderStatus.FILLED_PART:
                    self.log_message.emit(
                        f"⏳ [港股-订单] {code} {action} 部分成交中: {filled_qty}/{qty}股 @ HK${filled_avg:.3f}"
                    )

            except Exception as e:
                logger.error(f"[港股] 订单跟踪异常: {e}")

        self.log_message.emit(f"⏰ [港股-订单] {code} {action} 60秒内未完全成交，请手动检查订单 {order_id}")

    def get_account_assets(self) -> Tuple[float, float]:
        """
        获取可用资金和总资产 (模拟盘/实盘都实时查询)

        Returns:
            (可用资金金额, 总资产金额)
        """
        try:
            # 0. [核心修复] 强制刷新模拟盘账户列表同步 (对齐 US/A股通道)
            if self.trd_env == TrdEnv.SIMULATE:
                self.trd_ctx.get_acc_list()

            refresh = (self.trd_env == TrdEnv.SIMULATE)
            ret, data = self.trd_ctx.accinfo_query(trd_env=self.trd_env, refresh_cache=refresh)
            if ret == RET_OK and not data.empty:
                row = data.iloc[0]
                # [详细调试] 打印所有资金组件
                log_msg = (f"💹 [港股-资金详情]\n"
                           f"   • 现金(cash): {row.get('cash', 'N/A')}\n"
                           f"   • 总资产(total_assets): {row.get('total_assets', 'N/A')}\n"
                           f"   • 购买力(power): {row.get('power', 'N/A')}\n"
                           f"   • 证券市值(market_val): {row.get('market_val', 'N/A')}")
                self.log_message.emit(log_msg)

                # 优先使用 cash 字段 (总现金)
                if 'cash' in data.columns:
                    available_funds = data.iloc[0]['cash']
                elif 'avl_withdrawal_cash' in data.columns:
                    available_funds = data.iloc[0]['avl_withdrawal_cash']
                else:
                    available_funds = data.iloc[0].get('total_assets', 0.0)
                total_assets = data.iloc[0].get('total_assets', available_funds)
                self.log_message.emit(f"可用资金：{available_funds:,.2f} HKD, 总资产: {total_assets:,.2f} HKD")
                return float(available_funds), float(total_assets)
            else:
                self.log_message.emit(f"获取账户信息失败：{data}")
                return 0.0, 0.0
        except Exception as e:
            self.log_message.emit(f"获取资金信息异常：{e}")
            return 0.0, 0.0

    def _cleanup_old_charts(self, hours: int = 24):
        """清理旧的图表进行空间释放。"""
        import time
        try:
            now = time.time()
            cutoff = now - (hours * 3600)
            count = 0
            if os.path.exists(self.charts_dir):
                for filename in os.listdir(self.charts_dir):
                    if filename.endswith('.png'):
                        filepath = os.path.join(self.charts_dir, filename)
                        if os.path.getmtime(filepath) < cutoff:
                            try:
                                os.remove(filepath)
                                count += 1
                            except OSError:
                                pass
            if count > 0:
                self.log_message.emit(f"♻️ 自动清理：已删除 {count} 张超过 {hours} 小时的旧图表图片，释放空间")
        except Exception as e:
            logger.error(f"清理旧图表失败: {e}")

    def cancel_all_pending_orders(self) -> int:
        """收盘撤销所有未成交订单"""
        from futu import OrderStatus
        count = 0
        try:
            ret, data = self.trd_ctx.order_list_query(trd_env=self.trd_env)
            if ret == RET_OK and not data.empty:
                pending_states = [
                    OrderStatus.SUBMITTING, 
                    OrderStatus.SUBMITTED, 
                    OrderStatus.WAITING_SUBMIT,
                    OrderStatus.FILLED_PART
                ]
                pending_orders = data[data['order_status'].isin(pending_states)]
                
                for _, row in pending_orders.iterrows():
                    order_id = row['order_id']
                    ret_c, data_c = self.trd_ctx.cancel_order(order_id, trd_env=self.trd_env)
                    if ret_c == RET_OK:
                        count += 1
                        self.log_message.emit(f"✅ [收盘] 已成功撤单: {row['code']} (ID: {order_id})")
                    else:
                        self.log_message.emit(f"⚠️ [收盘] 撤单失败: {row['code']} (ID: {order_id}) - {data_c}")
            return count
        except Exception as e:
            self.log_message.emit(f"❌ [收盘] 撤单过程遇到异常: {e}")
            return 0

    def on_market_close(self):
        """每日收盘动作集合：撤单、报表、推送、清理"""
        # 周末不执行
        if datetime.now().weekday() >= 5:
            return
        self.log_message.emit("🌆 [系统] 检测到港股收市时间(16:10)，启动每日收盘流程...")
        
        # 1. 撤销当日挂单
        cancelled_count = self.cancel_all_pending_orders()
        
        # 🟢 [风控加固 Phase 9] 优化收盘总帐报告
        pnl_msg = ""
        report = []
        report.append("\n================== [港股] 每日收盘结算报告 ==================")

        total_assets = 0
        available_cash = 0
        try:
            # 1. 资产全貌
            ret_a, acct_data = self.get_account_assets() # Wait, get_account_assets returns (cash, total_assets)
            if hasattr(self, 'get_account_assets'):
                 available_cash, total_assets = self.get_account_assets()
        except:
             pass

        report.append(f"📊 1. 资产全貌")
        report.append(f"   • 总资产水位: HKD {total_assets:.2f}")
        report.append(f"   • 剩余可用资金: HKD {available_cash:.2f}")
        report.append(f"   • 活跃止损追踪舱: {len(getattr(self, 'position_trackers', {}))} 只标的 ")

        report.append(f"\n📈 2. 今日交易清单 (Filled Trades)")
        try:
            from futu import OrderStatus
            import sqlite3
            conn = sqlite3.connect(self.db.db_path)
            cursor = conn.cursor()
            today_str = datetime.now().strftime('%Y-%m-%d')

            # 查买入单
            cursor.execute("SELECT code, name, entry_price, quantity FROM live_trades WHERE date(entry_time) = ? AND market = 'HK'", (today_str,))
            buys = cursor.fetchall()
            for b in buys:
                 qty_val = b[3]
                 if isinstance(qty_val, bytes):
                     import struct
                     qty_val = struct.unpack('<q', qty_val)[0] if len(qty_val) == 8 else int.from_bytes(qty_val, byteorder='little')
                 report.append(f"   • [买入] {b[0]} ({b[1]}) | 成交: HKD {b[2]:.2f} | 数量: {qty_val}股")

            # 查卖出单
            cursor.execute("SELECT code, exit_price, exit_reason, pnl_pct FROM live_trades WHERE date(exit_time) = ? AND market = 'HK'", (today_str,))
            sells = cursor.fetchall()
            for s in sells:
                 report.append(f"   • [卖出/止损] {s[0]} | 出场: HKD {s[1]:.2f} | 理由: {s[2]} | PnL损耗: {s[3]:.2f}%")
        except Exception as e_db:
             report.append(f"   • 获取本地数据库报表异常: {e_db}")

        report.append(f"\n🛑 3. 系统除耗")
        report.append(f"   • 自动撤销挂单: {cancelled_count} 笔")
        report.append(f"   • 处于结构止损锁舱数: {len(getattr(self, 'structure_barrier', {}))} 个")
        report.append("==========================================================")
        
        pnl_msg = "\n".join(report)
        self.log_message.emit(pnl_msg)
        
        # 3. Discord 推送收盘战报表
        if self.discord_bot:
            import asyncio
            if self.discord_bot.loop and self.discord_bot.loop.is_running():
                env_str = "模拟盘" if self.trd_env == TrdEnv.SIMULATE else "实盘"
                full_report = (
                    f"🌆 **港股收盘日报 ({env_str})**\n"
                    f"日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"----------------------------------\n"
                    f"{pnl_msg}"
                    f"----------------------------------\n"
                    f"系统已进入低功耗休眠，等待下个交易日。"
                )
                asyncio.run_coroutine_threadsafe(self.discord_bot.send_notification(full_report), self.discord_bot.loop)
        
        # 4. 执行资源清理
        self._cleanup_old_charts()
        
        self.log_message.emit("✅ [收盘] 每日结转流程已完成。")

    def is_trading_time(self) -> bool:
        """
        检查当前是否在港股交易时间内。
        港股交易时间：
        上午：09:30 - 12:00
        下午：13:00 - 16:10 (包含收市竞价)
        周六日不交易。
        """
        now = datetime.now()
        # 1. 检查是否是周末
        if now.weekday() >= 5:  # 5 是周六，6 是周日
            return False
            
        current_time = now.time()
        
        # 2. 定义交易时段
        morning_start = datetime.strptime("09:30", "%H:%M").time()
        morning_end = datetime.strptime("12:00", "%H:%M").time()
        afternoon_start = datetime.strptime("13:00", "%H:%M").time()
        afternoon_end = datetime.strptime("16:10", "%H:%M").time()
        
        # 3. 检查当前时间是否在时段内
        if morning_start <= current_time <= morning_end:
            return True
        if afternoon_start <= current_time <= afternoon_end:
            return True
            
        return False

    def get_status_summary(self) -> str:
        """
        获取交易控制器的实时状态摘要，供 Discord 或 GUI 显示。
        """
        try:
            # 0. [核心修复] 强制刷新模拟盘账户列表同步
            if self.trd_env == TrdEnv.SIMULATE:
                self.trd_ctx.get_acc_list()

            # 1. 查询资金信息
            refresh = (self.trd_env == TrdEnv.SIMULATE)
            ret_acc, data_acc = self.trd_ctx.accinfo_query(trd_env=self.trd_env, refresh_cache=refresh)
            if ret_acc == RET_OK and not data_acc.empty:
                row = data_acc.iloc[0]
                # 尝试多个可能的字段名
                total_assets = row.get('total_assets', row.get('total_asset', 0.0))
                power = row.get('power', row.get('cash', row.get('avl_withdrawal_cash', 0.0)))
                unrealized_pl = row.get('unrealized_pl', row.get('unrealized_pnl', 0.0))
                
                # 安全转换为 float
                try: total_assets = float(total_assets)
                except: total_assets = 0.0
                try: power = float(power)
                except: power = 0.0
                try: unrealized_pl = float(unrealized_pl)
                except: unrealized_pl = 0.0
            else:
                total_assets = 0.0
                power = 0.0
                unrealized_pl = 0.0

            # 2. 查询持仓 (💡 [核心补强] 显式使用已锁定的账号 ID)
            if refresh:
                self.trd_ctx.accinfo_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=True)
            ret_pos, data_pos = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=False)
            pos_count = len(data_pos) if ret_pos == RET_OK and not data_pos.empty else 0
            
            # 3. 运行状态
            run_status = "🟢 正在运行" if self._is_running else "🛑 已停止"
            if self._is_paused:
                run_status = "⏸️ 已暂停"
            
            mode = "🧪 仿真 (Simulate)" if self.dry_run else "💰 生产 (Real)"
            
            summary = (
                f"📊 **自动化交易状态摘要**\n"
                f"----------------------------------\n"
                f"▸ 运行状态: {run_status}\n"
                f"▸ 交易模式: {mode}\n"
                f"▸ 总 资 产: `{total_assets:,.2f} HKD`\n"
                f"▸ 可用资金: `{power:,.2f} HKD`\n"
                f"▸ 未实现盈亏: `{unrealized_pl:,.2f} HKD`\n"
                f"▸ 当前持仓: `{pos_count} 只股票`\n"
                f"▸ 监控分组: `{self.hk_watchlist_group}`\n"
                f"▸ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return summary
        except Exception as e:
            logger.error(f"Error getting status summary: {e}")
            return f"❌ 获取状态摘要失败: {str(e)}"

    def toggle_pause(self, paused: bool):
        """切换暂停状态"""
        self._is_paused = paused
        status_msg = "暂停" if paused else "恢复"
        self.log_message.emit(f"🔄 自动化扫描已{status_msg} (通过 Discord 指令)")

    def manual_trade(self, code: str, action: str, quantity: int) -> dict:
        """
        通过 Discord 手动下单（买入或卖出）。

        Args:
            code: 股票代码，如 'HK.09988'
            action: 'BUY' 或 'SELL'
            quantity: 交易数量 (股)

        Returns:
            dict with keys: success (bool), message (str), price (float)
        """
        action = action.upper()
        if action not in ('BUY', 'SELL'):
            return {'success': False, 'message': f"无效操作：{action}，应为 BUY 或 SELL", 'price': 0}

        if quantity <= 0:
            return {'success': False, 'message': f"无效数量：{quantity}", 'price': 0}

        # 确保格式正确
        if not code.startswith('HK.'):
            code = f"HK.{code}"

        self.log_message.emit(f"📡 Discord 手动指令 - 正在获取 {code} 最新行情...")
        info = self.get_stock_info(code)
        if not info or info.get('current_price', 0) <= 0:
            return {'success': False, 'message': f"无法获取 {code} 的最新价格，请检查股票代码是否正确。", 'price': 0}

        current_price = info['current_price']
        lot_size = info.get('lot_size', 100)

        # 检查数量是否为合法手数的整数倍
        if lot_size > 0 and quantity % lot_size != 0:
            return {
                'success': False,
                'message': f"❌ 数量 {quantity} 不是最小交易单位 {lot_size} 的整数倍。",
                'price': current_price
            }

        self.log_message.emit(f"📝 Discord 手动指令 - {action} {code}: 数量={quantity}, 参考价={current_price}")

        success = self.execute_trade(code, action, quantity, current_price, urgent=True)

        if success:
            msg = f"✅ **{action}** {code} **{quantity}** 股，参考价 **{current_price:.3f}**，订单已提交。"
        else:
            msg = f"❌ {action} {code} {quantity} 股失败，请查看 GUI 日志。"

        return {'success': success, 'message': msg, 'price': current_price}

    def run_scan_and_trade(self):
        """主线程入口 - 设置异步环境并运行 _async_main"""
        self._is_running = True
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._async_main())
        except Exception as e:
            self.log_message.emit(f"❌ [港股] 主循环异常退出: {e}")
            logger.error(f"Main loop error: {e}\n{traceback.format_exc()}")
        finally:
            self.loop.close()

    async def _poll_commands_async(self):
        """持续轮询指令队列 (对齐 A股/美股)"""
        while self._is_running:
            try:
                import queue
                while not self.cmd_queue.empty():
                    priority, ts, cmd_type, data = self.cmd_queue.get_nowait()
                    if cmd_type == 'EXECUTE_TRADE':
                        c, a = data['code'], data['action']
                        q, p = data['quantity'], data['price']
                        urgent = data.get('urgent', False)
                        # 在线程池中执行同步下单
                        success = await asyncio.get_event_loop().run_in_executor(
                            None, self._execute_trade_sync, c, a, q, p, urgent
                        )
                        if success and hasattr(self, 'trade_cooldown'):
                            self.trade_cooldown[c] = time.time() # 下单成功刷新冷却期
                    elif cmd_type == 'MANUAL_TRADE':
                        c = data.get('code', 'Unknown')
                        self.log_message.emit(f"🚀 [手动-港股] 正在执行: {data['action']} {c} ({data['quantity']}股 @ {data['price']:.2f})")
                        try:
                            # 借用内部已有的同步交易逻辑
                            await asyncio.get_event_loop().run_in_executor(
                                None, self._execute_trade_sync,
                                data['code'], data['action'], data['quantity'], data['price'], True
                            )
                        except Exception as ex:
                            self.log_message.emit(f"⚠️ [手动-港股异常] {c} 执行失败: {ex}")
            except Exception:
                pass
            await asyncio.sleep(0.5)

    async def _async_main(self):
        """真正的异步主循环 (对齐 MonitorController)"""
        # 真正启动 Discord Bot (这样日志才能被 GUI 接收到)
        if self.discord_bot is None and TRADING_CONFIG.get('discord') and TRADING_CONFIG['discord'].get('token'):
            try:
                self.discord_bot = DiscordBot(
                    token=TRADING_CONFIG['discord']['token'],
                    channel_id=TRADING_CONFIG['discord']['channel_id'],
                    allowed_user_ids=TRADING_CONFIG['discord']['allowed_user_ids'],
                    controller=self
                )
                self.discord_bot.start()
                self.log_message.emit("🤖 Discord 机器人已启动")
            except Exception as e:
                self.log_message.emit(f"⚠️ Discord 机器人启动失败: {e}")

        self.log_message.emit("🚀 启动港股异步双速监控进程 (60s 风险监测 / 30m 策略扫描)...")
        
        # 避免启动时立即触发全量扫描，初始化为当前 30M Bar 时间，等待下一个周期再触发
        now = datetime.now()
        last_strategy_scan_time = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
        
        # 0. 初始化现有持仓的风险监控
        await asyncio.get_event_loop().run_in_executor(None, self._initialize_position_trackers)
        
        # 0.1 启动队列消费者
        asyncio.create_task(self._poll_commands_async())
        
        last_stop_check_time = time.time()
        last_escape_check_time = 0  # 设置为 0 强制启动时立即跑一次 5M 逃顶检测
        
        while self._is_running:
            try:
                now = datetime.now()
                # 计算属于哪个 30 分钟 K 线桶 (例如 10:29 -> 10:00, 10:31 -> 10:30)
                current_bar_time = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
                # --- 每日收盘逻辑探测 (Phase 2) ---
                current_date = now.date()
                if self._last_close_date != current_date:
                    # 港股在 16:10 (CAS结束) 触发收盘
                    if now.hour == 16 and now.minute >= 10:
                        await asyncio.get_event_loop().run_in_executor(None, self.on_market_close)
                        self._last_close_date = current_date

                # 0. 基础维护
                self._cleanup_old_charts(hours=24)
                
                # Phase 4: 检查并热加载最新的优化的模型
                self.signal_validator.check_and_reload()
                
                # 检查是否暂停
                if self._is_paused:
                    await asyncio.sleep(5)
                    continue

                # 检查是否在交易时间内
                if not self.is_trading_time() and not self._force_scan:
                    await asyncio.sleep(30)
                    continue
                
                # 1. 快速风险监测 (极速数据线：调整为 2 秒，大幅降低滑点)
                if time.time() - last_stop_check_time >= 2:
                    await asyncio.get_event_loop().run_in_executor(None, self._check_trailing_stops)
                    last_stop_check_time = time.time()
                
                # 🔥 [5M 逃顶快速路 Phase 8+] 独立于 30M 扫描，每 5 分钟专门跑一次持仓 5M 逃顶检测
                # 不等 30M Bar 换挡，确保 5M 卖点最多 5 分钟内被捕获并出单
                if time.time() - last_escape_check_time >= 300:
                    await asyncio.get_event_loop().run_in_executor(None, self._check_5m_escape_for_holdings)
                    last_escape_check_time = time.time()
                
                # 2. 慢速策略扫描触发逻辑
                # 规则：如果当前 Bar 时间与上次不同，且已经过了 Bar 开始后 2 分钟（等待数据稳定）
                should_scan_strategy = False
                is_force_scan = False
                
                if self._force_scan:
                    should_scan_strategy = True
                    is_force_scan = True
                    self._force_scan = False  # 重置标志
                elif last_strategy_scan_time != current_bar_time:
                    if now.minute % 30 >= 1: 
                        should_scan_strategy = True
                        # Phase 7: 每当进入新的 30M Bar，所有持仓的计数器 +1
                        if hasattr(self, 'position_trackers'):
                            for tracker in self.position_trackers.values():
                                tracker['bars_held'] = tracker.get('bars_held', 0) + 1
                elif not self._current_bar_scanned:
                    # 补偿刚启动时当前 30M 周期还未跑过扫描的情况
                    # 规则：仅在当前 Bar 时间开始后的前 8 分钟内允许补偿扫描 (例如 11:31-11:38)
                    if 1 <= (now.minute % 30) <= 8:
                        should_scan_strategy = True
                        self._current_bar_scanned = True
                    elif (now.minute % 30) > 8:
                        # 核心重点：如果启动时已经过了太久（比如 11:15 或 11:45），
                        # 则直接标记该 Bar 已扫完，从而避免“开机即扫”造成资源浪费（等下一个 30M 边界）
                        self.log_message.emit(f"ℹ️ 当前周期 ({current_bar_time.strftime('%H:%M')}) 已进入中段，跳过开机捕获，等待下一个 30M 边界。")
                        self._current_bar_scanned = True
                
                if should_scan_strategy:
                    log_msg = f"🔍 [策略扫描] 启动并发分析 ({current_bar_time.strftime('%H:%M')})..."
                    self.log_message.emit(log_msg)
                    
                    # 使用新的异步并发扫描方法
                    await self._perform_scan_async(is_force_scan=is_force_scan)
                    
                    last_strategy_scan_time = current_bar_time
                    self.log_message.emit("✅ [策略扫描] 本轮并发分析完成。")
                
                # 休眠 1 秒（轮询精细度）
                await asyncio.sleep(1)

            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                self.log_message.emit(f"❌ 运行循环发生异常: {e}\n{error_trace}")
                # logger.error(traceback.format_exc())
                await asyncio.sleep(10)

        self.log_message.emit("🔚 港股自动化监控进程已安全退出。")

    # ============================= 异步并发扫描 (对齐 MonitorController) =============================

    async def _perform_scan_async(self, is_force_scan: bool = False):
        """执行异步并发扫描"""
        # 🛡️ [同步加固 Phase 9] 启动扫描前先同步全量持仓，降低子进程中的 API 碎片化查询压力
        await self._sync_positions_async()
        
        watchlist = self.get_watchlist_data()
        if not watchlist:
            return

        codes = list(watchlist.items())
        total = len(codes)
        self.log_message.emit(f"📋 [港股] 开始并发扫描 {total} 只股票 (并发限流: {self.scan_semaphore._value})...")

        # 🌏 [风控加固 Phase 9] 提取大盘上下文环境 (恒生指数 HSI 动量/波动率)
        self.market_context = {}
        try:
            from Common.CEnum import KL_TYPE, AUTYPE
            from Chan import CChan
            from ChanConfig import CChanConfig
            from Common.StockUtils import get_default_data_sources
            idx_code = TRADING_CONFIG.get("hk_market_index", "HK.800000")
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
                self.log_message.emit(f"🌏 港股大盘诊断 ({idx_code}): 5周期动量={self.market_context.get('index_roc_5', 0):.4f}, 动能方差={self.market_context.get('index_volatility', 0):.4f}")
        except Exception as e_idx:
             self.log_message.emit(f"⚠️ 提取港股大盘环境特征失败: {e_idx}")

        start_time = time.time()

        # 使用 asyncio.gather 并发分析
        tasks = [
            self._analyze_single_stock_async(code, name, i + 1, total, is_force_scan)
            for i, (code, name) in enumerate(codes)
        ]
        
        # 收集所有可能产生的信号
        results = await asyncio.gather(*tasks)
        candidate_signals = [sig for res in results if res for sig in res]

        # 2. 生成图表 & 评分 & 执行
        if candidate_signals:
            self.log_message.emit(f"🎯 [港股] 扫描完成，发现 {len(candidate_signals)} 个有效初步信号，进入视觉评分/执行阶段...")
            scored_signals = await self._process_candidate_signals_async(candidate_signals)
            if scored_signals:
                available_funds, total_assets = self.get_account_assets()
                await asyncio.get_event_loop().run_in_executor(
                    None, self._execute_trades, scored_signals, available_funds, total_assets
                )
        
        # 进度清理
        self.scan_finished.emit(0, 0, 0, 0)

        duration = time.time() - start_time
        # 记录性能
        self.performance_monitor.record_scan_performance(total, duration)
        self.log_message.emit(f"✅ [港股] 本轮并发分析完成，总耗时 {duration:.1f} 秒。")

    async def _analyze_single_stock_async(self, code: str, name: str, index: int, total: int, is_force_scan: bool):
        """并发分析单只股票 (受信号量限流保护)"""
        async with self.scan_semaphore:
            try:
                loop = asyncio.get_event_loop()
                self.scan_progress.emit(index, total, f"并发分析 {code} {name}")
                
                # 在线程池中执行同步解析逻辑
                result = await loop.run_in_executor(
                    self.executor,
                    self._scan_single_stock_sync, code, name, is_force_scan
                )
                return result
            except Exception as e:
                logger.error(f"分析 {code} 异常: {e}")
                return None

    def _scan_single_stock_sync(self, code: str, name: str, is_force_scan: bool) -> List[Dict]:
        """同步扫描单只股票 (在线程池中运行)"""
        try:
            # 获取股票信息
            stock_info = self.get_stock_info(code)
            if not stock_info: return None
            
            # 缠论分析 (30M 主信号)
            chan_result = self.analyze_with_chan(code)
            if not chan_result: return None
            
            bsp_type = chan_result.get('bsp_type', '未知')
            is_buy = chan_result.get('is_buy_signal', False)
            bsp_time_str = chan_result.get('bsp_datetime_str', '')
            current_price = stock_info['current_price']
            
            # ML / 重复 / 持仓 过滤逻辑
            if not self._validate_and_filter_signal(code, chan_result, stock_info, is_force_scan):
                return None
            
            # 收集有效信号
            signal_data = {
                'code': code,
                'is_buy': is_buy,
                'bsp_type': bsp_type,
                'current_price': current_price,
                'position_qty': self.get_position_quantity(code),
                'lot_size': stock_info.get('lot_size', 100),
                'chan_result': chan_result,
                'name': name
            }
            
            # 记录已发现
            if bsp_time_str:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sig_key_strict = f"STRICT_{code}_{bsp_time_str}_{bsp_type}"
                sig_key_loose = f"LOOSE_{code}_{bsp_type}"
                self.discovered_signals[sig_key_strict] = now_str
                self.discovered_signals[sig_key_loose] = now_str
                self.discovered_signals[code] = bsp_time_str
                self._save_discovered_signals()
            
            return [signal_data]
            
        except Exception as e:
            logger.error(f"Sync Scan {code} Error: {e}")
            return None

    async def _process_candidate_signals_async(self, candidate_signals: List[Dict]) -> List[Dict]:
        """封装图表生成和评分流程 (基于 asyncio)"""
        signals_with_charts = []
        # ⚓ [5M 逃顶修复关键] 紧急逃顶信号单独收集，绝对不走 AI 视觉评分（避免 KeyError 静默丢失）
        urgent_escape_signals = []

        for signal in candidate_signals:
            # ⚓ [5M 逃顶离场 Phase 8] 紧急离场信号跳过视觉与ML，赋满分直接逃命
            is_escape = signal.get('chan_result', {}).get('is_escape_exit', False)
            if is_escape:
                self.log_message.emit(f"🚀 [5M 逃顶逃离] {signal['code']} 紧急离场生效，豁免视觉/ML校验")
                signal['score'] = 100
                signal['urgent_exit'] = True
                urgent_escape_signals.append(signal)  # ← 单独收集，不加入 signals_with_charts
                continue
                
            chan_analysis = signal.get('chan_result', {}).get('chan_analysis', {})
            chan_30m = chan_analysis.get('chan_30m')
            bsp_type_display = f"{'b' if signal['is_buy'] else 's'}{signal['bsp_type']}"
            
            # --- 0. [自愈加固] 20分钟 Cooldown 降温线 ---
            code = signal['code']
            if hasattr(self, 'trade_cooldown') and code in self.trade_cooldown:
                if (time.time() - self.trade_cooldown[code]) < 1200:
                    self.log_message.emit(f"🛡️ [港股] {code} 触发 20min 操作冷却安全期，本轮信号忽略。")
                    continue
            
            # 1. 优先提取买卖点，并进行 ML 一票否决验证
            bsp = None
            if chan_30m:
                bsp_list = chan_30m.get_bsp(idx=0)
                if bsp_list: bsp = bsp_list[-1]
                
            if bsp:
                # 1.1 买入信号 ML 验证
                if signal.get('is_buy'):
                    ml_res = self.signal_validator.validate_signal(chan_30m, bsp, threshold=self.ml_threshold, market_context=getattr(self, 'market_context', {}))
                    prob = ml_res.get('prob', 0)
                    signal['ml_prob'] = prob
                    if prob < self.ml_threshold:
                        self.log_message.emit(f"🤖 {signal['code']} {bsp_type_display} ML 未达标 ({prob*100:.1f}%) -> 拦截")
                        continue
                # 1.2 卖出信号 ML 验证
                else:
                    ml_res = self.signal_validator.validate_signal(chan_30m, bsp, threshold=0.60, market_context=getattr(self, 'market_context', {}))
                    prob = ml_res.get('prob', 0)
                    signal['ml_prob'] = prob
                    if prob < 0.60:
                        self.log_message.emit(f"🤖 {signal['code']} {bsp_type_display} ML 概率过低 ({prob*100:.1f}%) -> 拦截")
                        continue
            
            # 2. 图表生成 (线程内运行)
            loop = asyncio.get_event_loop()
            chart_paths = await loop.run_in_executor(None, self.generate_charts, signal['code'], chan_analysis)
            if chart_paths:
                s = signal.copy()
                s['chart_paths'] = chart_paths
                signals_with_charts.append(s)
        
        # 常规信号走 AI 评分；逃顶信号直接拼接返回，不过评分
        if urgent_escape_signals:
            self.log_message.emit(f"🚀 [5M 逃顶直通] {len(urgent_escape_signals)} 个紧急信号跳过AI评分直接提交执行")
        scored_regular = await self._batch_score_signals_async(signals_with_charts) if signals_with_charts else []
        return urgent_escape_signals + scored_regular


    def _validate_and_filter_signal(self, code, chan_result, stock_info, is_force_scan: bool = False) -> bool:
        """封装原有的信号验证和过滤逻辑，并引入与 A 股一致的去重机制"""
        is_buy = chan_result.get('is_buy_signal', False)
        bsp_type = chan_result.get('bsp_type', '未知')
        bsp_type_display = f"{'b' if is_buy else 's'}{bsp_type}"
        bsp_time_str = chan_result.get('bsp_datetime_str', '')
        
        # 0. ⚓ [5M 逃顶特权 Phase 8] 若为紧急离场，直接放行，仅在最终阶段屏蔽同单
        is_escape = chan_result.get('is_escape_exit', False)
        position_qty = self.get_position_quantity(code)
        if is_escape:
            if not is_buy and position_qty <= 0:
                 self.log_message.emit(f"⏭️ {code} 紧急逃顶触发，但当前无持仓(0股)，略过。")
                 return False
            self.log_message.emit(f"🚀 {code} 触发紧急逃逸豁免通道，跳过常规过滤。")
            return True
            
        # 1. 持仓方向校验
        position_qty = self.get_position_quantity(code)
        if is_buy and position_qty > 0: 
            self.log_message.emit(f"⏭️ {code} {bsp_type_display} 已有持仓({position_qty})，跳过买入信号")
            return False
        if not is_buy and position_qty <= 0: 
            self.log_message.emit(f"⏭️ {code} {bsp_type_display} 无持仓，跳过卖出信号")
            return False

        # 2. 核心去重逻辑 (Phase 4 Alignment)
        now = datetime.now()
        # 2.1 严格去重 (代码 + 信号K线时间 + 类型) -> 防止同一根K线反复报
        sig_key_strict = f"STRICT_{code}_{bsp_time_str}_{bsp_type}"
        # 2.2 宽松去重 (代码 + 类型) -> 处理“漂移”或“重现”的同一信号 (4小时保护期)
        sig_key_loose = f"LOOSE_{code}_{bsp_type}"
        
        if sig_key_strict in self.discovered_signals:
            self.log_message.emit(f"⏭️ {code} {bsp_type_display} 该K线信号此前已发现过并已处理（严格去重），跳过")
            return False
            
        # 2.2 宽松去重 (针对交易系统，仅进行日志记录，不拦截执行，防止漏下单)
        if sig_key_loose in self.discovered_signals:
            last_notify_info = self.discovered_signals[sig_key_loose]
            try:
                last_time = datetime.strptime(last_notify_info, "%Y-%m-%d %H:%M:%S")
                diff_sec = (now - last_time).total_seconds()
                if diff_sec < 14400: # 4小时保护期
                    self.log_message.emit(f"ℹ️ {code} {bsp_type_display} 在 4h 宽松去重保护期内，但交易系统继续执行校验")
            except Exception as e:
                logger.error(f"解析信号记录时间报错: {e}")

        # 3. 挂单校验 (如果有相同方向正在进行中的订单，不要重复下单)
        if self.check_pending_orders(code, 'BUY' if is_buy else 'SELL'):
            self.log_message.emit(f"⏭️ {code} {bsp_type_display} 已有相同方向挂单，跳过")
            return False

        # 4. 多周期共振过滤 (优化 A: 30M+5M 严苛嵌套)
        from config import TRADING_CONFIG
        enable_resonance_5m = TRADING_CONFIG.get('enable_resonance_5m', True)
        chan_5m = chan_result.get('chan_analysis', {}).get('chan_5m')
        
        if enable_resonance_5m and chan_5m:
            bsp_5m_list = chan_5m.get_latest_bsp(number=0)
            if not bsp_5m_list:

                self.log_message.emit(f"⚠️ [港股] {code} {bsp_type_display} 30M 信号未获得 5M 共振确认 (5M无任何信号)，拦截")
                return False
            
            # 获取绝对最新的 5M 信号进行验证
            sorted_5m = sorted(bsp_5m_list, key=lambda x: str(x.klu.time), reverse=True)
            latest_b = sorted_5m[0]
            b_dt = datetime(latest_b.klu.time.year, latest_b.klu.time.month, latest_b.klu.time.day, 
                           latest_b.klu.time.hour, latest_b.klu.time.minute, latest_b.klu.time.second)
            
            # 硬性标准：1. 方向必须一致(确保中间没反转); 2. 5M信号必须在30分钟内产生
            is_same_dir = (latest_b.is_buy == is_buy)
            is_recent = (now - b_dt).total_seconds() < 1800  # 30分钟
            
            if not is_same_dir:
                self.log_message.emit(f"⚠️ [港股] {code} {bsp_type_display} 5M 确认失败: 5M 最新信号为反向 {latest_b.type2str()} @ {latest_b.klu.time}")
                return False
            if not is_recent:
                self.log_message.emit(f"⚠️ [港股] {code} {bsp_type_display} 5M 确认失败: 5M 最新信号 {latest_b.type2str()} 已过时(>30min) @ {latest_b.klu.time}")
                return False
                
            self.log_message.emit(f"💎 [港股] {code} {bsp_type_display} 30M+5M 多周期共振确认成功 (最新5M信号: {latest_b.type2str()})")

        return True

    def _process_candidate_signals(self, candidate_signals: List[Dict]) -> List[Dict]:
        """封装图表生成和评分流程 (P1 加强: 先 ML 过滤，达标再绘图)"""
        signals_with_charts = []
        for signal in candidate_signals:
            chan_analysis = signal.get('chan_result', {}).get('chan_analysis', {})
            chan_30m = chan_analysis.get('chan_30m')
            bsp_type_display = f"{'b' if signal['is_buy'] else 's'}{signal['bsp_type']}"
            
            # 1. 优先提取买卖点，并进行 ML 一票否决验证 (针对买入信号)
            bsp = None
            if chan_30m:
                bsp_list = chan_30m.get_bsp(idx=0)
                if bsp_list: bsp = bsp_list[-1]
                
            if bsp:
                # 1.1 买入信号 ML 验证 (严格阈值)
                if signal.get('is_buy'):
                    ml_res = self.signal_validator.validate_signal(chan_30m, bsp, threshold=self.ml_threshold, market_context=getattr(self, 'market_context', {}))
                    prob = ml_res.get('prob', 0)
                    signal['ml_prob'] = prob
                    
                    if prob < self.ml_threshold:
                        self.log_message.emit(f"🤖 {signal['code']} {bsp_type_display} ML 未达标 ({prob*100:.1f}% < {self.ml_threshold*100:.0f}%) -> 拦截")
                        continue
                    else:
                        self.log_message.emit(f"🤖 {signal['code']} {bsp_type_display} ML 校验通过 ({prob*100:.1f}%)")
                # 1.2 卖出信号 ML 验证 (优化 D: 增加 0.4 阈值过滤，防止假卖点)
                else:
                    ml_res = self.signal_validator.validate_signal(chan_30m, bsp, threshold=0.60, market_context=getattr(self, 'market_context', {}))
                    prob = ml_res.get('prob', 0)
                    signal['ml_prob'] = prob
                    if prob < 0.60:
                        self.log_message.emit(f"🤖 {signal['code']} {bsp_type_display} ML 概率过低 ({prob*100:.1f}% < 60%) -> 拦截假卖点")
                        continue
                    else:
                         self.log_message.emit(f"🤖 {signal['code']} {bsp_type_display} ML 卖点验证通过 ({prob*100:.1f}%)")
            
            # 2. 只有 ML 达标后，才生成图表 (降低系统开销)
            chart_paths = self.generate_charts(signal['code'], chan_analysis)
            if chart_paths:
                s = signal.copy()
                s['chart_paths'] = chart_paths
                if 'ml_prob' in signal:
                    s['ml_prob'] = signal['ml_prob']
                signals_with_charts.append(s)
        

    def _execute_trades(self, all_signals: List[Dict], available_funds_at_start: float, total_assets: float = 0.0) -> Tuple[List[Dict], int, int, float]:
        """
        执行交易 - 第四步
        """
        # 检查熔断机制
        if self.risk_manager.check_circuit_breaker():
            self.log_message.emit("⚠️ 熔断机制激活，暂停所有交易操作")
            return [], [], 0, 0, available_funds_at_start
            
        # ==============================================================
        # Trailing Stop-Loss (移动追踪止损) 检查
        # 独立于缠论信号，基于当前实时价格与历史最高价的回撤距离来触发
        # ==============================================================
        self._check_trailing_stops()
        
        # 分离并排序信号
        sell_signals = [s for s in all_signals if not s['is_buy']]
        buy_signals = [s for s in all_signals if s['is_buy']]
        
        # 按评分从高到低排序
        sell_signals.sort(key=lambda x: x['score'], reverse=True)
        buy_signals.sort(key=lambda x: x['score'], reverse=True)
        
        self.log_message.emit(f"卖出信号: {len(sell_signals)}个, 买入信号: {len(buy_signals)}个")
        
        # 执行卖点（优先）
        available_funds = available_funds_at_start
        executed_sell = 0
        executed_buy = 0
        
        if sell_signals:
            self.log_message.emit(f"\n>>> 开始执行卖出操作（共{len(sell_signals)}个）")
            for i, signal in enumerate(sell_signals, 1):
                code = signal['code']
                name = signal.get('name', '')
                score = signal['score']
                qty = signal['position_qty']
                if qty <= 0:
                    self.log_message.emit(f"⏭️ {code} 当前持仓量为 0，跳过卖出执行")
                    continue
                
                price = signal['current_price']
                bsp_type = signal['bsp_type']
                
                self.log_message.emit(f"\n[{i}/{len(sell_signals)}] 卖出 {code} ({name}) - {bsp_type} - 评分: {score}")
                
                # 检查是否可以执行交易
                is_urgent = signal.get('urgent_exit', False)
                if not is_urgent and not self.risk_manager.can_execute_trade(code, score):
                    self.log_message.emit(f"⚠️ 风险管理限制，跳过卖出 {code}")
                    continue
                
                # 只有视觉评分 >= 阈值才执行交易 (紧急模式豁免)
                if is_urgent or score >= self.min_visual_score:
                    if is_urgent:
                        self.log_message.emit(f"🚀 {code} 属于紧急逃逸，豁免得分门槛({self.min_visual_score})，立即下单！")
                    
                    # 临时保存元数据用于 execute_trade 内部持久化
                    self._last_signal_type = bsp_type
                    self._last_ml_prob = signal.get('ml_prob', 0)
                    self._last_visual_score = score
                    self._last_exit_reason = "逃顶离场" if is_urgent else "信号卖出"
                    
                    if self.execute_trade(code, 'SELL', qty, price, score=score, urgent=is_urgent):
                        # 卖出成功，释放资金，更新信号历史记录
                        released_funds = price * qty
                        available_funds += released_funds
                        executed_sell += 1
                        
                        # 记录交易到风险管理器
                        self.risk_manager.record_trade(code, 'SELL', qty, price, score, pnl=released_funds)
                        
                        # 记录已执行信号，防止重复处理同一信号
                        bsp_time_str = signal.get('chan_result', {}).get('bsp_datetime_str', '')
                        if bsp_time_str:
                            self.executed_signals[code] = bsp_time_str
                            self._save_executed_signals()
                            
                        self.log_message.emit(f"✅ 卖出成功 {code} ({name}), 释放资金: {released_funds:.2f}, 当前可用: {available_funds:.2f}")
                    else:
                        self.log_message.emit(f"❌ 卖出失败 {code} ({name})")
                else:
                    self.log_message.emit(f"⏭️ 卖出信号 {code} ({name}) 评分({score})低于阈值({self.min_visual_score})，仅通知不执行")
        
        # 执行买点 - 使用风险管理器进行动态仓位控制
        if buy_signals:
            self.log_message.emit(f"\n>>> 开始执行买入操作（共{len(buy_signals)}个）")
            
            # 获取最大持仓限制
            max_total_stocks = TRADING_CONFIG.get('max_total_positions', 10)  # 从配置获取，默认为 10
            
            # 查询当前实际持仓数量（从富途API实时获取，而非仅依赖本轮计数器）
            current_position_count = 0
            try:
                # self.trd_ctx 属性会自动处理延迟初始化
                refresh = (self.trd_env == TrdEnv.SIMULATE)
                ret, data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=False)
                if ret == RET_OK and not data.empty:
                    # 只计算持仓数量 > 0 的股票
                    held = data[data['qty'].astype(float) > 0]
                    current_position_count = len(held)
                    self.log_message.emit(f"📊 当前实际持仓: {current_position_count}只股票")
            except Exception as e:
                self.log_message.emit(f"⚠️ 查询持仓数量异常: {e}，将使用保守限制")
            
            remaining_slots = max(0, max_total_stocks - current_position_count)
            stocks_bought = 0  # 本轮已买入股票数量
            
            for i, signal in enumerate(buy_signals, 1):
                # 检查是否已达到最大买入股票数量
                if stocks_bought >= remaining_slots:
                    self.log_message.emit(f"✅ 已达到最大持仓数量限制（当前持仓{current_position_count}+本轮买入{stocks_bought}={current_position_count+stocks_bought}只，上限{max_total_stocks}只），停止买入")
                    break
                
                code = signal['code']
                name = signal.get('name', '')
                score = signal['score']
                price = signal['current_price']
                bsp_type = signal['bsp_type']
                lot_size = signal.get('lot_size', 100)  # 获取股票的最小手数
                
                # 检查熔断和交易频率限制
                if not self.risk_manager.can_execute_trade(code, score):
                    self.log_message.emit(f"⚠️ 风险管理限制，跳过买入 {code} ({name})")
                    continue
                
                # 检查可用资金是否小于5万元，如果是则停止买入
                if available_funds < 50000:
                    self.log_message.emit(f"💰 可用资金({available_funds:.2f})少于5万元，停止买入操作")
                    break
                
                # 只有视觉评分 >= 阈值才执行交易
                if score >= self.min_visual_score:
                    # 获取该股票近乎最近的数据以计算 ATR
                    atr_value = None
                    atr_multiplier = 2.0
                    chan_res = signal.get('chan_result', {})
                    chan_analysis = chan_res.get('chan_analysis', {})
                    # 尝试从30M或其它可用级别计算 ATR
                    chan_30m = chan_analysis.get('chan_30m')
                    if chan_30m is not None and len(chan_30m[0]) > 0:
                        try:
                            kl_list = list(chan_30m[0].klu_iter())
                            atr_value = self._calculate_atr(kl_list, period=14)
                            self.log_message.emit(f"{code} ({name}) 波动率诊断: ATR={atr_value:.3f}")
                        except Exception as e:
                            import traceback
                            self.log_message.emit(f"⚠️ {code} ({name}) ATR 计算失败: {e}\n{traceback.format_exc()}")
                    else:
                        self.log_message.emit(f"⚠️ {code} ({name}) 无可用 chan_30m 数据用于计算 ATR，将使用固定20%仓位。")
                    
                    # 使用风险管理器计算动态仓位，通过 ATR 限额
                    buy_quantity = self.risk_manager.calculate_position_size(
                        code=code,
                        available_funds=available_funds,
                        current_price=price,
                        signal_score=score,
                        risk_factor=1.0,
                        atr=atr_value,
                        atr_multiplier=atr_multiplier,
                        total_assets=total_assets,
                        lot_size=lot_size,
                        ml_prob=signal.get('ml_prob') # Phase 7: 传入 ML 概率
                    )
                    
                    # 二次校验与强制舍入（双重保险，增加零值保护）
                    if lot_size > 0:
                        buy_quantity = (buy_quantity // lot_size) * lot_size
                    else:
                        self.log_message.emit(f"⚠️ {code} 手数信息异常(0)，无法买入")
                        buy_quantity = 0
                    
                    if buy_quantity <= 0:
                        self.log_message.emit(f"[{i}/{len(buy_signals)}] {code} 风险管理器建议不买入或资金不足 (计算股数: {buy_quantity})")
                        continue
                    
                    required_funds = price * buy_quantity
                    
                    # 检查可用资金是否足够
                    if required_funds > available_funds:
                        self.log_message.emit(f"[{i}/{len(buy_signals)}] {code} 资金不足，需要{required_funds:.2f}，可用{available_funds:.2f}，跳过")
                        continue
                    
                    lots_can_buy = buy_quantity // lot_size
                    self.log_message.emit(f"\n[{i}/{len(buy_signals)}] 买入 {code} - {bsp_type} - 评分: {score}")
                    self.log_message.emit(f"   计划买入: {buy_quantity}股 ({lots_can_buy}手), 预计花费: {required_funds:.2f}")
                    
                    # 临时保存元数据用于 execute_trade 内部持久化 (优化 F)
                    self._last_signal_type = bsp_type
                    self._last_ml_prob = signal.get('ml_prob', 0)
                    self._last_visual_score = score
                    
                    if self.execute_trade(code, 'BUY', buy_quantity, price, score=score, risk_params={'signal_score': score, 'atr': atr_value, 'atr_multiplier': atr_multiplier, 'ml_prob': signal.get('ml_prob', 0), 'lot_size': lot_size}):
                        # 买入成功，扣除资金，更新信号历史记录
                        available_funds -= required_funds
                        executed_buy += 1
                        stocks_bought += 1  # 增加已买入股票计数
                        
                        # 记录交易到风险管理器
                        self.risk_manager.record_trade(code, 'BUY', buy_quantity, price, score)
                        
                        # 记录已执行信号，防止重复处理同一信号
                        bsp_time_str = signal.get('chan_result', {}).get('bsp_datetime_str', '')
                        if bsp_time_str:
                            self.executed_signals[code] = bsp_time_str
                            self._save_executed_signals()
                        
                        # 初始化分阶段移动止损基准值 (方案丙)
                        if atr_value and atr_value > 0:
                            self.position_trackers[code] = {
                                'highest_price': price,
                                'atr': atr_value,
                                'entry_price': price,
                                'trail_active': False,
                                'bars_held': 0 # Phase 7: 记录持仓 K 线数用于时间止损
                            }
                            self._subscribe_stock_quote(code)  # 📡 [极速风控] 开启实时推送价格
                            self.log_message.emit(f"🛡️ {code} 已启动分阶段双重止损监控: 初始价={price:.3f}, ATR={atr_value:.3f}")
                            
                        self.log_message.emit(f"✅ 买入成功 {code}, 剩余资金: {available_funds:.2f}, 已买入{stocks_bought}/{remaining_slots}只(总持仓{current_position_count+stocks_bought}/{max_total_stocks})")
                    else:
                        self.log_message.emit(f"❌ 买入失败 {code}")
                else:
                    self.log_message.emit(f"⏭️ 买入信号 {code} 评分({score})低于阈值({self.min_visual_score})，仅通知不执行")
        
        self.log_message.emit(f"\n扫描交易完成，最终可用资金: {available_funds:.2f}")
        return sell_signals, buy_signals, executed_sell, executed_buy, available_funds

    def close_connections(self):
        """关闭 Futu 连接"""
        try:
            self.quote_ctx.close()
            self.trd_ctx.close()
        except Exception as e:
            logger.error(f"关闭 Futu 连接时出错: {e}")

    def _calculate_atr(self, kline_list: List, period: int = 14) -> float:
        """
        计算 ATR（Average True Range）
        """
        if not kline_list or len(kline_list) < period + 1:
            return 0.0
            
        import numpy as np
        
        tr_list = []
        # 从最后往前获取所需数量的K线，多取1根用于计算 TR
        klines_for_atr = kline_list[-(period+1):]
        
        for i in range(1, len(klines_for_atr)):
            current = klines_for_atr[i]
            previous = klines_for_atr[i-1]
            
            high = current.high
            low = current.low
            prev_close = previous.close
            
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            
            tr = max(tr1, tr2, tr3)
            tr_list.append(tr)
            
        # 简单移动平均计算 ATR
        if not tr_list:
            return 0.0
            
        mean_atr = float(np.mean(tr_list))
        # 💡 [保底风控] 强制 1.5% 安全垫底限，屏蔽自然点差产生的秒卖
        current_price = kline_list[-1].close if kline_list else 0
        if current_price > 0:
            return max(mean_atr, current_price * 0.015)
        return mean_atr

    def _check_5m_escape_for_holdings(self):
        """
        🔥 [5M 逃顶快速路 Phase 8+]
        独立于 30M 扫描节奏，每 5 分钟单独为所有持仓股检测 5M 缠论卖点。
        一旦发现卖点且无在单，立即将卖出指令注入 cmd_queue，完全绕开 30M Bar 换挡等待。
        """
        if not hasattr(self, 'position_trackers') or not self.position_trackers:
            return
        if not self.is_trading_time():
            return

        codes_to_check = list(self.position_trackers.keys())
        if not codes_to_check:
            return

        self.log_message.emit(f"🔍 [5M 逃顶快速轮询] 对 {len(codes_to_check)} 只持仓股快速检查 5M 卖点...")

        now = datetime.now()
        end_time_5m_str = now.strftime("%Y-%m-%d %H:%M:%S")
        start_time_5m_str = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

        # 🛡️ [API频率保护 Phase 9] 一站式预拉取全量持仓和待成交状态，杜绝 Loop 中频繁触发 API
        pending_orders_codes = set()
        positions_qty_map = {}
        try:
            with self.futu_api_lock:
                 ret_ord, ord_data = self.trd_ctx.order_list_query(trd_env=self.trd_env)
                 if ret_ord == RET_OK and not ord_data.empty:
                     from futu import TrdSide, OrderStatus
                     status_col = 'order_status' if 'order_status' in ord_data.columns else 'status'
                     active_statuses = [OrderStatus.SUBMITTING, OrderStatus.SUBMITTED, OrderStatus.WAITING_SUBMIT]
                     # 专门看 SELL 待成交
                     orders_active = ord_data[ord_data[status_col].isin(active_statuses) & (ord_data['trd_side'] == TrdSide.SELL)]
                     pending_orders_codes = set(orders_active['code'].tolist())
                 # self.trd_ctx 属性会自动处理延迟初始化
                 refresh = (self.trd_env == TrdEnv.SIMULATE)
                 ret_pos, pos_data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=False)
                 if ret_pos == RET_OK and not pos_data.empty:
                     for _, prow in pos_data.iterrows():
                          positions_qty_map[prow['code']] = int(prow['qty'])
        except Exception as e_pull:
             self.log_message.emit(f"⚠️ [5M 逃顶快速路] 数据批次预拉异常: {e_pull}")

        for code in codes_to_check:
            try:
                # 检查是否已有卖单（避免重复下单）
                if code in pending_orders_codes:
                    continue

                # 确认仍有持仓
                pos_qty = positions_qty_map.get(code, 0)
                if pos_qty <= 0:
                    continue

                # 独立 5M CChan 实例
                chan_5m = CChan(
                    code=code,
                    begin_time=start_time_5m_str,
                    end_time=end_time_5m_str,
                    data_src="custom:HybridFutuAPI.HybridFutuAPI",
                    lv_list=[KL_TYPE.K_5M],
                    config=self.chan_config
                )
                latest_bsps_5m = chan_5m.get_latest_bsp(idx=0, number=1)
                if not latest_bsps_5m:
                    continue

                bsp_5m = latest_bsps_5m[0]
                if bsp_5m.is_buy:
                    continue  # 只处理卖点

                bsp_ctime_5m = bsp_5m.klu.time
                bsp_time_5m = datetime(bsp_ctime_5m.year, bsp_ctime_5m.month, bsp_ctime_5m.day,
                                       bsp_ctime_5m.hour, bsp_ctime_5m.minute, bsp_ctime_5m.second)

                # 🕐 时效过滤：只接受最近 1 根 5M K 线内的卖点（即最多 5 分钟前）
                is_stale = (now - bsp_time_5m).total_seconds() > 310

                escape_key = f"ESCAPE_{code}_{bsp_time_5m.strftime('%Y%m%d%H%M')}"
                if escape_key in self.discovered_signals:
                    # 🕐 时效保质期拦截 [风控加固 Phase 9]：避免几天前触发的逃离锁对未来手动建仓产生误杀
                    is_too_old_for_healing = (now - bsp_time_5m).total_seconds() > 3600  # 1 小时前强力冷却
                    if is_too_old_for_healing:
                        continue
                    
                    # 该时间戳已触发过（但可能是漏单了），自愈逻辑：无在单时强制再次发出
                    self.log_message.emit(f"🚨🚨 [5M 快速自愈] {code} 5M 卖点曾报过但无在单，强制再发逃避出单！")
                else:
                    if is_stale:
                        # 对于全新的未发现信号，如果是过期的，就不当作逃顶处理
                        continue
                        
                    self.discovered_signals[escape_key] = bsp_time_5m.strftime("%Y-%m-%d %H:%M:%S")
                    self.log_message.emit(f"🚨🚨 [5M 逃顶快速路] {code} 发现 5M 卖点 ({bsp_5m.type2str()}) @ {bsp_5m.klu.close}，立即出单！")

                # 直接塞入交易队列，urgent=True 使用穿透限价单
                import time as _time
                current_price = bsp_5m.klu.close
                self.cmd_queue.put((-100, _time.time(), 'EXECUTE_TRADE', {
                    'code': code,
                    'action': 'SELL',
                    'quantity': pos_qty,
                    'price': current_price,
                    'urgent': True,
                    'exit_reason': '5M逃顶快速路',
                    'risk_params': None
                }))

            except Exception as e:
                self.log_message.emit(f"⚠️ [5M 逃顶快速路] {code} 异常（非致命）: {e}")

    def _check_trailing_stops(self):
        """
        检查所有在池中的持仓是否触发移动止损
        """
        from config import TRADING_CONFIG
        if not TRADING_CONFIG.get('enable_stop_loss', True):
            return
            
        if not hasattr(self, 'position_trackers') or not self.position_trackers:
            return

        # 周期性显示追踪信息保护心跳
        if not hasattr(self, '_last_atr_summary_time'):
            self._last_atr_summary_time = time.time() - 3600 # 初始立刻触发
            
        import time
        if time.time() - self._last_atr_summary_time >= 1800 and self.position_trackers:
            self.log_message.emit(f"🔍 [港股-风控] ATR心跳: 正在为 {len(self.position_trackers)} 只标的提供动态止损监控。")
            self._last_atr_summary_time = time.time()

        codes_to_check = list(self.position_trackers.keys())
        for code in codes_to_check:
            # 🚀 [性能优化 Phase 8] 移除循环内的 get_position_quantity 实时查询
            # 只有当真跌破止损阈值准备下单时，才去向远端 API 校验真实持仓
            # 极大程度释放并发心跳中的 API 频控压力
                
            # 🚀 [极速数据线] 从内存推送读取最新报价，降滑点，释放 API 配额
            current_price = getattr(self, 'live_prices', {}).get(code, 0.0)
            if current_price <= 0:
                info = self.get_stock_info(code)  # 容错降级
                if not info or info.get('current_price', 0) <= 0:
                    continue
                current_price = info['current_price']
                if not hasattr(self, 'live_prices'): self.live_prices = {}
                self.live_prices[code] = current_price  # 补齐缓存
                
            tracker = self.position_trackers[code]
            
            # 3. 更新最高价
            if current_price > tracker['highest_price']:
                tracker['highest_price'] = current_price
                self.log_message.emit(f"📈 {code} 创持仓新高: {current_price:.3f}")
                
            # 4. 判断止损 (方案丙)
            highest = tracker['highest_price']
            entry_price = tracker.get('entry_price', current_price)
            atr = tracker['atr']
            
            from config import TRADING_CONFIG
            atr_stop_init = TRADING_CONFIG.get('atr_stop_init', 1.2)
            # 🚀 [Phase 11] 使用针对港股优化的 1.5 ATR 移动止损
            atr_stop_trail = self.atr_stop_trail
            atr_profit_threshold = TRADING_CONFIG.get('atr_profit_threshold', 1.5)

            # 检查是否达标开启移动止损
            if not tracker.get('trail_active', False):
                has_reached_threshold = (current_price - entry_price) >= (atr * atr_profit_threshold)
                if has_reached_threshold:
                    tracker['trail_active'] = True
                    self.log_message.emit(f"🔓 {code} 已达获利门槛(${current_price:.2f} >= +{atr_profit_threshold}*ATR)，切换为移动止损模式")
                    
            bsp_type_str = tracker.get('signal_type', '未知')
            if tracker.get('trail_active', False):
                # 移动止损：最高价回撤 atr_stop_trail * ATR
                stop_price = tracker['highest_price'] - (atr * atr_stop_trail)
                stop_type = "ATR移动止盈"
            else:
                # 🛡️ [分档式止损 Phase 8] 1买放大至 1.5x 防穿针
                current_stop_init = atr_stop_init
                if "1买" in bsp_type_str:
                    current_stop_init = 1.5
                elif "2买" in bsp_type_str or "3买" in bsp_type_str:
                    current_stop_init = 1.2
                    
                stop_price = entry_price - (atr * current_stop_init)
                stop_type = "ATR初始止损"
                
            if current_price < stop_price:
                self.log_message.emit(f"🚨 [HK-风控] {code} 触发{stop_type}! 最高价={highest:.2f}, 现价={current_price:.2f}, 止损位={stop_price:.2f}")
                
                # 触发止损前，现场校验真实持仓数量
                qty = self.get_position_quantity(code)
                if qty <= 0:
                    self.log_message.emit(f"🔄 {code} 已无真实持仓，跳过抛售并停止追踪")
                    del self.position_trackers[code]
                    self._unsubscribe_stock_quote(code) # 🚫 释放推送配额
                    continue
                
                # 尝试强制抛售所有持仓
                if self.execute_trade(code, 'SELL', qty, current_price, urgent=True):
                    self.log_message.emit(f"✅ {code} 止损抛售成功: {qty} 股")
                    del self.position_trackers[code]
                    self._unsubscribe_stock_quote(code) # 🚫 释放推送配额
                    from Common.CTime import CTime
                    from datetime import datetime
                    now = datetime.now()
                    self.structure_barrier[code] = {
                        'lock_time_ts': CTime(now.year, now.month, now.day, now.hour, now.minute).ts
                    }
                    self.risk_manager.record_trade(code, 'SELL', qty, current_price, signal_score=0, pnl=0)
                else:
                    self.log_message.emit(f"❌ {code} 止损抛售失败，将在此后循环继续尝试。")
                continue

            # Phase 7: 5M 级别快速回撤保护利润
            # 如果正处于盈利状态且已经激活移动止损，若回撤超过 1.0 ATR (哪怕还没到 2.5 倍移动位) 则提前止盈
            if tracker.get('trail_active', False) and (highest - current_price) > (1.0 * atr):
                 self.log_message.emit(f"⚡ [HK-风控] {code} 触发快速回撤保护(回撤 > 1.0 ATR)，提前止盈。")
                 
                 qty = self.get_position_quantity(code)
                 if qty <= 0:
                     self.log_message.emit(f"🔄 {code} 已无真实持仓，跳过抛售并停止追踪")
                     del self.position_trackers[code]
                     self._unsubscribe_stock_quote(code) # 🚫 释放推送配额
                     continue

                 if self.execute_trade(code, 'SELL', qty, current_price, urgent=True):
                    del self.position_trackers[code]
                    self._unsubscribe_stock_quote(code) # 🚫 释放推送配额
                    from Common.CTime import CTime
                    from datetime import datetime
                    now = datetime.now()
                    self.structure_barrier[code] = {
                        'lock_time_ts': CTime(now.year, now.month, now.day, now.hour, now.minute).ts
                    }
                    self.risk_manager.record_trade(code, 'SELL', qty, current_price, signal_score=0, pnl=0)
                 continue

    def check_pending_orders(self, code: str, side: str) -> bool:
        """
        检查是否有针对该股票的同向待成交订单
        
        Args:
            code: 股票代码
            side: 'BUY' or 'SELL'
            
        Returns:
            True 如果存在待成交订单
        """
        try:
            ret, data = self.trd_ctx.order_list_query(trd_env=self.trd_env)
            if ret == RET_OK and not data.empty:
                # 兼容 futu API 返回的字段名可能是 order_status 或 status
                status_col = 'order_status' if 'order_status' in data.columns else 'status'
                if status_col in data.columns:
                    # 过滤出正在处理的订单
                    active_statuses = [OrderStatus.SUBMITTING, OrderStatus.SUBMITTED, OrderStatus.WAITING_SUBMIT]
                    data = data[data[status_col].isin(active_statuses)]
                    futu_side = TrdSide.BUY if side.upper() == 'BUY' else TrdSide.SELL
                    # 过滤出对应代码和方向的活跃订单
                    pending = data[(data['code'] == code) & (data['trd_side'] == futu_side)]
                    if not pending.empty:
                        self.log_message.emit(f"{code} 发现已有 {side} 待成交订单，订单ID: {pending.iloc[0]['order_id']}")
                        return True
            return False
        except Exception as e:
            self.log_message.emit(f"检查待成交订单异常 {code}: {e}")
            return False

    def calculate_trading_hours(self, start_time: datetime, end_time: datetime) -> float:
        """调用公共工具类计算交易时长"""
        try:
            return calc_trading_duration(start_time, end_time)
        except Exception as e:
            logger.error(f"Error in calculate_trading_hours: {e}")
            return 0.0

    def get_position_quantity(self, code: str) -> int:
        """
        🚀 [影子账本查询] 获取股票持仓数量
        耗时 0ms，彻底避开 API 限频与结算延迟。
        """
        return self.position_cache.get(code, 0)
             
        try:
            with self.futu_api_lock:
                refresh = (self.trd_env == TrdEnv.SIMULATE)
                # 💡 [核心修复] 先刷新账户信息唤醒后端
                if refresh:
                    self.trd_ctx.accinfo_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=True)
                    time.sleep(1.0) # ⏳ [Resilience] 给予后端同步持仓列表的缓冲时间
                
                # 💡 [补强] 尝试带 refresh 抓取，若失败且是模拟盘，重试一次
                ret, data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=refresh)
                if ret != RET_OK and refresh:
                    time.sleep(1.0)
                    ret, data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=True)

                if ret == RET_OK and not data.empty:
                    position = data[data['code'] == code]
                    if not position.empty:
                        qty = int(position.iloc[0]['qty'])
                        self.position_cache[code] = qty
                        return qty
                elif ret != RET_OK:
                    logger.warning(f"获取持仓 API 返回异常 {code}: {data}, 将返回内存缓存值")
            return self.position_cache.get(code, 0)
        except Exception as e:
            logger.error(f"获取持仓异常 {code}: {e}")
            return self.position_cache.get(code, 0)

    async def _sync_positions_async(self):
        """主动从柜台同步全量持仓快照到内存缓存，并清理僵尸追踪标的"""
        try:
            from futu import RET_OK
            loop = asyncio.get_event_loop()
            
            def query_positions_and_funds():
                with self.futu_api_lock:
                    refresh = (self.trd_env == TrdEnv.SIMULATE)
                    # 💡 [核心修复] 强制双重刷新：accinfo 唤醒 -> position_list 同步
                    ret_acc, acc_data = self.trd_ctx.accinfo_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=refresh)
                    
                    if refresh:
                        time.sleep(1.0) # ⏳ [Resilience] 模拟盘必须等待，否则持仓列表大概率不刷新
                    
                    # 💡 [核心补强] position_list 也使用 refresh_cache=refresh，但需处理“未准备好”的报错
                    ret_pos, pos_data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=refresh)
                    
                    # 💡 [容错自愈] 若 refresh 模式下 pos 报错“未准备好”，等待并重试一次 refresh
                    if ret_pos != RET_OK and refresh:
                        self.log_message.emit("⌛ [HK-同步] 持仓数据尚未就绪，正在重试强制刷新...")
                        time.sleep(1.0)
                        ret_pos, pos_data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=True)
                        
                    # 💡 [最终兜底] 若 refresh 依旧失败，尝试读一次本地缓存模式
                    if ret_pos != RET_OK and refresh:
                        ret_pos, pos_data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=False)
                    
                    return (ret_pos, pos_data), (ret_acc, acc_data)
            
            # 🚀 [影子账本-HK-预览] 在同步前先加载底仓，确保 UI 响应极速
            manual_hk_pos = {
                'HK.00699': {'qty': 5000, 'cost': 14.31, 'name': '均胜电子'}
            }
            preview_positions = []
            for m_code, m_info in manual_hk_pos.items():
                preview_positions.append({
                    'symbol': m_code.split('.')[-1],
                    'code': m_code,
                    'name': m_info['name'],
                    'qty': m_info['qty'],
                    'mkt_value': m_info['qty'] * m_info['cost'],
                    'pnl_ratio': 0.0,
                    'avg_cost': m_info['cost']
                })
            # 发射一次预览信号，防止 API 挂起导致 UI 长时间黑屏
            self.funds_updated.emit(0.0, 0.0, 0.0, preview_positions)

            (ret_pos, pos_data), (ret_acc, acc_data) = await loop.run_in_executor(None, query_positions_and_funds)
            
            def safe_float(v, default=0.0):
                try:
                    if v is None or v == 'N/A' or v == '': return default
                    return float(v)
                except: return default

            # Initialize basic structures
            new_cache = {}
            positions_list = []
            total_pos_mkt_val = 0.0

            if ret_pos == RET_OK:
                if not pos_data.empty:
                    for _, row in pos_data.iterrows():
                        code = row['code']
                        qty = int(row['qty'])
                        if qty > 0:
                            mkt_val = safe_float(row.get('market_val', 0.0))
                            total_pos_mkt_val += mkt_val
                            new_cache[code] = qty
                            positions_list.append({
                                'symbol': code.split('.')[-1],
                                'code': code,
                                'name': row.get('stock_name', code.split('.')[-1]),
                                'qty': qty,
                                'mkt_value': mkt_val,
                                'pnl_ratio': safe_float(row.get('pl_ratio', 0.0)),
                                'avg_cost': safe_float(row.get('cost_price', 0.0))
                            })
            else:
                # 💡 [影子账本自愈] API 失败时，保留之前的影子缓存
                for ghost_code, ghost_qty in self.position_cache.items():
                    if ghost_qty > 0:
                        new_cache[ghost_code] = ghost_qty
                        positions_list.append({
                            'symbol': ghost_code.split('.')[-1],
                            'code': ghost_code,
                            'name': '影子持仓保持',
                            'qty': ghost_qty,
                            'mkt_value': 0.0,
                            'pnl_ratio': 0.0,
                            'avg_cost': 0.0
                        })
            
            # 🛡️ [影子账本 - 强制隔离区穿透]
            # 即使 API 返回空，也根据 hard-coded 的底仓进行补齐展示
            manual_hk_pos = {
                'HK.00699': {'qty': 5000, 'cost': 14.31, 'name': '均胜电子'}
            }
            for m_code, m_info in manual_hk_pos.items():
                # 检查是否已在列表中 (避免重复)
                if not any(p['code'] == m_code for p in positions_list):
                    new_cache[m_code] = m_info['qty']
                    positions_list.append({
                        'symbol': m_code.split('.')[-1],
                        'code': m_code,
                        'name': m_info['name'],
                        'qty': m_info['qty'],
                        'mkt_value': m_info['qty'] * m_info['cost'],
                        'pnl_ratio': 0.0,
                        'avg_cost': m_info['cost']
                    })
                    self.log_message.emit(f"🛡️ [影子账本-HK] 已从内存加载硬核底仓: {m_code}")

            self.position_cache = new_cache
            self.last_pos_sync_time = time.time()
            
            # 🚀 [行情实时刷新] 为所有持仓获取最新的 Futu 市场快照 (含影子账本)
            all_codes = [p['code'] for p in positions_list]
            if all_codes and self.quote_ctx:
                try:
                    ret_snap, snap_data = self.quote_ctx.get_market_snapshot(all_codes)
                    if ret_snap == RET_OK and not snap_data.empty:
                        for _, s_row in snap_data.iterrows():
                            s_code = s_row['code']
                            last_price = safe_float(s_row.get('last_done', 0.0))
                            if last_price <= 0: continue
                            
                            for p in positions_list:
                                if p['code'] == s_code:
                                    p['mkt_price'] = last_price
                                    # 重新计算市值和盈亏比例
                                    p['mkt_value'] = p['qty'] * last_price
                                    if p.get('avg_cost', 0) > 0:
                                        p['pnl_ratio'] = round((last_price - p['avg_cost']) / p['avg_cost'] * 100, 2)
                                    break
                except Exception as snap_e:
                    self.log_message.emit(f"⚠️ [HK-行情] 获取实时快照失败: {snap_e}")
            
            # 发射信号同步 UI
            available = 0.0; total = 0.0; today_pl = 0.0
            if ret_acc == RET_OK and not acc_data.empty:
                available = float(acc_data['cash'].iloc[0])
                total = float(acc_data['total_assets'].iloc[0])
                today_pl = float(acc_data.iloc[0].get('today_pl', 0.0))
            
            self.funds_updated.emit(available, total, today_pl, positions_list)
                
            # 🧹 [持仓大扫除] 清理 position_trackers 中的僵尸代码
            if hasattr(self, 'position_trackers'):
                trackers = list(self.position_trackers.keys())
                for code in trackers:
                    if self.position_cache.get(code, 0) <= 0:
                        self.log_message.emit(f"🧹 [HK-清理] {code} 已无持仓，移除僵尸止损追踪器。")
                        del self.position_trackers[code]
                        self._unsubscribe_stock_quote(code)
                        
            self.log_message.emit(f"🔄 [HK-持仓同步] 已同步 {len(new_cache)} 只持仓标的。")
        except Exception as e:
            self.log_message.emit(f"⚠️ [HK-持仓同步] 失败: {e}")

    def _initialize_position_trackers(self):
        """为现有持仓初始化追踪止损器"""
        self.log_message.emit("🛡️ 正在为现有持仓初始化风险监控...")
        try:
            refresh = (self.trd_env == TrdEnv.SIMULATE)
            ret, data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=False)
            if ret == RET_OK and not data.empty:
                held = data[data['qty'].astype(float) > 0]
                for _, row in held.iterrows():
                    code = row['code']
                    if code in self.position_trackers:
                        continue
                        
                    # 获取最新报价
                    info = self.get_stock_info(code)
                    if not info: continue
                    current_price = info.get('current_price', 0)
                    if current_price <= 0: continue
                    
                    # 获取数据计算 ATR
                    try:
                        now_t = datetime.now()
                        end_time = now_t.replace(minute=(now_t.minute // 30) * 30, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
                        start_time = (now_t - timedelta(days=15)).strftime("%Y-%m-%d")
                        chan = CChan(
                            code=code,
                            begin_time=start_time,
                            end_time=end_time,
                            data_src=DATA_SRC.FUTU,
                            lv_list=[KL_TYPE.K_30M],
                            config=self.chan_config
                        )
                        if chan and len(chan[0]) > 0:
                            kl_list = list(chan[0].klu_iter())
                            atr_value = self._calculate_atr(kl_list, period=14)
                            if atr_value > 0:
                                self.position_trackers[code] = {
                                    'highest_price': current_price,
                                    'atr': atr_value,
                                    'entry_price': current_price,
                                    'trail_active': False,
                                    'bars_held': 0
                                }
                                self._subscribe_stock_quote(code) # 📡 [极速风控] 开启实时推送
                                self.log_message.emit(f"🛡️ {code} 已加载移动止损监控: 现价={current_price:.3f}, ATR={atr_value:.3f}")
                    except Exception as e:
                        logger.error(f"Error calculating ATR for existing position {code}: {e}")
            self.log_message.emit("✅ 风险监控初始化完成")
        except Exception as e:
            self.log_message.emit(f"⚠️ 初始化风险监控失败: {e}")

    async def _async_evaluate_single_signal(self, session, signal: Dict) -> Optional[Dict]:
        """
        异步评估单个信号的辅助函数 (P1 加强: ML 优先一票否决)
        """
        code = signal['code']
        bsp_type = signal['bsp_type']
        
        # ⚓ [5M 逃顶豁免短路] 紧急逃顶信号 score=100，直接返回，不走 AI 视觉评分
        if signal.get('urgent_exit', False):
            self.log_message.emit(f"🚀 [5M 逃顶直通] {code} urgent_exit=True，跳过 AI 视觉，直接注入执行队列")
            return signal
        
        chart_paths = signal.get('chart_paths', [])
        bsp_time_str = signal.get('chan_result', {}).get('bsp_datetime_str', '')
        cache_key = f"{code}_{bsp_time_str}_{bsp_type}"
        bsp_type_display = f"{'b' if signal.get('is_buy') else 's'}{bsp_type}"
        
        # --- 0. ML 优先审查已在候选池循环中提前完成 ---
        ml_prob = signal.get('ml_prob', 1.0) # 已经过校验，默认安全
        
        try:
            # 检查缓存
            if cache_key in self.visual_score_cache:
                self.log_message.emit(f"⚡ {code} 命中视觉评分缓存 ({cache_key})")
                visual_result = self.visual_score_cache[cache_key]
            else:
                # 使用线程池执行器来异步调用同步的evaluate方法
                loop = asyncio.get_event_loop()
                visual_result = await loop.run_in_executor(None, self.visual_judge.evaluate, chart_paths, bsp_type)
                
                if visual_result is None:
                    self.log_message.emit(f"⚠️ {code} 视觉评分返回为空 (超时或模型故障)")
                    return None
                
                if visual_result and visual_result.get('action') != 'ERROR':
                    # 只缓存成功的评分
                    self.visual_score_cache[cache_key] = visual_result
            
            score = visual_result.get('score', 0) or 0
            action = visual_result.get('action', 'WAIT')
            analysis = visual_result.get('analysis', '')
            
            # Assuming bsp_type_display is available from signal processing
            bsp_type_display = f"{'b' if signal['is_buy'] else 's'}{bsp_type}"
            
            self.log_message.emit(f"✅ {code} {bsp_type_display} 评分完成: {score}")
            
            # --- 2. 视觉验证 (已经过 ML 达标过滤) ---
            if score < 70:
                self.log_message.emit(f"🤖 {code} {bsp_type_display} 拦截 [ML:{ml_prob:.2f}, Visual:{score}]: 视觉得分不达标(<70)")
                return None
            else:
                self.log_message.emit(f"✅ {code} {bsp_type_display} 准入 [ML:{ml_prob:.2f}, Visual:{score}]: 三项阈值均达标 (包含缠论买卖点)")

            # 添加评分结果到信号数据
            scored_signal = signal.copy()
            scored_signal['score'] = score
            scored_signal['visual_result'] = visual_result
            # Assuming chart_path refers to the primary chart for notification,
            # taking the first one if chart_paths is a list.
            scored_signal['chart_path'] = chart_paths[0] if chart_paths else None

            # --- Discord 推送 ---
            if self.discord_bot and score >= self.min_visual_score:
                ml_prob = signal.get('ml_prob', 0)
                msg = (
                    f"🎯 **发现港股交易信号**\n"
                    f"股票: {code}\n"
                    f"信号: {bsp_type_display}\n"
                    f"价格: {signal['current_price']}\n"
                    f"ML概率: **{ml_prob*100:.1f}%**\n"
                    f"视觉评分: **{score}分**\n"
                    f"时间: {datetime.now().strftime('%H:%M:%S')}"
                )
                # Use asyncio.run_coroutine_threadsafe for sending from a thread to the bot's event loop
                if scored_signal['chart_path']:
                    asyncio.run_coroutine_threadsafe(
                        self.discord_bot.send_notification(msg, scored_signal['chart_path']),
                        self.discord_bot.loop
                    )
                else:
                    asyncio.run_coroutine_threadsafe(
                        self.discord_bot.send_notification(msg),
                        self.discord_bot.loop
                    )
            
            self.log_message.emit(f"✅ {code} 评分已完成 (评分: {score})")
            return scored_signal
            
        except Exception as e:
            self.log_message.emit(f"视觉评分异常 {code}: {e}")
            # 即使视觉评分失败，也添加信号（评分为0）
            scored_signal = signal.copy()
            scored_signal['score'] = 0
            scored_signal['visual_result'] = {'score': 0, 'action': 'ERROR', 'analysis': '视觉评分失败'}
            self.log_message.emit(f"⚠️ {code} 评分失败，但信号已添加")
            return scored_signal

    def _collect_candidate_signals(self, watchlist_codes: List[str]) -> List[Dict]:
        """
        收集候选信号 - 第一步
        返回包含股票代码、缠论分析结果和股票信息的数据结构，但不包括图表和评分
        """
        self.log_message.emit("开始收集候选信号...")
        candidate_signals = []
        
        for code in watchlist_codes:
            self.log_message.emit(f"分析股票: {code}")
            
            # 获取股票信息
            stock_info = self.get_stock_info(code)
            if not stock_info:
                self.log_message.emit(f"{code} 股票信息获取失败，跳过")
                continue
            
            current_price = stock_info['current_price']
            if current_price <= 0:
                self.log_message.emit(f"{code} 实时报价无效（价格: {current_price}），尝试通过缠论分析获取价格...")
                # 先进行缠论分析，看是否能获取到有效价格
                chan_result = self.analyze_with_chan(code)
                if not chan_result:
                    self.log_message.emit(f"{code} 缠论分析也失败，跳过")
                    continue
                
                # 如果缠论分析成功，使用其中的价格
                bsp_price = chan_result.get('bsp_price', 0)
                if bsp_price > 0:
                    current_price = bsp_price
                    stock_info['current_price'] = current_price
                    self.log_message.emit(f"{code} 使用缠论分析价格: {current_price}")
                else:
                    self.log_message.emit(f"{code} 缠论分析价格也无效（{bsp_price}），跳过")
                    continue
            
            # 缠论分析
            chan_result = self.analyze_with_chan(code)
            if not chan_result:
                self.log_message.emit(f"{code} 无缠论信号，跳过")
                continue
            
            # 记录信号类型
            bsp_type = chan_result.get('bsp_type', '未知')
            is_buy = chan_result.get('is_buy_signal', False)
            bsp_time_str = chan_result.get('bsp_datetime_str', '')  # 需要在 analyze_with_chan 中添加
            bsp_type_display = f"{'b' if is_buy else 's'}{bsp_type}"
            
            # ====== 信号去重逻辑：检查持久化记录 ======
            # 检查是否已经执行过该信号
            last_executed_time = self.executed_signals.get(code, "")
            if last_executed_time == bsp_time_str:
                self.log_message.emit(f"{code} {bsp_type_display} 信号时间 {bsp_time_str} 已执行过，跳过重复处理")
                continue
                
            # 检查是否已经发现过该信号（避免重复通知未执行的信号）
            last_discovered_time = self.discovered_signals.get(code, "")
            if last_discovered_time == bsp_time_str:
                self.log_message.emit(f"{code} {bsp_type_display} 信号时间 {bsp_time_str} 已发现过，跳过重复通知")
                continue

            self.log_message.emit(f"{code} 信号类型: {bsp_type_display}, 是否买入: {is_buy}")
            
            # 持仓过滤
            position_qty = self.get_position_quantity(code)
            
            if is_buy and position_qty > 0:
                self.log_message.emit(f"{code} 已有持仓({position_qty}股)，跳过买入")
                continue
            
            if not is_buy and position_qty <= 0:
                self.log_message.emit(f"{code} 无持仓，跳过卖出")
                continue
            
            # ====== 待成交订单过滤 ======
            side_str = 'BUY' if is_buy else 'SELL'
            if self.check_pending_orders(code, side_str):
                self.log_message.emit(f"{code} 存在活跃 {side_str} 订单，跳过下单")
                continue
            
            # 收集候选信号（不包括图表和评分）
            signal_data = {
                'code': code,
                'is_buy': is_buy,
                'bsp_type': bsp_type,
                'current_price': current_price,
                'position_qty': position_qty,
                'lot_size': stock_info.get('lot_size', 100),
                'chan_result': chan_result  # 保存完整的缠论分析结果
            }
            
            # 记录已发现的信号（无论是否最终执行，都避免重复通知）
            if bsp_time_str:
                self.discovered_signals[code] = bsp_time_str
                self._save_discovered_signals()
            
            candidate_signals.append(signal_data)
            self.log_message.emit(f"✅ {code} 候选信号已收集")
        
        self.log_message.emit(f"共收集到 {len(candidate_signals)} 个候选信号")
        
        # 对候选信号进行本地评分筛选
        filtered_signals = []
        for signal in candidate_signals:
            chan_analysis = signal.get('chan_result', {}).get('chan_analysis', {})
            local_score = self.local_scorer.calculate_local_score(chan_analysis)
            
            self.log_message.emit(f"{signal['code']} 本地评分: {local_score}")
            
            if self.local_scorer.should_proceed_to_visual_ai(local_score):
                signal['local_score'] = local_score
                filtered_signals.append(signal)
                self.log_message.emit(f"✅ {signal['code']} 通过本地评分筛选，将进行视觉AI评分")
            else:
                self.log_message.emit(f"⏭️ {signal['code']} 本地评分({local_score})低于阈值，跳过视觉AI评分")
        
        self.log_message.emit(f"本地评分筛选后剩余 {len(filtered_signals)} 个信号")
        return filtered_signals

    def _generate_single_chart(self, signal_data: Dict) -> Optional[Dict]:
        """
        生成单个图表的辅助函数，用于并行处理
        """
        code = signal_data['code']
        chan_result = signal_data['chan_result']
        
        try:
            # 生成图表
            chart_paths = self.generate_charts(code, chan_result['chan_analysis'])
            if not chart_paths:
                self.log_message.emit(f"{code} 图表生成失败")
                return None
            
            # 添加图表路径到信号数据
            signal_with_chart = signal_data.copy()
            signal_with_chart['chart_paths'] = chart_paths
            self.log_message.emit(f"✅ {code} 图表已生成 ({len(chart_paths)} 张)")
            return signal_with_chart
        except Exception as e:
            self.log_message.emit(f"生成图表异常 {code}: {e}")
            return None

    def _batch_generate_charts(self, candidate_signals: List[Dict]) -> List[Dict]:
        """
        批量生成图表 - 第二步 (并行化版本)
        """
        self.log_message.emit(f"开始批量生成图表，共 {len(candidate_signals)} 个信号")
        
        # 使用进程池并行生成图表
        signals_with_charts = []
        max_workers = min(4, len(candidate_signals))  # 限制并发数避免资源耗尽
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_signal = {
                executor.submit(self._generate_single_chart, signal): signal
                for signal in candidate_signals
            }
            
            # 收集结果
            for future in as_completed(future_to_signal):
                result = future.result()
                if result is not None:
                    signals_with_charts.append(result)
        
        self.log_message.emit(f"批量图表生成完成，成功生成 {len(signals_with_charts)} 个带图表的信号")
        return signals_with_charts

    async def _batch_score_signals_async(self, signals_with_charts: List[Dict]) -> List[Dict]:
        """
        异步批量评分信号 - 第三步
        """
        self.log_message.emit(f"开始异步批量评分，共 {len(signals_with_charts)} 个带图表的信号")
        
        # 创建一个异步会话（虽然我们实际上不会在这里使用它，但为了接口一致性保留）
        async with aiohttp.ClientSession() as session:
            # 创建任务列表
            tasks = [self._async_evaluate_single_signal(session, signal) for signal in signals_with_charts]
            
            # 并发执行所有评分任务
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 过滤掉异常结果
        scored_signals = []
        for result in results:
            if isinstance(result, Exception):
                self.log_message.emit(f"评分任务异常: {result}")
            else:
                scored_signals.append(result)
        
        # 移除可能的None值
        scored_signals = [s for s in scored_signals if s is not None]
        
        self.log_message.emit(f"异步批量评分完成，共 {len(scored_signals)} 个已评分信号")
        return scored_signals

    @pyqtSlot(dict, result=bool)
    def process_realtime_signal(self, signal_data: Dict) -> bool:
        """
        处理单个实时交易信号
        
        Args:
            signal_data: 包含信号信息的字典，格式为:
                {
                    'code': str,        # 股票代码
                    'signal': str,      # 信号类型 ('BUY' or 'SELL')
                    'price': float,     # 信号价格
                    'time': str         # 信号时间
                }
                
        Returns:
            bool: 交易是否成功执行
        """
        try:
            code = signal_data['code']
            signal_type = signal_data['signal']
            price = signal_data['price']
            signal_time = signal_data['time']
            
            self.log_message.emit(f"🔄 处理实时信号: {code} {signal_type} @ {price} ({signal_time})")
            
            # 获取股票信息
            stock_info = self.get_stock_info(code)
            if not stock_info:
                self.log_message.emit(f"❌ {code} 股票信息获取失败，跳过实时信号处理")
                return False
            
            current_price = stock_info['current_price']
            if current_price <= 0:
                current_price = price  # 使用信号价格作为备选
                self.log_message.emit(f"{code} 使用信号价格: {current_price}")
            
            # 获取持仓信息
            position_qty = self.get_position_quantity(code)
            
            # 检查信号方向与持仓是否匹配
            is_buy = signal_type.upper() == 'BUY'
            if is_buy and position_qty > 0:
                self.log_message.emit(f"{code} 已有持仓({position_qty}股)，跳过买入信号")
                return False
            
            if not is_buy and position_qty <= 0:
                self.log_message.emit(f"{code} 无持仓，跳过卖出信号")
                return False
            
            # 检查待成交订单
            side_str = 'BUY' if is_buy else 'SELL'
            if self.check_pending_orders(code, side_str):
                self.log_message.emit(f"{code} 存在活跃 {side_str} 订单，跳过下单")
                return False
            
            # 执行缠论分析以获取完整的分析结果（用于生成图表）
            chan_result = self.analyze_with_chan(code)
            if not chan_result:
                self.log_message.emit(f"{code} 缠论分析失败，跳过实时信号处理")
                return False
            
            # 生成图表
            chart_paths = self.generate_charts(code, chan_result['chan_analysis'])
            if not chart_paths:
                self.log_message.emit(f"{code} 图表生成失败，但继续处理信号")
            
            # 执行视觉评分（如果图表生成成功）
            score = 0
            if chart_paths:
                try:
                    # 检查缓存
                    cache_key = f"{code}_{signal_time}_{chan_result['bsp_type']}"
                    if cache_key in self.visual_score_cache:
                        self.log_message.emit(f"⚡ {code} 实时信号命中视觉缓存 ({cache_key})")
                        visual_result = self.visual_score_cache[cache_key]
                    else:
                        visual_result = self.visual_judge.evaluate(chart_paths, chan_result['bsp_type'])
                        if visual_result and visual_result.get('action') != 'ERROR':
                            self.visual_score_cache[cache_key] = visual_result
                            
                    score = visual_result.get('score', 0)
                    self.log_message.emit(f"{code} 视觉评分: {score}/100")
                except Exception as e:
                    self.log_message.emit(f"{code} 视觉评分异常: {e}")
                    score = 0
            
            # 检查熔断机制
            if self.risk_manager.check_circuit_breaker():
                self.log_message.emit("⚠️ 熔断机制激活，暂停所有交易操作")
                return False
            
            # 检查风险管理
            if not self.risk_manager.can_execute_trade(code, score):
                self.log_message.emit(f"⚠️ 风险管理限制，跳过交易 {code}")
                return False
            
            # 只有视觉评分 >= 阈值才执行交易
            if score >= self.min_visual_score:
                # 临时保存元数据用于 execute_trade 内部持久化 (优化 F)
                self._last_signal_type = chan_result.get('bsp_type', '未知')
                self._last_ml_prob = chan_result.get('ml_prob', 0) # 实时信号可能没有ML prob，这里需要从chan_result获取或设为0
                self._last_visual_score = score
                self._last_exit_reason = "实时信号"
                
                # 计算交易数量
                if is_buy:
                    # 买入：使用风险管理器计算动态仓位
                    lot_size = stock_info.get('lot_size', 100)
                    available_funds, total_assets = self.get_account_assets()
                    buy_quantity = self.risk_manager.calculate_position_size(
                        code=code,
                        available_funds=available_funds,
                        current_price=current_price,
                        signal_score=score,
                        risk_factor=1.0,
                        total_assets=total_assets,
                        lot_size=lot_size
                    )
                    
                    # 二次校验与强制舍入
                    buy_quantity = (buy_quantity // lot_size) * lot_size
                    
                    if buy_quantity <= 0:
                        self.log_message.emit(f"{code} 风险管理器建议不买入或资金不足 (计算股数: {buy_quantity})")
                        return False
                    
                    if self.execute_trade(code, 'BUY', buy_quantity, current_price):
                        # 记录交易
                        self.risk_manager.record_trade(code, 'BUY', buy_quantity, current_price, score)
                        self.executed_signals[code] = signal_time
                        self._save_executed_signals()
                        self.log_message.emit(f"✅ 实时买入成功 {code}, 数量: {buy_quantity}, 价格: {current_price}")
                        return True
                    else:
                        self.log_message.emit(f"❌ 实时买入失败 {code}")
                        return False
                else:
                    # 卖出：卖出全部持仓
                    if self.execute_trade(code, 'SELL', position_qty, current_price):
                        # 记录交易
                        released_funds = current_price * position_qty
                        self.risk_manager.record_trade(code, 'SELL', position_qty, current_price, score, pnl=released_funds)
                        self.executed_signals[code] = signal_time
                        self._save_executed_signals()
                        self.log_message.emit(f"✅ 实时卖出成功 {code}, 数量: {position_qty}, 价格: {current_price}")
                        return True
                    else:
                        self.log_message.emit(f"❌ 实时卖出失败 {code}")
                        return False
            else:
                self.log_message.emit(f"⏭️ 实时信号 {code} 评分({score})低于阈值({self.min_visual_score})，仅通知不执行")
                return False
                
        except Exception as e:
            self.log_message.emit(f"❌ 处理实时信号异常 {code}: {e}")
            return False

    @pyqtSlot(result=bool)
    def close_all_positions(self) -> bool:
        """
        一键清仓：卖出当前账户中的所有持仓
        
        Returns:
            bool: 是否成功执行了清仓操作
        """
        try:
            self.log_message.emit("🚨 正在启动一键清仓流程...")
            
            refresh = (self.trd_env == TrdEnv.SIMULATE)
            # 1. 查询所有持仓
            ret, data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=False)
            if ret != RET_OK:
                self.log_message.emit(f"❌ 获取持仓列表失败: {data}")
                return False
                
            if data.empty:
                self.log_message.emit("ℹ️ 当前账户无任何持仓，无需清仓。")
                return True
                
            self.log_message.emit(f"发现 {len(data)} 个持仓代码，准备逐一清仓。")
            
            success_count = 0
            # 过滤掉数量为0的持仓
            valid_positions = data[data['qty'] > 0]
            total_count = len(valid_positions)
            
            if total_count == 0:
                self.log_message.emit("ℹ️ 当前账户无有效持仓，无需清仓。")
                return True
            
            for _, position in valid_positions.iterrows():
                code = position['code']
                qty = int(position['qty'])
                
                # 获取最新价格以尝试卖出
                info = self.get_stock_info(code)
                current_price = info.get('current_price', 0) if info else 0
                
                if current_price <= 0:
                    self.log_message.emit(f"⚠️ 无法获取 {code} 的最新价格，跳过清仓。")
                    continue
                
                self.log_message.emit(f"正在清仓 {code}: 数量={qty}, 价格={current_price}")
                
                # 执行卖出
                if self.execute_trade(code, 'SELL', qty, current_price, urgent=True):
                    self.log_message.emit(f"✅ {code} 清仓成功")
                    success_count += 1
                    # 记录风险管理日志
                    self.risk_manager.record_trade(code, 'SELL', qty, current_price, signal_score=0, pnl=0)
                else:
                    self.log_message.emit(f"❌ {code} 清仓失败")
            
            self.log_message.emit(f"🏁 一键清仓完成：成功 {success_count}/{total_count}")
            return success_count == total_count
            
        except Exception as e:
            self.log_message.emit(f"❌ 一键清仓异常: {e}")
            return False

    @pyqtSlot()
    def query_account_funds(self):
        """查询账户资金和持仓 (对齐 GUI 接口)"""
        try:
            # 0. [核心修复] 强制刷新模拟盘账户列表同步 (解决模拟盘成交后数据不更新)
            if self.trd_env == TrdEnv.SIMULATE:
                self.trd_ctx.get_acc_list()
            
            refresh = (self.trd_env == TrdEnv.SIMULATE)
            
            with self.futu_api_lock:
                # 1. 查询资金
                ret, data = self.trd_ctx.accinfo_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=refresh)
                if ret != RET_OK:
                    self.log_message.emit(f"❌ 获取资金失败: {data}")
                    return
                
                # 提取可用资金和总资产
                available = float(data["cash"].iloc[0]) if not data.empty else 0.0
                total = float(data["total_assets"].iloc[0]) if not data.empty else 0.0
                
                # 2. 查询持仓
                ret_pos, pos_data = self.trd_ctx.position_list_query(acc_id=self._trd_acc_id, trd_env=self.trd_env, refresh_cache=refresh)
                positions = []
                new_cache = {}
                
                if ret_pos == RET_OK and not pos_data.empty:
                    for _, row in pos_data.iterrows():
                        code = row['code']
                        qty = int(row['qty'])
                        if qty > 0:
                            new_cache[code] = qty
                            positions.append({
                                "symbol": code.split('.')[-1],
                                "code": code,
                                "qty": qty,
                                "mkt_value": float(row.get("market_val", 0.0)),
                                "pnl_ratio": float(row.get("pl_ratio", 0.0)),
                                "avg_cost": float(row.get("cost_price", 0.0))
                            })

                # 🛡️ [影子账本 - 强制隔离区穿透]
                # 即使 API 返回空，也根据 hard-coded 的底仓进行补齐展示
                manual_hk_pos = {
                    'HK.00699': {'qty': 5000, 'cost': 14.31, 'name': '均胜电子'}
                }
                for m_code, m_info in manual_hk_pos.items():
                    # 检查是否已在列表中 (避免重复)
                    if not any(p['code'] == m_code for p in positions):
                        num_qty = m_info['qty']
                        new_cache[m_code] = num_qty
                        positions.append({
                            'symbol': m_code.split('.')[-1],
                            'code': m_code,
                            'qty': num_qty,
                            'mkt_value': num_qty * 14.86, # 假设参考价
                            'pnl_ratio': round((14.86 - m_info['cost']) / m_info['cost'] * 100, 2),
                            'avg_cost': m_info['cost']
                        })
                        self.log_message.emit(f"🛡️ [影子账本-HK-手动刷新] 已从内存加载底仓: {m_code}")
                
                # 3. 更新内存缓存 (确保 0ms 查询也能命中)
                self.position_cache.update(new_cache)
                self.last_pos_sync_time = time.time()
                
                # 4. 发射信号 (UI 主线程会自动接收)
                # 💡 [关键修正] 对齐 pyqtSignal(float, float, float, list) 信号签名
                today_pl = float(data.iloc[0].get('today_pl', 0.0)) if not data.empty else 0.0
                self.funds_updated.emit(available, total, today_pl, positions)
            
        except Exception as e:
            self.log_message.emit(f"❌ 查询账户状态异常: {e}")
