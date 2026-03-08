#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股自动化交易控制器

此模块将 `futu_hk_visual_trading_fixed.py` 中的核心逻辑封装为一个独立的、可被 GUI 调用的类。
它负责处理从信号收集、图表生成、视觉评分到最终交易执行的完整流程。
"""

import os
import sys
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
from config import TRADING_CONFIG, CHAN_CONFIG
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

# 导入本地评分
from Trade.LocalScorer import get_local_scorer

# 导入性能监控
from Monitoring.PerformanceMonitor import get_performance_monitor

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
                 parent=None):
        """
        初始化港股交易控制器。

        Args:
            hk_watchlist_group: 自选股组名
            min_visual_score: 最小视觉评分阈值
            max_position_ratio: 单票最大仓位比例
            dry_run: 是否为模拟盘模式
            parent: 父 QObject (用于 Qt 内存管理)
        """
        super().__init__(parent)
        self.hk_watchlist_group = hk_watchlist_group or TRADING_CONFIG['hk_watchlist_group']
        self.min_visual_score = min_visual_score or TRADING_CONFIG['min_visual_score']
        self.max_position_ratio = max_position_ratio or TRADING_CONFIG['max_position_ratio']
        self.dry_run = dry_run if dry_run is not None else TRADING_CONFIG['dry_run']

        # 创建图表目录
        self.charts_dir = "charts"
        os.makedirs(self.charts_dir, exist_ok=True)

        # 初始化富途连接
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
        self.trd_env = TrdEnv.SIMULATE if self.dry_run else TrdEnv.REAL

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

        # 用于停止扫描的标志
        self._is_running = False

        # 视觉评分缓存 (code_time_type -> score_dict)
        self.visual_score_cache = {}

        self.log_message.emit("✅ 港股交易控制器初始化完成")

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
        self.log_message.emit("🛑 收到停止信号，正在安全退出...")

    def get_watchlist_codes(self) -> List[str]:
        """
        获取富途自选股列表中的港股代码。

        Returns:
            List[str]: 港股代码列表
        """
        try:
            ret, data = self.quote_ctx.get_user_security(group_name=self.hk_watchlist_group)
            if ret == RET_OK and not data.empty:
                # 过滤出以 'HK.' 开头的代码
                hk_codes = data[data['code'].str.startswith('HK.')]['code'].tolist()
                self.log_message.emit(f"成功获取 {len(hk_codes)} 只港股自选股")
                return hk_codes
            else:
                self.log_message.emit(f"获取自选股列表失败: {data}")
                return []
        except Exception as e:
            self.log_message.emit(f"获取自选股列表异常: {e}")
            return []

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
            
            # 顺序获取30M和5M数据（与A股系统保持一致）
            try:
                # 获取30M数据
                chan_30m = CChan(
                    code=code,
                    begin_time=start_time_30m_str,
                    end_time=end_time_str,
                    data_src=DATA_SRC.FUTU,
                    lv_list=[KL_TYPE.K_30M],
                    config=self.chan_config
                )
                
                # 获取5M数据（使用7天范围确保获取最新数据）
                chan_5m = CChan(
                    code=code,
                    begin_time=start_time_5m_str,
                    end_time=end_time_str,
                    data_src=DATA_SRC.FUTU,
                    lv_list=[KL_TYPE.K_5M],
                    config=self.chan_config
                )
            except Exception as e:
                self.log_message.emit(f"获取K线数据异常 {code}: {e}")
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
            
            # 检查5M数据是否足够
            if chan_5m is not None:
                kline_5m_count = 0
                for _ in chan_5m[0].klu_iter():
                    kline_5m_count += 1
                if kline_5m_count < 20:  # 如果5M数据少于20根K线，则认为数据不足
                    self.log_message.emit(f"{code} 5分钟K线数据不足({kline_5m_count}根)，仅使用30M数据进行分析")
                    chan_5m = None
            
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
                self.log_message.emit(f"{code} {bsp_type} 信号产生于 {bsp_time.strftime('%Y-%m-%d %H:%M')}，"
                                   f"距今 {trading_hours:.1f} 个交易小时，超过{TRADING_CONFIG['max_signal_age_hours']}小时窗口，跳过")
                return None
            
            self.log_message.emit(f"{code} {bsp_type} 信号在{TRADING_CONFIG['max_signal_age_hours']}小时窗口内（{trading_hours:.1f}个交易小时前），继续分析")
            
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
            
            self.log_message.emit(f"{code} 缠论分析: {bsp_type} 信号, 价格: {price}")
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
                        plot_para={
                            "figure": {"w": 16, "h": 12, "macd_h": 0.25, "grid": None},
                            "bi": {"show_num": False},
                            "seg": {"color": "#9932CC", "width": 5},  # 紫色线段
                            "zs": {"linewidth": 2},
                            "bsp": {"fontsize": 12, "buy_color": "#C71585", "sell_color": "#C71585"},  # 品红色买卖点
                            "macd": {"width": 0.6}
                        }
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
                        plot_para={
                            "figure": {"w": 16, "h": 12, "macd_h": 0.25, "grid": None},
                            "bi": {"show_num": False},
                            "seg": {"color": "#9932CC", "width": 5},  # 紫色线段
                            "zs": {"linewidth": 2},
                            "bsp": {"fontsize": 12, "buy_color": "#C71585", "sell_color": "#C71585"},  # 品红色买卖点
                            "macd": {"width": 0.6}
                        }
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

    def execute_trade(self, code: str, action: str, quantity: int, price: float) -> bool:
        """
        执行交易

        Args:
            code: 股票代码
            action: 交易动作 ('BUY' or 'SELL')
            quantity: 数量
            price: 价格

        Returns:
            交易是否成功
        """
        if quantity <= 0:
            self.log_message.emit(f"无效数量 {quantity}，跳过交易 {code}")
            return False
        
        try:
            if action.upper() == 'BUY':
                # 买单使用略高价格确保成交，价格保留 3 位小数 (港股精度)
                order_price = round(price * 1.01, 3)
                ret, data = self.trd_ctx.place_order(
                    price=order_price,
                    qty=quantity,
                    code=code,
                    trd_side=TrdSide.BUY,
                    order_type=OrderType.NORMAL,  # 港股增强限价单
                    trd_env=self.trd_env
                )
                
                if ret == RET_OK:
                    order_id = data.iloc[0]['order_id']
                    self.log_message.emit(f"买入订单已提交 {code}: 数量={quantity}, 价格={order_price}, 订单ID={order_id}")
                    return True
                else:
                    self.log_message.emit(f"买入订单失败 {code}: {data}")
                    return False
                    
            elif action.upper() == 'SELL':
                # 卖单使用略低价格确保成交，价格保留 3 位小数 (港股精度)
                order_price = round(price * 0.99, 3)
                ret, data = self.trd_ctx.place_order(
                    price=order_price,
                    qty=quantity,
                    code=code,
                    trd_side=TrdSide.SELL,
                    order_type=OrderType.NORMAL,  # 港股增强限价单
                    trd_env=self.trd_env
                )
                
                if ret == RET_OK:
                    order_id = data.iloc[0]['order_id']
                    self.log_message.emit(f"卖出订单已提交 {code}: 数量={quantity}, 价格={order_price}, 订单ID={order_id}")
                    return True
                else:
                    self.log_message.emit(f"卖出订单失败 {code}: {data}")
                    return False
            else:
                self.log_message.emit(f"未知交易动作: {action}")
                return False
                
        except Exception as e:
            self.log_message.emit(f"执行交易异常 {code}: {e}")
            return False

    def get_available_funds(self) -> float:
        """
        获取可用资金 (模拟盘/实盘都实时查询)

        Returns:
            可用资金金额
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
                self.log_message.emit(f"可用资金：{available_funds:,.2f} HKD")
                return float(available_funds)
            else:
                self.log_message.emit(f"获取账户信息失败：{data}")
                return 0.0
        except Exception as e:
            self.log_message.emit(f"获取资金信息异常：{e}")
            return 0.0

    def run_scan_and_trade(self):
        """
        执行完整的扫描和交易流程。
        这是供 GUI 调用的主要入口方法。内部包含循环机制。
        """
        self._is_running = True
        self.log_message.emit("🚀 启动港股自动化扫描与交易守护进程 (5分钟循环)...")
        
        while self._is_running:
            # 检查是否在交易时间内
            if not self.is_trading_time():
                self.log_message.emit("非交易时间，等待 60 秒后重试...")
                time.sleep(60)
                continue
                
            # 记录开始时间用于性能监控
            start_time = time.time()

        try:
            # 1. 获取自选股列表
            watchlist_codes = self.get_watchlist_codes()
            if not watchlist_codes:
                self.log_message.emit("❌ 自选股列表为空，无法继续。")
                self.scan_finished.emit(0, 0, 0, 0)
                return

            total_stocks = len(watchlist_codes)
            self.log_message.emit(f"📊 准备分析 {total_stocks} 只港股...")

            # 2. 收集候选信号
            candidate_signals = []
            for i, code in enumerate(watchlist_codes, 1):
                if not self._is_running:
                    break
                self.scan_progress.emit(i, total_stocks, f"分析 {code}")
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
                bsp_time_str = chan_result.get('bsp_datetime_str', '')
                bsp_type_display = f"{'b' if is_buy else 's'}{bsp_type}"
                
                # 信号去重逻辑
                last_executed_time = self.executed_signals.get(code, "")
                if last_executed_time == bsp_time_str:
                    self.log_message.emit(f"{code} {bsp_type_display} 信号时间 {bsp_time_str} 已执行过，跳过重复处理")
                    continue
                    
                last_discovered_time = self.discovered_signals.get(code, "")
                if last_discovered_time == bsp_time_str:
                    self.log_message.emit(f"{code} {bsp_type_display} 信号时间 {bsp_time_str} 已发现过，跳过重复通知")
                    continue

                # 持仓过滤
                position_qty = self.get_position_quantity(code)
                if is_buy and position_qty > 0:
                    self.log_message.emit(f"{code} 已有持仓({position_qty}股)，跳过买入")
                    continue
                
                if not is_buy and position_qty <= 0:
                    self.log_message.emit(f"{code} 无持仓，跳过卖出")
                    continue
                
                # 待成交订单过滤
                side_str = 'BUY' if is_buy else 'SELL'
                if self.check_pending_orders(code, side_str):
                    self.log_message.emit(f"{code} 存在活跃 {side_str} 订单，跳过下单")
                    continue
                
                # 收集候选信号
                signal_data = {
                    'code': code,
                    'is_buy': is_buy,
                    'bsp_type': bsp_type,
                    'current_price': current_price,
                    'position_qty': position_qty,
                    'lot_size': stock_info.get('lot_size', 100),
                    'chan_result': chan_result
                }
                
                # 记录已发现的信号
                if bsp_time_str:
                    self.discovered_signals[code] = bsp_time_str
                    self._save_discovered_signals()
                
                candidate_signals.append(signal_data)
                self.log_message.emit(f"✅ {code} 候选信号已收集")

            # 3. 生成图表
            signals_with_charts = []
            for i, signal in enumerate(candidate_signals, 1):
                if not self._is_running:
                    break
                self.scan_progress.emit(i, len(candidate_signals), f"生成图表 {signal['code']}")
                chart_paths = self.generate_charts(signal['code'], signal['chan_result']['chan_analysis'])
                if chart_paths:
                    signal_with_chart = signal.copy()
                    signal_with_chart['chart_paths'] = chart_paths
                    signals_with_charts.append(signal_with_chart)
                    self.log_message.emit(f"✅ {signal['code']} 图表已生成 ({len(chart_paths)} 张)")
                else:
                    self.log_message.emit(f"{signal['code']} 图表生成失败")

            # 4. 批量评分
            if signals_with_charts:
                scored_signals = self._batch_score_signals(signals_with_charts)
                # 记录信号评分
                for signal in scored_signals:
                    self.performance_monitor.record_signal(signal['score'])
            else:
                scored_signals = []

            # 5. 执行交易
            available_funds = self.get_available_funds()
            if scored_signals:
                sell_signals, buy_signals, executed_sell, executed_buy, final_funds = self._execute_trades(
                    scored_signals, available_funds
                )
            else:
                sell_signals, buy_signals, executed_sell, executed_buy, final_funds = [], [], 0, 0, available_funds

            # 6. 发送完成信号
            self.scan_finished.emit(executed_sell, executed_buy, 0, 0)
            
            # 记录扫描性能数据
            end_time = time.time()
            duration = end_time - start_time
            if duration > 0:
                self.performance_monitor.record_scan_performance(len(watchlist_codes), duration)
                self.log_message.emit(f"📊 性能监控: 扫描速度 {len(watchlist_codes)/duration:.2f} 只/秒")

        except Exception as e:
            self.log_message.emit(f"❌ 扫描交易流程发生严重错误: {e}")
            self.scan_finished.emit(0, 0, 0, 0)
            
            # 记录失败的扫描
            self.performance_monitor.record_execution(False)
            
            if self._is_running:
                self.log_message.emit("💤 发生异常，休息 60 秒后重试...")
                time.sleep(60)

        if self._is_running:
            self.log_message.emit("💤 本轮扫描结束，休眠 5 分钟后进入下一轮。")
            # 不阻碍线程停止，拆分 sleep
            for _ in range(300):
                if not self._is_running:
                    break
                time.sleep(1)
        
        self.log_message.emit("🔚 港股自动化扫描与交易守护进程已退出。")

    def _batch_score_signals(self, signals_with_charts: List[Dict]) -> List[Dict]:
        """批量评分信号"""
        # 使用 asyncio.run 来运行异步方法
        return asyncio.run(self._batch_score_signals_async(signals_with_charts))

    def _execute_trades(self, all_signals: List[Dict], available_funds_at_start: float) -> Tuple[List[Dict], int, int, float]:
        """
        执行交易 - 第四步
        """
        # 检查熔断机制
        if self.risk_manager.check_circuit_breaker():
            self.log_message.emit("⚠️ 熔断机制激活，暂停所有交易操作")
            return [], [], 0, 0, available_funds_at_start
        
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
                score = signal['score']
                qty = signal['position_qty']
                price = signal['current_price']
                bsp_type = signal['bsp_type']
                
                self.log_message.emit(f"\n[{i}/{len(sell_signals)}] 卖出 {code} - {bsp_type} - 评分: {score}")
                
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
                            
                        self.log_message.emit(f"✅ 卖出成功 {code}, 释放资金: {released_funds:.2f}, 当前可用: {available_funds:.2f}")
                    else:
                        self.log_message.emit(f"❌ 卖出失败 {code}")
                else:
                    self.log_message.emit(f"⏭️ 卖出信号 {code} 评分({score})低于阈值({self.min_visual_score})，仅通知不执行")
        
        # 执行买点 - 使用风险管理器进行动态仓位控制
        if buy_signals:
            self.log_message.emit(f"\n>>> 开始执行买入操作（共{len(buy_signals)}个）")
            
            max_stocks_to_buy = 5  # 最多买入5只股票
            stocks_bought = 0  # 已买入股票数量
            
            for i, signal in enumerate(buy_signals, 1):
                # 检查是否已达到最大买入股票数量
                if stocks_bought >= max_stocks_to_buy:
                    self.log_message.emit(f"✅ 已达到最大买入股票数量限制({max_stocks_to_buy}只)，停止买入")
                    break
                
                code = signal['code']
                score = signal['score']
                price = signal['current_price']
                bsp_type = signal['bsp_type']
                lot_size = signal.get('lot_size', 100)  # 获取股票的最小手数
                
                # 检查熔断和交易频率限制
                if not self.risk_manager.can_execute_trade(code, score):
                    self.log_message.emit(f"⚠️ 风险管理限制，跳过买入 {code}")
                    continue
                
                # 检查可用资金是否小于5万元，如果是则停止买入
                if available_funds < 50000:
                    self.log_message.emit(f"💰 可用资金({available_funds:.2f})少于5万元，停止买入操作")
                    break
                
                # 只有视觉评分 >= 阈值才执行交易
                if score >= self.min_visual_score:
                    # 使用风险管理器计算动态仓位
                    buy_quantity = self.risk_manager.calculate_position_size(
                        code=code,
                        available_funds=available_funds,
                        current_price=price,
                        signal_score=score,
                        risk_factor=1.0  # 可以根据波动率等计算风险因子
                    )
                    
                    if buy_quantity <= 0:
                        self.log_message.emit(f"[{i}/{len(buy_signals)}] {code} 风险管理器建议不买入或资金不足")
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
                            
                        self.log_message.emit(f"✅ 买入成功 {code}, 剩余资金: {available_funds:.2f}, 已买入{stocks_bought}/{max_stocks_to_buy}只")
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
                # 过滤出正在处理的订单
                active_statuses = [OrderStatus.SUBMITTING, OrderStatus.SUBMITTED, OrderStatus.WAITING_SUBMIT]
                data = data[data['status'].isin(active_statuses)]
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
        """
        计算两个时间点之间的港股交易小时数（排除非交易时段）
        
        港股交易时间：
        - 上午：09:30 - 12:00
        - 下午：13:00 - 16:00
        - 周末和节假日不交易
        
        Args:
            start_time: 信号产生时间
            end_time: 当前时间
            
        Returns:
            交易小时数（浮点数）
        """
        try:
            import pandas_market_calendars as mcal
            
            # 获取港股交易日历
            hkex = mcal.get_calendar('XHKG')
            
            # 获取交易时间段
            schedule = hkex.schedule(start_date=start_time.date(), end_date=end_time.date())
            if schedule.empty:
                return 0.0
            
            total_hours = 0.0
            
            # 遍历每个交易日
            for index, row in schedule.iterrows():
                market_open = row['market_open'].to_pydatetime().replace(tzinfo=None)
                market_close = row['market_close'].to_pydatetime().replace(tzinfo=None)
                
                # 确定当天的计算范围
                day_start = max(start_time, market_open)
                day_end = min(end_time, market_close)
                
                if day_start < day_end:
                    # 计算当天的交易时间
                    day_hours = (day_end - day_start).total_seconds() / 3600
                    total_hours += day_hours
            
            return total_hours
        except ImportError:
            self.log_message.emit("pandas_market_calendars 未安装，使用原始方法计算交易时间")
            # 使用配置中的交易时间
            from config import TRADING_CONFIG
            trading_start_hour, trading_start_minute = map(int, TRADING_CONFIG['trading_hours_start'].split(':'))
            trading_end_hour, trading_end_minute = map(int, TRADING_CONFIG['trading_hours_end'].split(':'))
            lunch_start_hour, lunch_start_minute = map(int, TRADING_CONFIG['lunch_break_start'].split(':'))
            lunch_end_hour, lunch_end_minute = map(int, TRADING_CONFIG['lunch_break_end'].split(':'))
            
            total_hours = 0.0
            current = start_time
            
            while current < end_time:
                # 检查是否是工作日（周一到周五）
                if current.weekday() >= 5:  # 周六或周日
                    current += timedelta(days=1)
                    current = current.replace(hour=0, minute=0, second=0)
                    continue
                
                # 获取当天的交易时段
                morning_start = current.replace(hour=trading_start_hour, minute=trading_start_minute, second=0, microsecond=0)
                morning_end = current.replace(hour=lunch_start_hour, minute=lunch_start_minute, second=0, microsecond=0)
                afternoon_start = current.replace(hour=lunch_end_hour, minute=lunch_end_minute, second=0, microsecond=0)
                afternoon_end = current.replace(hour=trading_end_hour, minute=trading_end_minute, second=0, microsecond=0)
                day_end = current.replace(hour=23, minute=59, second=59)
                
                # 如果当前时间早于上午开盘，跳到开盘时间
                if current < morning_start:
                    current = morning_start
                
                # 计算上午交易时段
                if morning_start <= current < morning_end:
                    segment_end = min(morning_end, end_time)
                    total_hours += (segment_end - current).total_seconds() / 3600
                    current = segment_end
                
                # 计算下午交易时段
                if afternoon_start <= current < afternoon_end:
                    segment_end = min(afternoon_end, end_time)
                    total_hours += (segment_end - current).total_seconds() / 3600
                    current = segment_end
                
                # 如果已经过了下午收盘，进入下一天
                if current >= afternoon_end:
                    current = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0)
                elif morning_end <= current < afternoon_start:
                    # 午休时间，跳到下午开盘
                    current = afternoon_start
            
            return total_hours

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
                    self.log_message.emit(f"{code} 当前持仓: {qty} 股")
                    return qty
            self.log_message.emit(f"{code} 无持仓")
            return 0
        except Exception as e:
            self.log_message.emit(f"获取持仓异常 {code}: {e}")
            return 0

    async def _async_evaluate_single_signal(self, session, signal: Dict) -> Optional[Dict]:
        """
        异步评估单个信号的辅助函数
        """
        code = signal['code']
        chart_paths = signal['chart_paths']
        bsp_type = signal['bsp_type']  # 使用信号类型作为额外信息
        
        # 构建缓存键: 股票代码_时间_信号类型
        bsp_time_str = signal.get('chan_result', {}).get('bsp_datetime_str', '')
        cache_key = f"{code}_{bsp_time_str}_{bsp_type}"
        
        try:
            # 检查缓存
            if cache_key in self.visual_score_cache:
                self.log_message.emit(f"⚡ {code} 命中视觉评分缓存 ({cache_key})")
                visual_result = self.visual_score_cache[cache_key]
            else:
                # 使用线程池执行器来异步调用同步的evaluate方法
                loop = asyncio.get_event_loop()
                visual_result = await loop.run_in_executor(None, self.visual_judge.evaluate, chart_paths, bsp_type)
                if visual_result and visual_result.get('action') != 'ERROR':
                    # 只缓存成功的评分
                    self.visual_score_cache[cache_key] = visual_result
            
            score = visual_result.get('score', 0)
            action = visual_result.get('action', 'WAIT')
            analysis = visual_result.get('analysis', '')
            
            self.log_message.emit(f"{code} 视觉评分: {score}/100, 建议: {action}")
            
            # 添加评分结果到信号数据
            scored_signal = signal.copy()
            scored_signal['score'] = score
            scored_signal['visual_result'] = visual_result
            
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
                    buy_quantity = self.risk_manager.calculate_position_size(
                        code=code,
                        available_funds=self.get_available_funds(),
                        current_price=current_price,
                        signal_score=score,
                        risk_factor=1.0
                    )
                    if buy_quantity <= 0:
                        self.log_message.emit(f"{code} 风险管理器建议不买入或资金不足")
                        return False
                    
                    lot_size = stock_info.get('lot_size', 100)
                    buy_quantity = (buy_quantity // lot_size) * lot_size  # 确保是整手
                    
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