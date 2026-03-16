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
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Callable
from pathlib import Path
import asyncio

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 导入配置和核心库
from config import TRADING_CONFIG, CHAN_CONFIG, CHART_PARA
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# 导入 Futu 和视觉评分
from futu import *
from visual_judge import VisualJudge
import aiohttp

# 导入风险管理
from Trade.RiskManager import get_risk_manager
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
        self.trd_env = TrdEnv.SIMULATE if self.dry_run else TrdEnv.REAL

        # 初始化 Discord Bot (将在启动扫描时真正启动)
        self.discord_bot = discord_bot

        # 缠论配置
        self.chan_config = CChanConfig(CHAN_CONFIG)

        # 视觉评分器
        self.visual_judge = VisualJudge()

        # 图表生成锁
        self.chart_generation_lock = threading.Lock()

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
        self._force_scan = False  # 标志是否需要强制执行下一次扫描
        
        # 视觉评分缓存 (code_time_type -> score_dict)
        self.visual_score_cache = {}

        self.last_login_time = None
        
        # 记录持仓的追踪止损状态: { 'HK.00700': {'highest_price': 300.5, 'atr': 5.2, 'atr_multiplier': 2.0} }
        self.position_trackers = {}
        
        # --- ML Validation ---
        self.signal_validator = SignalValidator()
        self.ml_threshold = 0.60
        
        # 记录最近分析过的信号日志时间，防止重复刷屏: { 'HK.09959_2s': timestamp }
        self.last_analysis_log_time = {}
        
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
        """延迟初始化 Futu 交易上下文，确保在使用线程上创建"""
        if self._trd_ctx is None:
            self._trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
        return self._trd_ctx

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
                self.discord_bot.stop()
            except:
                pass
        self.log_message.emit("🛑 收到停止信号，正在安全退出...")

    def force_scan(self):
        """外部触发：强制立即执行一轮完整策略扫描"""
        self._force_scan = True
        self.log_message.emit("⚡ 收到强制扫描指令，将在下一次心跳时触发完整扫描")

    def get_watchlist_data(self) -> Dict[str, str]:
        """获取所选自选股分组的代码和名称清单（支持逗号分隔的多分组合并）"""
        try:
            # 支持多分组合并: "港股,热点_实盘" -> 分别拉取再合并
            groups = [g.strip() for g in self.hk_watchlist_group.split(',') if g.strip()]
            if not groups:
                groups = [""]
            
            merged_watchlist = {}
            for group in groups:
                if group in ["全部", "All", ""]:
                    group = ""
                ret, data = self.quote_ctx.get_user_security(group_name=group)
                if ret == RET_OK and not data.empty:
                    # 过滤出以 'HK.' 开头的代码
                    hk_data = data[data['code'].str.startswith('HK.')]
                    name_col = 'name' if 'name' in hk_data.columns else 'stock_name'
                    partial = dict(zip(hk_data['code'].tolist(), hk_data[name_col].tolist()))
                    merged_watchlist.update(partial)
                    self.log_message.emit(f"分组 [{group or '全部'}] 获取到 {len(partial)} 只港股")
                else:
                    self.log_message.emit(f"获取分组 [{group}] 失败: {data}")
            
            self.log_message.emit(f"合计获取 {len(merged_watchlist)} 只港股自选股 (去重后)")
            return merged_watchlist
        except Exception as e:
            self.log_message.emit(f"获取自选股列表异常: {e}")
            return {}

    def get_stock_info(self, code: str) -> Optional[Dict]:
        """
        获取单个股票的详细信息。

        Args:
            code: 股票代码

        Returns:
            包含股票信息的字典，如果失败则返回 None
        """
        try:
            ret, data = self.quote_ctx.get_stock_basicinfo(Market.HK, code_list=[code])
            if ret == RET_OK and not data.empty:
                info = data.iloc[0].to_dict()
                # 获取实时报价，使用 get_market_snapshot 替代无需订阅的 get_stock_quote
                ret_snap, snap_data = self.quote_ctx.get_market_snapshot([code])
                if ret_snap == RET_OK and not snap_data.empty:
                    quote = snap_data.iloc[0]
                    info['current_price'] = quote['last_price']
                    info['lot_size'] = quote.get('lot_size', info.get('lot_size', 100))
                else:
                    # 尝试从基础信息中获取价格作为备选
                    if 'price' in info and info['price'] > 0:
                        info['current_price'] = info['price']
                        info['lot_size'] = info.get('lot_size', 100)
                    else:
                        info['current_price'] = 0.0
                        info['lot_size'] = 0
                return info
            else:
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
        try:
            # 获取30分钟和5分钟K线数据（分别获取，使用不同的时间范围）
            end_time = datetime.now()
            
            # 标准化结束时间到最近的5分钟边界，以提高缓存命中率
            # 例如：10:34:23 -> 10:35:00
            minutes = (end_time.minute // 5) * 5
            end_time_rounded = end_time.replace(minute=minutes, second=0, microsecond=0)
            end_time_str = end_time_rounded.strftime("%Y-%m-%d %H:%M:%S")
            
            # 30M数据使用30天范围（历史数据充足）
            start_time_30m = end_time - timedelta(days=30)
            start_time_30m_str = start_time_30m.strftime("%Y-%m-%d")
            
            # 5M数据使用7天范围（避免Futu API的1000根K线限制）
            start_time_5m = end_time - timedelta(days=7)
            start_time_5m_str = start_time_5m.strftime("%Y-%m-%d")
            
            # 顺序获取30M数据
            try:
                # 默认数据源
                data_src = DATA_SRC.FUTU
                if code.upper().startswith("US.") and os.getenv("IB_HOST"):
                    data_src = DATA_SRC.IB
                
                # 获取30M数据
                chan_30m = CChan(
                    code=code,
                    begin_time=start_time_30m_str,
                    end_time=end_time_str,
                    data_src=data_src,
                    lv_list=[KL_TYPE.K_30M],
                    config=self.chan_config
                )
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
                self.log_message.emit(f"{code} 30分钟K线数据不足({kline_30m_count}根)，跳过分析")
                return None
            
            # 从30M级别获取最新的买卖点（主分析基于30M）
            latest_bsps = chan_30m.get_latest_bsp(idx=0, number=1)
            if not latest_bsps:
                return None  # 无信号，不再继续获取 5M 数据
            
            # ====== 发现买卖点，按需获取 5M 数据（用于后续图表生成） ======
            chan_5m = None
            try:
                chan_5m = CChan(
                    code=code,
                    begin_time=start_time_5m_str,
                    end_time=end_time_str,
                    data_src=DATA_SRC.FUTU,
                    lv_list=[KL_TYPE.K_5M],
                    config=self.chan_config
                )
                
                # 检查5M数据是否足够
                if chan_5m is not None:
                    kline_5m_count = 0
                    for _ in chan_5m[0].klu_iter():
                        kline_5m_count += 1
                    if kline_5m_count < 20:
                        chan_5m = None
            except Exception as e:
                self.log_message.emit(f"{code} 获取5M次级别数据失败 (非致命): {e}")
            
            # 从30M级别获取最新的买卖点（主分析基于30M）
            latest_bsps = chan_30m.get_latest_bsp(idx=0, number=1)
            if not latest_bsps:
                self.log_message.emit(f"{code} 未发现买卖点")
                return None
            
            bsp = latest_bsps[0]
            bsp_type = bsp.type2str()
            is_buy = bsp.is_buy  # 信任 CChan 的 is_buy 判断
            price = bsp.klu.close
            
            # ====== 时间过滤：只交易最近4个交易小时内的信号 ======
            # 将CTime转换为datetime
            bsp_ctime = bsp.klu.time
            bsp_time = datetime(bsp_ctime.year, bsp_ctime.month, bsp_ctime.day,
                               bsp_ctime.hour, bsp_ctime.minute, bsp_ctime.second)
            
            now = datetime.now()
            trading_hours = self.calculate_trading_hours(bsp_time, now)
            
            if trading_hours > TRADING_CONFIG['max_signal_age_hours']:
                self.log_message.emit(f"{code} {bsp_type} {'买入' if is_buy else '卖出'}信号产生于 {bsp_time.strftime('%Y-%m-%d %H:%M')}，"
                                   f"距今 {trading_hours:.1f} 个交易小时，超过{TRADING_CONFIG['max_signal_age_hours']}小时窗口，跳过")
                return None
            
            self.log_message.emit(f"{code} {bsp_type} {'买入' if is_buy else '卖出'}信号在{TRADING_CONFIG['max_signal_age_hours']}小时窗口内（{trading_hours:.1f}个交易小时前），继续分析")
            
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
                self.log_message.emit(f"{code} 缠论分析: {bsp_type} {'买入' if is_buy else '卖出'}信号, 价格: {price}")
                self.last_analysis_log_time[log_key] = now
                
            return result
            
        except Exception as e:
            self.log_message.emit(f"CChan分析异常 {code}: {e}")
            # 捕获特定的K线数据不足错误
            if "在次级别找不到K线条数超过" in str(e) or "次级别" in str(e):
                self.log_message.emit(f"{code} 因K线数据不足跳过分析")
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

    def execute_trade(self, code: str, action: str, quantity: int, price: float, urgent: bool = False) -> bool:
        """
        执行交易

        Args:
            code: 股票代码
            action: 交易动作 ('BUY' or 'SELL')
            quantity: 数量
            price: 价格
            urgent: 是否为紧急模式 (如止损、清仓)
        """
        if quantity <= 0:
            self.log_message.emit(f"无效数量 {quantity}，跳过交易 {code}")
            return False
        
        try:
            is_cts = self.is_in_continuous_trading_session()
            trd_side = TrdSide.BUY if action.upper() == 'BUY' else TrdSide.SELL
            
            # 策略：如果是紧急模式且在持续交易时段，使用市价单保证成交
            if urgent and is_cts:
                self.log_message.emit(f"🚀 {code} 触发紧急模式，使用【市价单】执行 {action}")
                ret, data = self.trd_ctx.place_order(
                    price=0,  # 市价单价格传0
                    qty=quantity,
                    code=code,
                    trd_side=trd_side,
                    order_type=OrderType.MARKET,
                    trd_env=self.trd_env
                )
            else:
                # 常规模式或非交易时段，使用增强限价单
                # 如果是紧急模式但不在 CTS，缓冲区从 1% 扩大到 3%
                buffer = 0.03 if urgent else 0.01
                if action.upper() == 'BUY':
                    order_price = round(price * (1 + buffer), 3)
                else:
                    order_price = round(price * (1 - buffer), 3)
                
                mode_str = "紧急(回退)" if urgent else "常规"
                self.log_message.emit(f"📝 {code} 使用【增强限价单】({mode_str}) 执行 {action}: 数量={quantity}, 价格={order_price}")
                
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
                return True
            else:
                self.log_message.emit(f"❌ {action} 订单失败 {code}: {data}")
                return False
                
        except Exception as e:
            self.log_message.emit(f"执行交易异常 {code}: {e}")
            return False

    def get_account_assets(self) -> Tuple[float, float]:
        """
        获取可用资金和总资产 (模拟盘/实盘都实时查询)

        Returns:
            (可用资金金额, 总资产金额)
        """
        try:
            ret, data = self.trd_ctx.accinfo_query(trd_env=self.trd_env)
            if ret == RET_OK and not data.empty:
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
        """
        清理旧的图表进行空间释放。
        默认清理指定的 hours 之前的 .png 图表。
        """
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
            # 1. 查询资金信息
            ret_acc, data_acc = self.trd_ctx.accinfo_query(trd_env=self.trd_env)
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

            # 2. 查询持仓
            ret_pos, data_pos = self.trd_ctx.position_list_query(trd_env=self.trd_env)
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
        """
        执行循环扫描和交易流程。
        - 快速回路 (Fast Loop, ~60s): 检查追踪止损、清仓申请、更新报价。
        - 慢速策略扫描 (Slow Scan, ~30m): 基于 30 分钟 K 线边界触发完整缠论分析。
        """
        self._is_running = True
        
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

        self.log_message.emit("🚀 启动港股双速自动化监控进程 (60s 风险监测 / 30m 策略扫描)...")
        
        # 避免启动时立即触发全量扫描，初始化为当前 30M Bar 时间，等待下一个周期再触发
        now = datetime.now()
        last_strategy_scan_time = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
        
        # 0. 初始化现有持仓的风险监控
        self._initialize_position_trackers()
        
        while self._is_running:
            try:
                # 0. 基础维护
                self._cleanup_old_charts(hours=24)
                
                # Phase 4: 检查并热加载最新的优化的模型
                self.signal_validator.check_and_reload()
                
                # 检查是否暂停
                if self._is_paused:
                    self.log_message.emit("⏸️ 自动化扫描已由远程指令暂停...")
                    for _ in range(60):
                        if not self._is_running or not self._is_paused: break
                        time.sleep(1)
                    continue

                # 检查是否在交易时间内
                if not self.is_trading_time():
                    self.log_message.emit("💤 非交易时间，等待 60 秒后重试...")
                    for _ in range(60):
                        if not self._is_running or self._is_paused: break
                        time.sleep(1)
                    continue
                
                now = datetime.now()
                # 计算属于哪个 30 分钟 K 线桶 (例如 10:29 -> 10:00, 10:31 -> 10:30)
                current_bar_time = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
                
                # 1. 快速风险监测 (每轮必跑)
                self.log_message.emit(f"💓 [快速监测] 检查持仓风险与最新报价... ({now.strftime('%H:%M:%S')})")
                watchlist = self.get_watchlist_data()
                if not watchlist:
                    time.sleep(10)
                    continue
                
                watchlist_codes = list(watchlist.keys())

                # 批量更新价格并检查止损
                self._check_trailing_stops()
                
                # 2. 慢速策略扫描触发逻辑
                # 规则：如果当前 Bar 时间与上次不同，且已经过了 Bar 开始后 2 分钟（等待数据稳定）
                should_scan_strategy = False
                is_force_scan = False
                
                if self._force_scan:
                    should_scan_strategy = True
                    is_force_scan = True
                    self._force_scan = False  # 重置标志
                elif last_strategy_scan_time != current_bar_time:
                    # 额外等待 3 分钟让 30M 棒线在富途后端稳定
                    if now.minute % 30 >= 3: 
                        should_scan_strategy = True
                
                if should_scan_strategy:
                    if last_strategy_scan_time == current_bar_time:
                        self.log_message.emit(f"🔍 [策略扫描] 捕获到手动强制扫描指令，启动完整缠论分析...")
                    else:
                        self.log_message.emit(f"🔍 [策略扫描] 捕获到新的 30M 周期 ({current_bar_time.strftime('%H:%M')})，启动完整缠论分析...")
                    
                    # 执行原有的完整扫描逻辑
                    self._perform_full_strategy_scan(watchlist, is_force_scan=is_force_scan)
                    last_strategy_scan_time = current_bar_time
                    self.log_message.emit("✅ [策略扫描] 本轮分析完成。")
                
                # 进度清理
                self.scan_finished.emit(0, 0, 0, 0)
                
                # 休眠 60 秒（风险监测频率）
                self.log_message.emit("💤 监测中，60秒后进入下一轮快速巡检...")
                for _ in range(60):
                    if not self._is_running: break
                    time.sleep(1)

            except Exception as e:
                self.log_message.emit(f"❌ 运行循环发生异常: {e}")
                time.sleep(10)

        self.log_message.emit("🔚 港股自动化监控进程已安全退出。")

    def _perform_full_strategy_scan(self, watchlist: Dict[str, str], is_force_scan: bool = False):
        """原有的完整缠论分析和交易决策逻辑"""
        try:
            start_time = time.time()
            watchlist_codes = list(watchlist.keys())
            total_stocks = len(watchlist_codes)
            
            # 1. 收集候选信号
            candidate_signals = []
            for i, code in enumerate(watchlist_codes, 1):
                if not self._is_running: break
                name = watchlist.get(code, "")
                self.scan_progress.emit(i, total_stocks, f"策略分析 {code} {name}")
                self.log_message.emit(f"🔍 [策略扫描] 正在分析 {code} {name} ({i}/{total_stocks})...")
                
                # 获取股票信息
                stock_info = self.get_stock_info(code)
                if not stock_info: continue
                
                # 缠论分析 (30M 主信号)
                chan_result = self.analyze_with_chan(code)
                if not chan_result:
                    # 如果失败，略作休息防止持续撞墙
                    time.sleep(1.0)
                    continue
                
                # 为后续请求预留一点 API 额度
                time.sleep(1.0)
                bsp_type = chan_result.get('bsp_type', '未知')
                is_buy = chan_result.get('is_buy_signal', False)
                bsp_time_str = chan_result.get('bsp_datetime_str', '')
                current_price = stock_info['current_price']
                
                # ML / 重复 / 持仓 过滤逻辑 (保持原有逻辑)
                if not self._validate_and_filter_signal(code, chan_result, stock_info, is_force_scan):
                    continue
                
                # 收集有效信号
                signal_data = {
                    'code': code,
                    'is_buy': is_buy,
                    'bsp_type': bsp_type,
                    'current_price': current_price,
                    'position_qty': self.get_position_quantity(code),
                    'lot_size': stock_info.get('lot_size', 100),
                    'chan_result': chan_result
                }
                
                # 记录已发现 (Phase 4: 使用双键系统去重)
                if bsp_time_str:
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    sig_key_strict = f"STRICT_{code}_{bsp_time_str}_{bsp_type}"
                    sig_key_loose = f"LOOSE_{code}_{bsp_type}"
                    self.discovered_signals[sig_key_strict] = now_str
                    self.discovered_signals[sig_key_loose] = now_str
                    self.discovered_signals[code] = bsp_time_str # 保留旧格式供风险监控查阅
                    self._save_discovered_signals()
                
                candidate_signals.append(signal_data)

            # 2. 生成图表 & 评分 & 执行
            if candidate_signals:
                scored_signals = self._process_candidate_signals(candidate_signals)
                if scored_signals:
                    available_funds, total_assets = self.get_account_assets()
                    self._execute_trades(scored_signals, available_funds, total_assets)

            # 记录性能
            duration = time.time() - start_time
            self.performance_monitor.record_scan_performance(len(watchlist_codes), duration)
            
        except Exception as e:
            self.log_message.emit(f"⚠️ 策略扫描子流程错误: {e}")

    def _validate_and_filter_signal(self, code, chan_result, stock_info, is_force_scan: bool = False) -> bool:
        """封装原有的信号验证和过滤逻辑，并引入与 A 股一致的去重机制"""
        is_buy = chan_result.get('is_buy_signal', False)
        bsp_type = chan_result.get('bsp_type', '未知')
        bsp_type_display = f"{'b' if is_buy else 's'}{bsp_type}"
        bsp_time_str = chan_result.get('bsp_datetime_str', '')
        
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
            logger.debug(f"[去重] {code} 严格去重跳过: {sig_key_strict}")
            return False
            
        if sig_key_loose in self.discovered_signals:
            last_notify_info = self.discovered_signals[sig_key_loose]
            try:
                last_time = datetime.strptime(last_notify_info, "%Y-%m-%d %H:%M:%S")
                diff_sec = (now - last_time).total_seconds()
                if diff_sec < 14400: # 4小时保护期
                    self.log_message.emit(f"⏭️ {code} {bsp_type_display} 宽松去重跳过 (4h保护期内)")
                    return False
            except Exception as e:
                logger.error(f"解析信号记录时间报错: {e}")

        # 3. 挂单校验 (如果有相同方向正在进行中的订单，不要重复下单)
        if self.check_pending_orders(code, 'BUY' if is_buy else 'SELL'):
            self.log_message.emit(f"⏭️ {code} {bsp_type_display} 已有相同方向挂单，跳过")
            return False

        return True

    def _process_candidate_signals(self, candidate_signals: List[Dict]) -> List[Dict]:
        """封装图表生成和评分流程"""
        signals_with_charts = []
        for signal in candidate_signals:
            chart_paths = self.generate_charts(signal['code'], signal['chan_result']['chan_analysis'])
            if chart_paths:
                s = signal.copy()
                s['chart_paths'] = chart_paths
                signals_with_charts.append(s)
        
        if signals_with_charts:
            return self._batch_score_signals(signals_with_charts)
        return []


    def _batch_score_signals(self, signals_with_charts: List[Dict]) -> List[Dict]:
        """批量评分信号"""
        # 使用 asyncio.run 来运行异步方法
        return asyncio.run(self._batch_score_signals_async(signals_with_charts))

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
                price = signal['current_price']
                bsp_type = signal['bsp_type']
                
                self.log_message.emit(f"\n[{i}/{len(sell_signals)}] 卖出 {code} ({name}) - {bsp_type} - 评分: {score}")
                
                # 检查是否可以执行交易
                if not self.risk_manager.can_execute_trade(code, score):
                    self.log_message.emit(f"⚠️ 风险管理限制，跳过卖出 {code}")
                    continue
                
                # 只有视觉评分 >= 阈值才执行交易
                if score >= self.min_visual_score:
                    if self.execute_trade(code, 'SELL', qty, price):
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
                ret, data = self.trd_ctx.position_list_query(trd_env=self.trd_env)
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
                        lot_size=lot_size
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
                    
                    if self.execute_trade(code, 'BUY', buy_quantity, price):
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
                        
                        # 初始化或更新追踪止损基准值
                        if atr_value and atr_value > 0:
                            self.position_trackers[code] = {
                                'highest_price': price,
                                'atr': atr_value,
                                'atr_multiplier': atr_multiplier
                            }
                            self.log_message.emit(f"🛡️ {code} 已启动移动止损监控: 初始价={price:.3f}, ATR={atr_value:.3f}")
                            
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
        return float(np.mean(tr_list))

    def _check_trailing_stops(self):
        """
        检查所有在池中的持仓是否触发移动止损
        """
        if not hasattr(self, 'position_trackers') or not self.position_trackers:
            return
            
        codes_to_check = list(self.position_trackers.keys())
        for code in codes_to_check:
            # 1. 查询当前真实持仓
            qty = self.get_position_quantity(code)
            if qty <= 0:
                # 已经没有持仓了（可能通过缠论普通信号平仓），移除追踪
                self.log_message.emit(f"🔄 {code} 已无持仓，停止移动止损追踪")
                del self.position_trackers[code]
                continue
                
            # 2. 查询最新价格
            info = self.get_stock_info(code)
            if not info or info.get('current_price', 0) <= 0:
                continue
                
            current_price = info['current_price']
            tracker = self.position_trackers[code]
            
            # 3. 更新最高价
            if current_price > tracker['highest_price']:
                tracker['highest_price'] = current_price
                self.log_message.emit(f"📈 {code} 创持仓新高: {current_price:.3f}")
                
            # 4. 判断回撤止损
            highest = tracker['highest_price']
            stop_distance = tracker['atr'] * tracker['atr_multiplier']
            stop_price = highest - stop_distance
            
            if current_price < stop_price:
                self.log_message.emit(f"🚨 {code} 触发移动止损! 最高价={highest:.3f}, 现价={current_price:.3f}, 止损位={stop_price:.3f}")
                
                # 尝试强制抛售所有持仓
                if self.execute_trade(code, 'SELL', qty, current_price, urgent=True):
                    self.log_message.emit(f"✅ {code} 止损抛售成功: {qty} 股")
                    del self.position_trackers[code]
                    
                    # 通知风控记录盈亏
                    # 如果有记录买入均价更好，这里近似计算 pnl 或者留给后端对齐 
                    self.risk_manager.record_trade(code, 'SELL', qty, current_price, signal_score=0, pnl=0)
                else:
                    self.log_message.emit(f"❌ {code} 止损抛售失败，将在此后循环继续尝试。")

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
        获取股票持仓数量
        
        Args:
            code: 股票代码
            
        Returns:
            持仓数量（0表示未持仓）
        """
        try:
            ret, data = self.trd_ctx.position_list_query(trd_env=self.trd_env)
            if ret == RET_OK and not data.empty:
                # 查找对应股票的持仓
                position = data[data['code'] == code]
                if not position.empty:
                    qty = int(position.iloc[0]['qty'])
                    return qty
            return 0
        except Exception as e:
            self.log_message.emit(f"获取持仓异常 {code}: {e}")
            return 0

    def _initialize_position_trackers(self):
        """为现有持仓初始化追踪止损器"""
        self.log_message.emit("🛡️ 正在为现有持仓初始化风险监控...")
        try:
            ret, data = self.trd_ctx.position_list_query(trd_env=self.trd_env)
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
                        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        start_time = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
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
                                    'atr_multiplier': 2.0
                                }
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
        chart_paths = signal['chart_paths']
        bsp_type = signal['bsp_type']
        
        bsp_time_str = signal.get('chan_result', {}).get('bsp_datetime_str', '')
        cache_key = f"{code}_{bsp_time_str}_{bsp_type}"
        bsp_type_display = f"{'b' if signal['is_buy'] else 's'}{bsp_type}"
        
        # --- 0. ML 优先审查 & 一票否决 ---
        ml_res = {}
        if signal.get('is_buy'):
            chan_env = signal.get('chan_result', {}).get('chan_analysis', {}).get('chan_30m')
            if chan_env:
                bsp_list = chan_env.get_bsp()
                if bsp_list:
                    ml_start = time.perf_counter()
                    ml_res = self.signal_validator.validate_signal(chan_env, bsp_list[-1], threshold=self.ml_threshold)
                    prob = ml_res.get('prob', 0)
                    
                    if prob < self.ml_threshold:
                        self.log_message.emit(f"🤖 {code} {bsp_type_display} ML 未达标 ({prob*100:.1f}% < {self.ml_threshold*100:.0f}%) -> 一票否决，跳过视觉评分")
                        return None
                    self.log_message.emit(f"🤖 {code} {bsp_type_display} ML 校验通过 ({prob*100:.1f}%) -> 继续触发视觉评估")

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
            
            score = visual_result.get('score', 0)
            action = visual_result.get('action', 'WAIT')
            analysis = visual_result.get('analysis', '')
            
            # Assuming bsp_type_display is available from signal processing
            bsp_type_display = f"{'b' if signal['is_buy'] else 's'}{bsp_type}"
            
            self.log_message.emit(f"✅ {code} {bsp_type_display} 评分完成: {score}")
            
            # --- 2. 视觉验证 (已经过 ML 达标过滤) ---
            if score < 70:
                self.log_message.emit(f"🤖 {code} {bsp_type_display} 拦截 [ML:{ml_res.get('prob', 0):.2f}, Visual:{score}]: 视觉得分不达标(<70)")
                return None
            else:
                self.log_message.emit(f"✅ {code} {bsp_type_display} 准入 [ML:{ml_res.get('prob', 0):.2f}, Visual:{score}]: 三项阈值均达标 (包含缠论买卖点)")

            # 添加评分结果到信号数据
            scored_signal = signal.copy()
            scored_signal['score'] = score
            scored_signal['visual_result'] = visual_result
            # Assuming chart_path refers to the primary chart for notification,
            # taking the first one if chart_paths is a list.
            scored_signal['chart_path'] = chart_paths[0] if chart_paths else None

            # --- Discord 推送 ---
            if self.discord_bot and score >= self.min_visual_score:
                msg = (
                    f"🎯 **发现港股交易信号**\n"
                    f"股票: {code}\n"
                    f"信号: {bsp_type_display}\n"
                    f"价格: {signal['current_price']}\n"
                    f"评分: {score}\n"
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
            
            # 1. 查询所有持仓
            ret, data = self.trd_ctx.position_list_query(trd_env=self.trd_env)
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