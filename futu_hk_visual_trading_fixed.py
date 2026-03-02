#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货港股视觉交易系统 - 修复版
"""

import os
import sys
import time
import logging
import shutil
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
import aiohttp

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

# 导入配置
from config import TRADING_CONFIG, CHAN_CONFIG

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from futu import *
from visual_judge import VisualJudge
from send_email_report import send_stock_report

# 添加 dotenv 支持
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'email_config.env'))

# 导入配置
from config import TRADING_CONFIG, CHAN_CONFIG

# 导入交易日检查函数
from scheduler_config import is_trading_day

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('futu_hk_trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FutuHKVisualTrading:
    def __init__(self,
                 hk_watchlist_group: str = None,
                 min_visual_score: int = None,
                 max_position_ratio: float = None,
                 dry_run: bool = None):
        """
        初始化港股视觉交易系统
        
        Args:
            hk_watchlist_group: 自选股组名
            min_visual_score: 最小视觉评分阈值
            max_position_ratio: 单票最大仓位比例
            dry_run: 是否为模拟盘模式
        """
        # 使用配置文件中的默认值，如果提供了参数则覆盖
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
        
        # 交易环境
        self.trd_env = TrdEnv.SIMULATE # if dry_run else TrdEnv.REAL # 强制使用模拟盘进行调试
        
        # 缠论配置 - 启用MACD计算（严格模式 + 线段）
        self.chan_config = CChanConfig(CHAN_CONFIG)
        
        # 视觉评分器
        self.visual_judge = VisualJudge()
        
        # 信号执行历史记录文件
        self.executed_signals_file = "executed_signals.json"
        self.executed_signals = self._load_executed_signals()
        
        logger.info(f"初始化完成 - 模拟盘: {dry_run}, 评分阈值: {min_visual_score}")
    
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
                    logger.info(f"{code} 发现已有 {side} 待成交订单，订单ID: {pending.iloc[0]['order_id']}")
                    return True
            return False
        except Exception as e:
            logger.error(f"检查待成交订单异常 {code}: {e}")
            return False
    
    def send_email_notification(self, scan_summary):
        """
        发送扫描结果邮件
        """
        try:
            all_signals = scan_summary.get('all_signals', [])
            if not all_signals:
                logger.info("没有发现交易信号，不发送邮件。")
                # Even if there are no signals, we might want to send a "still alive" email.
                # For now, we only send emails when there are signals.
                return

            all_chart_paths = []
            for signal in all_signals:
                stock_info = self.get_stock_info(signal['code'])
                signal['stock_name'] = stock_info.get('name', '')
                chart_paths = signal.get('chart_paths', [])
                if chart_paths:
                    all_chart_paths.extend(chart_paths)

            now = datetime.now()
            subject = f"港股交易信号 - {now.strftime('%Y-%m-%d %H:%M')}"

            send_stock_report(all_signals, all_chart_paths, subject=subject)
        except Exception as e:
            logger.error(f"发送邮件通知异常: {e}")

    def close_connections(self):
        """关闭富途连接"""
        if hasattr(self, 'quote_ctx'):
            self.quote_ctx.close()
        if hasattr(self, 'trd_ctx'):
            self.trd_ctx.close()
    
    def get_watchlist_codes(self) -> List[str]:
        """
        获取港股自选股列表
        
        Returns:
            股票代码列表
        """
        try:
            ret, data = self.quote_ctx.get_user_security(self.hk_watchlist_group)
            if ret == RET_OK:
                codes = data['code'].tolist()
                # 过滤港股代码
                hk_codes = [code for code in codes if code.startswith(('HK.', 'SH.', 'SZ.'))]
                logger.info(f"获取到 {len(hk_codes)} 只港股: {hk_codes[:10]}...")
                return hk_codes
            else:
                logger.error(f"获取自选股失败: {data}")
                return []
        except Exception as e:
            logger.error(f"获取自选股异常: {e}")
            return []
    
    def get_stock_info(self, code: str) -> Dict:
        """
        获取股票信息
        
        Args:
            code: 股票代码
            
        Returns:
            包含价格、市值、每手股数等信息的字典
        """
        try:
            ret, data = self.quote_ctx.get_market_snapshot([code])
            if ret == RET_OK and not data.empty:
                stock_info = data.iloc[0].to_dict()
                return {
                    'current_price': stock_info['last_price'],
                    'name': stock_info.get('stock_name', ''),
                    'market_val': stock_info.get('market_val', 0),
                    'turnover_rate': stock_info.get('turnover_rate', 0),
                    'volume': stock_info.get('volume', 0),
                    'lot_size': int(stock_info.get('lot_size', 100))
                }
            else:
                logger.warning(f"无法获取 {code} 的市场快照")
                return {}
        except Exception as e:
            logger.error(f"获取股票信息异常 {code}: {e}")
            return {}
    
    def calculate_position_size(self, current_price: float, available_funds: float, lot_size: int = 100) -> int:
        """
        计算持仓大小
        
        Args:
            current_price: 当前价格
            available_funds: 可用资金
            
        Returns:
            买入股数
        """
        if current_price <= 0:
            return 0
        
        # 计算最大可投资金（总资金的20%）
        max_investment = available_funds * self.max_position_ratio
        
        # 计算股数（以手为单位，每手100股或根据股票调整）
        shares_to_buy = int(max_investment / current_price)
        
        # 确保最小购买量
        # 向下取整到最接近的整手
        lots = shares_to_buy // lot_size
        final_quantity = lots * lot_size
        
        return max(0, final_quantity)
        lot_size = max(min_lot_size, shares_to_buy // 100 * 100)
        
        return max(0, lot_size)
    
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
            logger.warning("pandas_market_calendars 未安装，使用原始方法计算交易时间")
            # 使用配置中的交易时间
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
    
    def analyze_with_chan(self, code: str) -> Optional[Dict]:
        """
        使用CChan分析股票
        
        Args:
            code: 股票代码
            
        Returns:
            分析结果字典
        """
        try:
            # 获取30分钟和5分钟K线数据（一次性获取多级别数据）
            end_time = datetime.now()
            start_time = end_time - timedelta(days=30)  # 30天数据用于30M分析
            
            # 首先尝试获取30M数据
            try:
                # 一次性初始化包含30M和5M两个级别的CChan对象
                chan_multi_level = CChan(
                    code=code,
                    begin_time=start_time.strftime("%Y-%m-%d"),
                    end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                    data_src=DATA_SRC.FUTU,
                    lv_list=[KL_TYPE.K_30M, KL_TYPE.K_5M],  # 同时获取30M和5M数据
                    config=self.chan_config
                )
            except Exception as e:
                logger.warning(f"{code} 获取多级别数据失败: {e}，尝试仅使用30M数据")
                # 如果5M数据有问题，只使用30M数据
                chan_multi_level = CChan(
                    code=code,
                    begin_time=start_time.strftime("%Y-%m-%d"),
                    end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                    data_src=DATA_SRC.FUTU,
                    lv_list=[KL_TYPE.K_30M],  # 仅使用30M数据
                    config=self.chan_config
                )
            
            # 从30M级别获取最新的买卖点
            # 修复：使用 CChan.get_latest_bsp 并在 KLine_List 上正确调用
            latest_bsps = chan_multi_level.get_latest_bsp(idx=0, number=1)
            if not latest_bsps:
                logger.debug(f"{code} 未发现买卖点")
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
                logger.info(f"{code} {bsp_type} 信号产生于 {bsp_time.strftime('%Y-%m-%d %H:%M')}，"
                           f"距今 {trading_hours:.1f} 个交易小时，超过{TRADING_CONFIG['max_signal_age_hours']}小时窗口，跳过")
                return None
            
            logger.info(f"{code} {bsp_type} 信号在{TRADING_CONFIG['max_signal_age_hours']}小时窗口内（{trading_hours:.1f}个交易小时前），继续分析")
            
            result = {
                'code': code,
                'bsp_type': bsp_type,
                'is_buy_signal': is_buy,
                'bsp_price': price,
                'bsp_datetime': bsp.klu.time,
                'bsp_datetime_str': bsp_time.strftime("%Y-%m-%d %H:%M:%S"),
                'chan_analysis': {
                    'chan_multi_level': chan_multi_level  # 保存多级别对象，供后续图表生成使用
                }
            }
            
            logger.info(f"{code} 缠论分析: {bsp_type} 信号, 价格: {price}")
            return result
            
        except Exception as e:
            logger.error(f"CChan分析异常 {code}: {e}")
            # 捕获特定的K线数据不足错误
            if "在次级别找不到K线条数超过" in str(e) or "次级别" in str(e):
                logger.warning(f"{code} 因K线数据不足跳过分析")
            return None
    
    
    def generate_charts(self, code: str, chan_multi_level: CChan) -> List[str]:
        """
        生成技术图表（AI视觉优化版）
        """
        chart_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_code = code.replace('.', '_').replace('-', '_')
        original_lv_list = chan_multi_level.lv_list
        
        try:
            for lv in original_lv_list:
                # 暂时修改级别列表以生成单层图表
                chan_multi_level.lv_list = [lv]
                
                # 生成技术图表（统一为 A 股格式）
                plot_driver = CPlotDriver(
                    chan_multi_level,
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
                
                chart_path = f"{self.charts_dir}/{safe_code}_{timestamp}_{lv.name.replace('K_','')}.png"
                plt.savefig(chart_path, bbox_inches='tight', dpi=120, facecolor='white')
                plt.close('all')
                chart_paths.append(chart_path)
            return chart_paths
        except Exception as e:
            logger.error(f"生成图表异常 {code}: {e}")
            return []
        finally:
            chan_multi_level.lv_list = original_lv_list
    
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
            logger.warning(f"无效数量 {quantity}，跳过交易 {code}")
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
                    logger.info(f"买入订单已提交 {code}: 数量={quantity}, 价格={order_price}, 订单ID={order_id}")
                    return True
                else:
                    logger.error(f"买入订单失败 {code}: {data}")
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
                    logger.info(f"卖出订单已提交 {code}: 数量={quantity}, 价格={order_price}, 订单ID={order_id}")
                    return True
                else:
                    logger.error(f"卖出订单失败 {code}: {data}")
                    return False
            else:
                logger.warning(f"未知交易动作: {action}")
                return False
                
        except Exception as e:
            logger.error(f"执行交易异常 {code}: {e}")
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
                logger.info(f"可用资金：{available_funds:,.2f} HKD")
                return float(available_funds)
            else:
                logger.error(f"获取账户信息失败：{data}")
                return 0.0
        except Exception as e:
            logger.error(f"获取资金信息异常：{e}")
            return 0.0
        
    def _collect_candidate_signals(self, watchlist_codes: List[str]) -> List[Dict]:
        """
        收集候选信号 - 第一步
        返回包含股票代码、缠论分析结果和股票信息的数据结构，但不包括图表和评分
        """
        logger.info("开始收集候选信号...")
        candidate_signals = []
        
        for code in watchlist_codes:
            logger.info(f"分析股票: {code}")
            
            # 获取股票信息
            stock_info = self.get_stock_info(code)
            if not stock_info:
                continue
            
            current_price = stock_info['current_price']
            if current_price <= 0:
                logger.warning(f"{code} 价格无效，跳过")
                continue
            
            # 缠论分析
            chan_result = self.analyze_with_chan(code)
            if not chan_result:
                logger.debug(f"{code} 无缠论信号，跳过")
                continue
            
            # 记录信号类型
            bsp_type = chan_result.get('bsp_type', '未知')
            is_buy = chan_result.get('is_buy_signal', False)
            bsp_time_str = chan_result.get('bsp_datetime_str', '')  # 需要在 analyze_with_chan 中添加
            bsp_type_display = f"{'b' if is_buy else 's'}{bsp_type}"
            
            # ====== 信号去重逻辑：检查持久化记录 ======
            last_executed_time = self.executed_signals.get(code, "")
            if last_executed_time == bsp_time_str:
                logger.info(f"{code} {bsp_type_display} 信号时间 {bsp_time_str} 与历史记录一致，跳过重复处理")
                continue

            logger.info(f"{code} 信号类型: {bsp_type_display}, 是否买入: {is_buy}")
            
            # 持仓过滤
            position_qty = self.get_position_quantity(code)
            
            if is_buy and position_qty > 0:
                logger.info(f"{code} 已有持仓({position_qty}股)，跳过买入")
                continue
            
            if not is_buy and position_qty <= 0:
                logger.info(f"{code} 无持仓，跳过卖出")
                continue
            
            # ====== 待成交订单过滤 ======
            side_str = 'BUY' if is_buy else 'SELL'
            if self.check_pending_orders(code, side_str):
                logger.info(f"{code} 存在活跃 {side_str} 订单，跳过下单")
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
            candidate_signals.append(signal_data)
            logger.info(f"✅ {code} 候选信号已收集")
        
        logger.info(f"共收集到 {len(candidate_signals)} 个候选信号")
        return candidate_signals

    def _generate_single_chart(self, signal_data: Dict) -> Optional[Dict]:
        """
        生成单个图表的辅助函数，用于并行处理
        """
        code = signal_data['code']
        chan_result = signal_data['chan_result']
        
        try:
            # 生成图表
            chart_paths = self.generate_charts(code, chan_result['chan_analysis']['chan_multi_level'])
            if not chart_paths:
                logger.warning(f"{code} 图表生成失败")
                return None
            
            # 添加图表路径到信号数据
            signal_with_chart = signal_data.copy()
            signal_with_chart['chart_paths'] = chart_paths
            logger.info(f"✅ {code} 图表已生成 ({len(chart_paths)} 张)")
            return signal_with_chart
        except Exception as e:
            logger.error(f"生成图表异常 {code}: {e}")
            return None

    def _batch_generate_charts(self, candidate_signals: List[Dict]) -> List[Dict]:
        """
        批量生成图表 - 第二步 (并行化版本)
        """
        logger.info(f"开始批量生成图表，共 {len(candidate_signals)} 个信号")
        
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
        
        logger.info(f"批量图表生成完成，成功生成 {len(signals_with_charts)} 个带图表的信号")
        return signals_with_charts

    async def _async_evaluate_single_signal(self, session: aiohttp.ClientSession, signal: Dict) -> Optional[Dict]:
        """
        异步评估单个信号的辅助函数
        """
        code = signal['code']
        chart_paths = signal['chart_paths']
        bsp_type = signal['bsp_type']  # 使用信号类型作为额外信息
        
        try:
            # 使用线程池执行器来异步调用同步的evaluate方法
            loop = asyncio.get_event_loop()
            visual_result = await loop.run_in_executor(None, self.visual_judge.evaluate, chart_paths, bsp_type)
            
            score = visual_result.get('score', 0)
            action = visual_result.get('action', 'WAIT')
            analysis = visual_result.get('analysis', '')
            
            logger.info(f"{code} 视觉评分: {score}/100, 建议: {action}")
            
            # 添加评分结果到信号数据
            scored_signal = signal.copy()
            scored_signal['score'] = score
            scored_signal['visual_result'] = visual_result
            
            logger.info(f"✅ {code} 评分已完成 (评分: {score})")
            return scored_signal
            
        except Exception as e:
            logger.error(f"视觉评分异常 {code}: {e}")
            # 即使视觉评分失败，也添加信号（评分为0）
            scored_signal = signal.copy()
            scored_signal['score'] = 0
            scored_signal['visual_result'] = {'score': 0, 'action': 'ERROR', 'analysis': '视觉评分失败'}
            logger.info(f"⚠️ {code} 评分失败，但信号已添加")
            return scored_signal

    async def _batch_score_signals_async(self, signals_with_charts: List[Dict]) -> List[Dict]:
        """
        异步批量评分信号 - 第三步
        """
        logger.info(f"开始异步批量评分，共 {len(signals_with_charts)} 个带图表的信号")
        
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
                logger.error(f"评分任务异常: {result}")
            else:
                scored_signals.append(result)
        
        # 移除可能的None值
        scored_signals = [s for s in scored_signals if s is not None]
        
        logger.info(f"异步批量评分完成，共 {len(scored_signals)} 个已评分信号")
        return scored_signals

    def _batch_score_signals(self, signals_with_charts: List[Dict]) -> List[Dict]:
        """
        批量评分信号 - 第三步 (同步包装器)
        """
        # 使用 asyncio.run 来运行异步方法
        return asyncio.run(self._batch_score_signals_async(signals_with_charts))
    
    def _execute_trades(self, all_signals: List[Dict], available_funds_at_start: float) -> Tuple[List[Dict], int, int, float]:
        """
        执行交易 - 第四步
        """
        # 分离并排序信号
        sell_signals = [s for s in all_signals if not s['is_buy']]
        buy_signals = [s for s in all_signals if s['is_buy']]
        
        # 按评分从高到低排序
        sell_signals.sort(key=lambda x: x['score'], reverse=True)
        buy_signals.sort(key=lambda x: x['score'], reverse=True)
        
        logger.info(f"卖出信号: {len(sell_signals)}个, 买入信号: {len(buy_signals)}个")
        
        # 执行卖点（优先）
        available_funds = available_funds_at_start
        executed_sell = 0
        executed_buy = 0
        
        if sell_signals:
            logger.info(f"\n>>> 开始执行卖出操作（共{len(sell_signals)}个）")
            for i, signal in enumerate(sell_signals, 1):
                code = signal['code']
                score = signal['score']
                qty = signal['position_qty']
                price = signal['current_price']
                bsp_type = signal['bsp_type']
                
                logger.info(f"\n[{i}/{len(sell_signals)}] 卖出 {code} - {bsp_type} - 评分: {score}")
                
                # 只有视觉评分 >= 阈值才执行交易
                if score >= self.min_visual_score:
                    if self.execute_trade(code, 'SELL', qty, price):
                        # 卖出成功，释放资金，更新信号历史记录
                        released_funds = price * qty
                        available_funds += released_funds
                        executed_sell += 1
                        
                        # 记录已执行信号，防止重复处理同一信号
                        bsp_time_str = signal.get('chan_result', {}).get('bsp_datetime_str', '')
                        if bsp_time_str:
                            self.executed_signals[code] = bsp_time_str
                            self._save_executed_signals()
                            
                        logger.info(f"✅ 卖出成功 {code}, 释放资金: {released_funds:.2f}, 当前可用: {available_funds:.2f}")
                    else:
                        logger.error(f"❌ 卖出失败 {code}")
                else:
                    logger.info(f"⏭️ 卖出信号 {code} 评分({score})低于阈值({self.min_visual_score})，仅通知不执行")
        
        # 执行买点
        if buy_signals:
            logger.info(f"\n>>> 开始执行买入操作（共{len(buy_signals)}个）")
            for i, signal in enumerate(buy_signals, 1):
                code = signal['code']
                score = signal['score']
                price = signal['current_price']
                bsp_type = signal['bsp_type']
                
                # 只有视觉评分 >= 阈值才执行交易
                if score >= self.min_visual_score:
                    # 计算可买入数量
                    buy_quantity = self.calculate_position_size(price, available_funds, signal.get('lot_size', 100))
                    
                    if buy_quantity <= 0:
                        logger.warning(f"[{i}/{len(buy_signals)}] {code} 资金不足，跳过 (可用: {available_funds:.2f})")
                        continue
                    
                    required_funds = price * buy_quantity
                    
                    logger.info(f"\n[{i}/{len(buy_signals)}] 买入 {code} - {bsp_type} - 评分: {score}")
                    logger.info(f"   计划买入: {buy_quantity}股, 预计花费: {required_funds:.2f}")
                    
                    if self.execute_trade(code, 'BUY', buy_quantity, price):
                        # 买入成功，扣除资金，更新信号历史记录
                        available_funds -= required_funds
                        executed_buy += 1
                        
                        # 记录已执行信号，防止重复处理同一信号
                        bsp_time_str = signal.get('chan_result', {}).get('bsp_datetime_str', '')
                        if bsp_time_str:
                            self.executed_signals[code] = bsp_time_str
                            self._save_executed_signals()
                            
                        logger.info(f"✅ 买入成功 {code}, 剩余资金: {available_funds:.2f}")
                    else:
                        logger.error(f"❌ 买入失败 {code}")
                else:
                    logger.info(f"⏭️ 买入信号 {code} 评分({score})低于阈值({self.min_visual_score})，仅通知不执行")
        
        logger.info(f"\n扫描交易完成，最终可用资金: {available_funds:.2f}")
        return sell_signals, buy_signals, executed_sell, executed_buy, available_funds

    def scan_and_trade(self):
        """
        批量扫描并执行交易
        逻辑：收集所有信号 → 批量生成图表 → 批量评分 → 执行交易
        """
        # ========== 诊断检查：磁盘空间 ==========
        import shutil
        total, used, free = shutil.disk_usage("/")
        logger.info(f"[DIAGNOSTIC] 磁盘空间 - 总计：{total//1024//1024}MB, 已用：{used//1024//1024}MB, 可用：{free//1024//1024}MB")
        if free < 500 * 1024 * 1024:  # 少于 500MB
            logger.error(f"[DIAGNOSTIC] 磁盘空间不足！仅剩 {free//1024//1024}MB，建议清理后再运行")
            raise Exception("磁盘空间不足，无法继续运行")
        # ========================================
        
        # 检查是否为交易日
        if not is_trading_day():
            today = datetime.now().strftime('%Y-%m-%d')
            weekday = datetime.now().strftime('%A')
            logger.info(f"📭 今日是非交易日 ({today} {weekday})，跳过扫描")
            return
        
        logger.info("开始批量扫描交易...")
        
        # 获取自选股
        watchlist_codes = self.get_watchlist_codes()
        if not watchlist_codes:
            logger.warning("没有获取到自选股，退出扫描")
            return
        
        # 获取初始可用资金
        available_funds = self.get_available_funds()
        available_funds_at_start = available_funds  # 记录初始资金用于备忘录对比
        if available_funds <= 0:
            logger.error("可用资金不足，退出扫描")
            return
        
        # ========== 第一阶段：收集所有候选信号 ==========
        candidate_signals = self._collect_candidate_signals(watchlist_codes)
        
        # ========== 第二阶段：如果没有候选信号，直接发送结果 ==========
        if not candidate_signals:
            # 即使没有信号也继续执行，让备忘录函数处理
            try:
                scan_summary = {
                    'total_stocks': len(watchlist_codes),
                    'all_signals': [],  # 所有缠论信号
                    'sell_signals': [],
                    'buy_signals': [],
                    'executed_sells': 0,
                    'executed_buys': 0,
                    'initial_funds': available_funds_at_start,
                    'final_funds': available_funds,
                    'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                self.send_email_notification(scan_summary)
            except Exception as e:
                logger.error(f"发送扫描结果到备忘录失败: {e}")
            return
        
        # ========== 第三阶段：批量生成图表 ==========
        signals_with_charts = self._batch_generate_charts(candidate_signals)
        
        # ========== 第四阶段：如果没有图表，直接发送结果 ==========
        if not signals_with_charts:
            # 即使没有成功生成图表的信号也继续执行
            try:
                scan_summary = {
                    'total_stocks': len(watchlist_codes),
                    'all_signals': [],  # 所有缠论信号
                    'sell_signals': [],
                    'buy_signals': [],
                    'executed_sells': 0,
                    'executed_buys': 0,
                    'initial_funds': available_funds_at_start,
                    'final_funds': available_funds,
                    'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                self.send_email_notification(scan_summary)
            except Exception as e:
                logger.error(f"发送扫描结果到备忘录失败: {e}")
            return
        
        # ========== 第五阶段：批量评分信号 ==========
        all_signals = self._batch_score_signals(signals_with_charts)
        
        # ========== 第六阶段：执行交易 ==========
        sell_signals, buy_signals, executed_sell, executed_buy, final_funds = self._execute_trades(
            all_signals, available_funds_at_start
        )
        
        # ========== 第七阶段：发送扫描结果到备忘录 ==========
        try:
            scan_summary = {
                'total_stocks': len(watchlist_codes),
                'all_signals': all_signals,  # 所有缠论信号
                'sell_signals': sell_signals,
                'buy_signals': buy_signals,
                'executed_sells': executed_sell,
                'executed_buys': executed_buy,
                'initial_funds': available_funds_at_start,
                'final_funds': final_funds,
                'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self.send_email_notification(scan_summary)
        except Exception as e:
            logger.error(f"发送扫描结果到备忘录失败: {e}")

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
                    logger.info(f"{code} 当前持仓: {qty} 股")
                    return qty
            logger.debug(f"{code} 无持仓")
            return 0
        except Exception as e:
            logger.error(f"获取持仓异常 {code}: {e}")
            return 0

def main():
    """主函数"""
    try:
        # 初始化交易系统
        trader = FutuHKVisualTrading()
        trader.scan_and_trade()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在退出...")
    except Exception as e:
        logger.error(f"程序异常: {e}")
    finally:
        # 清理资源
        try:
            trader.close_connections()
        except:
            pass

if __name__ == "__main__":
    main()
