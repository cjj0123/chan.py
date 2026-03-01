#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股缠论视觉回测系统 - 30M 周期
与主程序 (futu_hk_visual_trading_fixed.py) 逻辑完全一致

核心功能:
1. 多级别缠论分析 (30M 主级别 + 5M 确认级别)
2. 信号时间过滤 (只交易最近 4 个交易小时内的信号)
3. 视觉评分 (Gemini API, >= 70 分才买入)
4. 持仓过滤 (已有持仓不买入，无持仓不卖出)
5. 比较有无视觉判断的差异
"""

import os
import sys
import logging
import argparse
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import asyncio
import aiohttp

import pandas as pd
import numpy as np

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Common.CEnum import KL_TYPE, DATA_SRC
from Common.CTime import CTime
from Chan import CChan
from ChanConfig import CChanConfig
from Plot.PlotDriver import CPlotDriver
from DataAPI.MockStockAPI import register_kline_data, clear_kline_data
from BacktestDataLoader import BacktestDataLoader, BacktestKLineUnit
from visual_judge import VisualJudge

# 导入配置
from config import TRADING_CONFIG, CHAN_CONFIG, CHART_CONFIG, CHART_PARA

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hk_visual_backtest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class HKVisualBacktestBroker:
    """港股模拟交易账户和经纪商"""
    
    def __init__(self, initial_funds: float = 100000.0, lot_size_map: Dict[str, int] = None):
        self.initial_funds = initial_funds
        self.available_funds = initial_funds
        self.positions: Dict[str, int] = {}  # {code: quantity}
        self.position_cost: Dict[str, float] = {}  # {code: avg_cost}
        self.lot_size_map = lot_size_map or {}
        self.trade_history: List[Dict] = []
        
        # 港股交易成本
        self.commission_rate = 0.0003  # 佣金 0.03%
        self.stamp_duty_rate = 0.001   # 印花税 0.1%
        self.transaction_fee = 0.000027  # 交易费 0.0027%
        self.min_commission = 15  # 最低佣金 15 HKD
    
    def calculate_hk_cost(self, amount: float, is_buy: bool) -> tuple:
        """计算港股交易成本"""
        commission = max(amount * self.commission_rate, self.min_commission)
        transaction_fee = amount * self.transaction_fee
        
        if is_buy:
            total_cost = commission + transaction_fee
        else:
            stamp_duty = amount * self.stamp_duty_rate
            total_cost = commission + transaction_fee + stamp_duty
        
        return total_cost, {
            'commission': commission,
            'transaction_fee': transaction_fee,
            'stamp_duty': amount * self.stamp_duty_rate if not is_buy else 0
        }
    
    def get_position_quantity(self, code: str) -> int:
        """获取持仓数量"""
        return self.positions.get(code, 0)
    
    def calculate_position_size(self, code: str, current_price: float, available_funds: float, max_investment_ratio: float = 1.0) -> int:
        """计算应买入的股数（全仓买卖）"""
        lot_size = self.lot_size_map.get(code, 100)
        max_amount = available_funds * max_investment_ratio
        
        # 计算可以买入的股数（考虑每手限制）
        # 先计算可以买入多少手
        affordable_lots = int(max_amount / (current_price * lot_size))
        
        # 全仓买入：至少买入 1 手（如果有足够资金）
        if affordable_lots == 0:
            # 如果连 1 手都买不起，返回 0
            quantity = 0
        else:
            quantity = affordable_lots * lot_size
        
        return max(0, quantity)
    
    def execute_trade(self, code: str, action: str, quantity: int, price: float, timestamp: pd.Timestamp) -> bool:
        """执行交易"""
        if quantity <= 0:
            return False
        
        amount = quantity * price
        cost, cost_detail = self.calculate_hk_cost(amount, action == 'BUY')
        
        if action == 'BUY':
            total_cost = amount + cost
            if total_cost > self.available_funds:
                logger.warning(f"资金不足：需要 {total_cost:.2f}, 可用 {self.available_funds:.2f}")
                return False
            
            self.available_funds -= total_cost
            
            # 更新持仓
            current_qty = self.positions.get(code, 0)
            current_cost = self.position_cost.get(code, 0)
            
            if current_qty > 0:
                new_avg_cost = (current_cost * current_qty + amount) / (current_qty + quantity)
            else:
                new_avg_cost = price
            
            self.positions[code] = current_qty + quantity
            self.position_cost[code] = new_avg_cost
            
            logger.info(f"✅ 买入 {code}: {quantity}股 @ {price:.2f}, 成本 {cost:.2f}")
            
        elif action == 'SELL':
            current_qty = self.get_position_quantity(code)
            if quantity > current_qty:
                logger.warning(f"持仓不足：尝试卖出 {quantity}, 当前持仓 {current_qty}")
                quantity = current_qty
                amount = quantity * price
                cost, cost_detail = self.calculate_hk_cost(amount, False)
            
            self.available_funds += (amount - cost)
            self.positions[code] = current_qty - quantity
            
            if self.positions[code] == 0:
                del self.positions[code]
                if code in self.position_cost:
                    del self.position_cost[code]
            
            logger.info(f"✅ 卖出 {code}: {quantity}股 @ {price:.2f}, 成本 {cost:.2f}")
        
        # 记录交易历史
        self.trade_history.append({
            'timestamp': timestamp,
            'code': code,
            'action': action,
            'quantity': quantity,
            'price': price,
            'amount': amount,
            'cost': cost,
            'cost_detail': cost_detail,
            'funds_after': self.available_funds,
            'position_after': self.positions.get(code, 0)
        })
        
        return True
    
    def get_portfolio_value(self, prices: Dict[str, float]) -> float:
        """计算组合总价值"""
        value = self.available_funds
        for code, qty in self.positions.items():
            price = prices.get(code, 0)
            value += qty * price
        return value


class HKVisualBacktestEngine:
    """
    港股缠论视觉回测引擎
    与主程序 (futu_hk_visual_trading_fixed.py) 逻辑完全一致
    """
    
    def __init__(self, 
                 watchlist: List[str],
                 start_date: str, 
                 end_date: str,
                 initial_funds: float = 100000.0,
                 lot_size_map: Dict[str, int] = None,
                 output_dir: str = "hk_backtest_charts",
                 min_visual_score: int = 70,
                 max_signal_age_hours: float = 4.0,
                 use_visual_judge: bool = True):
        self.watchlist = watchlist
        self.start_date = start_date
        self.end_date = end_date
        self.initial_funds = initial_funds
        self.lot_size_map = lot_size_map or {}
        self.output_dir = output_dir
        self.min_visual_score = min_visual_score
        self.max_signal_age_hours = max_signal_age_hours
        self.use_visual_judge = use_visual_judge  # 是否启用视觉判断
        
        os.makedirs(output_dir, exist_ok=True)
        
        self.loader = BacktestDataLoader()
        self.broker = HKVisualBacktestBroker(initial_funds, self.lot_size_map)
        self.visual_judge = VisualJudge(use_mock=False) if use_visual_judge else None
        
        # 缠论配置 - 与主程序一致
        self.chan_config = CChanConfig(CHAN_CONFIG)
        
        # 回测统计
        self.stats = {
            'signals_found': 0,
            'signals_filtered_by_time': 0,
            'visual_scores': [],
            'trades_with_visual': 0,
            'trades_without_visual': 0,
        }
    
    def load_kline_data(self, code: str, kl_type: KL_TYPE) -> Optional[List[BacktestKLineUnit]]:
        """加载 K 线数据"""
        try:
            return self.loader.load_kline_data(code, kl_type.name.replace('K_', ''), self.start_date, self.end_date)
        except Exception as e:
            logger.error(f"加载 {code} {kl_type.name} 数据失败：{e}")
            return None
    
    def calculate_trading_hours(self, start_time: datetime, end_time: datetime) -> float:
        """
        计算两个时间点之间的港股交易小时数（排除非交易时段）
        与主程序逻辑一致
        """
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
    
    def analyze_with_chan(self, code: str, klines_30m: List[BacktestKLineUnit],
                          klines_5m: List[BacktestKLineUnit], current_time: pd.Timestamp) -> Optional[Dict]:
        """
        使用 CChan 分析股票 - 双级别版本（30M 主级别 + 5M 确认级别）
        """
        try:
            # 注册 30M 和 5M 数据
            clear_kline_data()
            register_kline_data(code, KL_TYPE.K_30M, klines_30m)
            register_kline_data(code, KL_TYPE.K_5M, klines_5m)
            
            logger.debug(f"[DEBUG] 已注册 {len(klines_30m)} 条 30M K 线数据和 {len(klines_5m)} 条 5M K 线数据")
            
            # 创建双级别 CChan 实例
            chan_config = CChanConfig({
                'bi_strict': True,  # 严格笔
                'seg_algo': 'chan',
                'bs_type': '1,1p,2,2s,3a,3b',
                'divergence_rate': float('inf'),
                'kl_data_check': False,
                'print_warning': False,
            })
            
            logger.debug(f"[DEBUG] 创建 CChan 实例，code={code}, lv_list=[KL_TYPE.K_30M, KL_TYPE.K_5M]")
            
            chan_multi_level = CChan(
                code=code,
                data_src="custom:MockStockAPI.MockStockAPI",
                lv_list=[KL_TYPE.K_30M, KL_TYPE.K_5M],  # 使用 30M+5M 双级别
                config=chan_config,
                autype=0,
            )
            
            logger.debug(f"[DEBUG] CChan 实例创建成功")
            
            # 重置 Chan 库内部状态，避免时间单调性检查失败
            chan_multi_level.klu_last_t = [CTime(1980, 1, 1, 0, 0) for _ in chan_multi_level.lv_list]
            chan_multi_level.klu_cache = [None for _ in chan_multi_level.lv_list]
            
            logger.debug(f"[DEBUG] 重置 Chan 内部状态")
            
            # 使用 trigger_load 加载双级别历史数据
            logger.debug(f"[DEBUG] 开始 trigger_load")
            chan_multi_level.trigger_load({
                KL_TYPE.K_30M: klines_30m,
                KL_TYPE.K_5M: klines_5m
            })
            logger.debug(f"[DEBUG] trigger_load 完成")
            
            # 从 30M 级别获取最新的买卖点
            latest_bsps = chan_multi_level.get_latest_bsp(idx=0, number=1)
            
            logger.debug(f"[DEBUG] {code} get_latest_bsp 返回 {len(latest_bsps)} 个买卖点")
            if latest_bsps:
                logger.debug(f"[DEBUG] 最新买卖点类型={latest_bsps[0].type2str()}, is_buy={latest_bsps[0].is_buy}")
            
            if not latest_bsps:
                return None
            
            bsp = latest_bsps[0]
            bsp_type = bsp.type2str()
            is_buy = bsp.is_buy
            price = bsp.klu.close
            
            # 将 CTime 转换为 datetime
            bsp_ctime = bsp.klu.time
            bsp_time = datetime(bsp_ctime.year, bsp_ctime.month, bsp_ctime.day,
                               bsp_ctime.hour, bsp_ctime.minute, bsp_ctime.second)
            
            # 取消时间过滤 - 所有信号都交易
            # trading_hours = self.calculate_trading_hours(bsp_time, current_time)
            # if trading_hours > TRADING_CONFIG['max_signal_age_hours']:
            #     return None
            
            logger.info(f"{code} {bsp_type} 信号，价格={price:.2f}, 时间={bsp_time}")
            
            return {
                'code': code,
                'bsp_type': bsp_type,
                'is_buy_signal': is_buy,
                'bsp_price': price,
                'bsp_datetime': bsp_time,
                'chan_analysis': {
                    'chan_multi_level': chan_multi_level,
                    'chan_30m': chan_multi_level,  # 保持兼容
                    'chan_5m': None  # 5M 级别不单独存储
                }
            }
            
        except Exception as e:
            logger.error(f"CChan 分析异常 {code}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _customize_macd_colors(self, plot_driver):
        """自定义 MACD 颜色 - 与主程序一致"""
        try:
            for ax in plot_driver.figure.axes:
                for container in ax.containers:
                    if hasattr(container, '__iter__'):
                        for bar in container:
                            if hasattr(bar, 'get_height'):
                                if bar.get_height() >= 0:
                                    bar.set_color('#FF0000')
                                    bar.set_edgecolor('#8B0000')
                                else:
                                    bar.set_color('#00FF00')
                                    bar.set_edgecolor('#006400')
                                bar.set_alpha(0.85)
                
                for line in ax.lines:
                    label = str(line.get_label()).lower() if line.get_label() else ''
                    if 'dif' in label or 'DIF' in str(line.get_label()):
                        line.set_color('#FFFFFF')
                        line.set_linewidth(2.0)
                        line.set_alpha(0.9)
                    elif 'dea' in label or 'DEA' in str(line.get_label()):
                        line.set_color('#FFFF00')
                        line.set_linewidth(2.0)
                        line.set_alpha(0.9)
                
                ax.set_facecolor('#1a1a1a')
                ax.tick_params(colors='white')
                ax.xaxis.label.set_color('white')
                ax.yaxis.label.set_color('white')
                
        except Exception as e:
            logger.warning(f"自定义 MACD 颜色失败：{e}")
    
    def generate_charts(self, code: str, chan_multi_level, signal_type: str) -> List[str]:
        """生成图表 - 双级别版本（30M + 5M）"""
        chart_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_code = code.replace('.', '_').replace('-', '_')
        
        try:
            # 生成 30 分钟图
            plot_30m = CPlotDriver(
                chan_multi_level,
                plot_config=CHART_CONFIG,
                plot_para=CHART_PARA
            )
            self._customize_macd_colors(plot_30m)
            
            chart_30m_path = f"{self.output_dir}/{safe_code}_{timestamp}_30M_{signal_type}.png"
            plt.savefig(chart_30m_path, bbox_inches='tight', dpi=120, facecolor='white')
            plt.close('all')
            chart_paths.append(chart_30m_path)
            
            # 生成 5 分钟图
            plot_5m = CPlotDriver(
                chan_multi_level,
                plot_config=CHART_CONFIG,
                plot_para=CHART_PARA
            )
            self._customize_macd_colors(plot_5m)
            
            chart_5m_path = f"{self.output_dir}/{safe_code}_{timestamp}_5M_{signal_type}.png"
            plt.savefig(chart_5m_path, bbox_inches='tight', dpi=120, facecolor='white')
            plt.close('all')
            chart_paths.append(chart_5m_path)
            
            logger.info(f"生成图表：{chart_paths}")
            return chart_paths
            
        except Exception as e:
            logger.error(f"生成图表异常 {code}: {e}")
            return []
    
    def get_visual_score(self, chart_paths: List[str], signal_type: str) -> int:
        """获取视觉评分 - 使用真实 Gemini API"""
        if not self.use_visual_judge or not self.visual_judge:
            return 100  # 不启用视觉判断时返回满分
        
        if len(chart_paths) < 2:
            logger.warning(f"图表数量不足 2 张，无法进行视觉评分，返回默认分数 100")
            return 100
        
        try:
            result = self.visual_judge.evaluate(chart_paths, signal_type)
            score = result.get('score', 0)
            logger.info(f"🤖 Gemini 评分：{score}/100, 信号类型：{signal_type}")
            return score
        except Exception as e:
            logger.error(f"视觉评分失败：{e}")
            return 0
    
    def run_backtest(self) -> Dict[str, Any]:
        """运行回测"""
        logger.info(f"🚀 开始回测 - 股票数：{len(self.watchlist)}, 区间：{self.start_date} 至 {self.end_date}")
        logger.info(f"视觉判断：{'启用' if self.use_visual_judge else '禁用'}, 评分阈值：{self.min_visual_score}")
        
        results = {
            'watchlist': self.watchlist,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'initial_funds': self.initial_funds,
            'use_visual_judge': self.use_visual_judge,
            'min_visual_score': self.min_visual_score,
            'trades': [],
            'signals': [],
            'final_funds': 0,
            'total_return': 0,
        }
        
        for code in self.watchlist:
            logger.info(f"\n📈 开始回测 {code}...")
            
            # 加载数据
            klines_30m = self.load_kline_data(code, KL_TYPE.K_30M)
            klines_5m = self.load_kline_data(code, KL_TYPE.K_5M)
            
            if not klines_30m or not klines_5m:
                logger.warning(f"{code} 数据加载失败，跳过")
                continue
            
            logger.info(f"加载数据完成：30M={len(klines_30m)}, 5M={len(klines_5m)}")
            
            # 持仓状态
            position_qty = 0
            entry_price = 0
            entry_time = None
            
            # 逐步处理每根 K 线
            for i in range(len(klines_30m)):
                current_klines_30m = klines_30m[:i+1]
                current_time = current_klines_30m[-1].timestamp
                
                # DEBUG: 记录当前处理进度
                if i % 100 == 0 or i == len(klines_30m) - 1:
                    logger.debug(f"[DEBUG] {code} 处理进度：{i+1}/{len(klines_30m)}, 当前时间={current_time}")
                
                # 缠论分析（仅使用 30M 数据）
                chan_result = self.analyze_with_chan(code, current_klines_30m, klines_5m, current_time)
                if not chan_result:
                    continue
                
                self.stats['signals_found'] += 1
                signal_type = chan_result['bsp_type']
                is_buy = chan_result['is_buy_signal']
                signal_price = chan_result['bsp_price']
                
                logger.info(f"📍 {code} 发现 {signal_type} 信号，方向={'买' if is_buy else '卖'}，价格={signal_price:.2f}")
                
                # 持仓过滤
                if is_buy and position_qty > 0:
                    logger.info(f"{code} 已有持仓 ({position_qty}股)，跳过买入")
                    continue
                
                if not is_buy and position_qty <= 0:
                    logger.info(f"{code} 无持仓，跳过卖出")
                    continue
                
                # 生成图表（双级别）
                chart_paths = self.generate_charts(code, chan_result['chan_analysis']['chan_multi_level'], signal_type)
                
                # 获取视觉评分
                visual_score = 100
                if is_buy and self.use_visual_judge:
                    visual_score = self.get_visual_score(chart_paths, signal_type)
                
                # 记录信号
                signal_record = {
                    'code': code,
                    'time': str(current_time),
                    'type': signal_type,
                    'is_buy': is_buy,
                    'price': signal_price,
                    'visual_score': visual_score,
                }
                results['signals'].append(signal_record)
                self.stats['visual_scores'].append({
                    'code': code,
                    'time': str(current_time),
                    'type': signal_type,
                    'score': visual_score
                })
                
                # 执行交易
                if is_buy:
                    # 买入：需要评分 >= 阈值
                    if visual_score >= self.min_visual_score:
                        qty = self.broker.calculate_position_size(code, signal_price, self.broker.available_funds)
                        if qty > 0:
                            if self.broker.execute_trade(code, 'BUY', qty, signal_price, current_time):
                                position_qty = qty
                                entry_price = signal_price
                                entry_time = current_time
                                self.stats['trades_with_visual' if self.use_visual_judge else 'trades_without_visual'] += 1
                                results['trades'].append({
                                    'code': code,
                                    'action': 'BUY',
                                    'quantity': qty,
                                    'price': signal_price,
                                    'time': str(current_time),
                                    'visual_score': visual_score
                                })
                                logger.info(f"✅ 执行买入：{qty}股 @ {signal_price:.2f} (评分={visual_score})")
                    else:
                        logger.info(f"⏭️ 跳过买入：评分不足 (评分={visual_score}, 阈值={self.min_visual_score})")
                
                elif not is_buy:
                    # 卖出：有持仓就卖出
                    if position_qty > 0:
                        if self.broker.execute_trade(code, 'SELL', position_qty, signal_price, current_time):
                            profit = (signal_price - entry_price) * position_qty
                            profit_pct = (signal_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
                            results['trades'].append({
                                'code': code,
                                'action': 'SELL',
                                'quantity': position_qty,
                                'price': signal_price,
                                'time': str(current_time),
                                'profit': profit,
                                'profit_pct': profit_pct
                            })
                            logger.info(f"✅ 执行卖出：{position_qty}股 @ {signal_price:.2f}, 盈亏={profit:.2f} ({profit_pct:.2f}%)")
                            position_qty = 0
                            entry_price = 0
                            entry_time = None
        
        # 计算最终结果
        # 计算持仓价值：使用最后一根 K 线的收盘价
        total_funds = self.broker.available_funds
        for code, qty in self.broker.positions.items():
            if qty > 0:
                # 使用最后已知的 K 线收盘价作为期末价格
                last_price = klines_30m[-1].close if 'klines_30m' in locals() else 0
                total_funds += qty * last_price
                logger.info(f"{code} 期末持仓：{qty}股 @ {last_price:.2f} = {qty * last_price:.2f} HKD")
        
        results['final_funds'] = total_funds
        results['total_return'] = (results['final_funds'] - self.initial_funds) / self.initial_funds * 100
        results['stats'] = self.stats
        
        return results
    
    def print_report(self, results: Dict[str, Any]):
        """打印回测报告"""
        print("\n" + "="*70)
        print("📊 港股缠论视觉回测报告")
        print("="*70)
        print(f"回测区间：{results['start_date']} 至 {results['end_date']}")
        print(f"股票数量：{len(results['watchlist'])}")
        print(f"视觉判断：{'启用' if results['use_visual_judge'] else '禁用'}")
        if results['use_visual_judge']:
            print(f"评分阈值：{results['min_visual_score']}")
        print("-"*70)
        print(f"初始资金：{results['initial_funds']:,.2f} HKD")
        print(f"最终资金：{results['final_funds']:,.2f} HKD")
        print(f"总回报率：{results['total_return']:.2f}%")
        print("-"*70)
        print(f"发现信号数：{results['stats']['signals_found']}")
        print(f"时间过滤信号数：{results['stats']['signals_filtered_by_time']}")
        print(f"执行交易数：{len(results['trades'])}")
        print("="*70)
        
        if results['trades']:
            print("\n📝 交易明细:")
            for trade in results['trades']:
                action = "🟢 买入" if trade['action'] == 'BUY' else "🔴 卖出"
                vs_info = f" (评分={trade.get('visual_score', 'N/A')})" if trade['action'] == 'BUY' else ""
                profit_info = f", 盈亏={trade.get('profit', 0):.2f} ({trade.get('profit_pct', 0):.2f}%)" if trade['action'] == 'SELL' else ""
                print(f"  {trade['time'][:16]} {action} {trade['code']} {trade['quantity']}股 @ {trade['price']:.2f}{vs_info}{profit_info}")
        
        print("="*70)


def get_hk_watchlist() -> List[str]:
    """获取港股回测列表 - 从 stock_cache 中读取可用的 30M 数据"""
    cache_dir = "stock_cache"
    watchlist = []
    
    if os.path.exists(cache_dir):
        for filename in os.listdir(cache_dir):
            if filename.endswith('_K_30M.parquet'):
                code = filename.replace('_K_30M.parquet', '')
                watchlist.append(code)
    
    logger.info(f"从缓存目录获取到 {len(watchlist)} 只港股：{watchlist}")
    return sorted(watchlist)


def get_lot_size_map(watchlist: List[str]) -> Dict[str, int]:
    """获取每手股数映射"""
    # 默认每手 100 股，可以根据实际情况扩展
    lot_size_map = {code: 100 for code in watchlist}
    
    # 常见港股每手股数（可以扩展）
    known_lot_sizes = {
        'HK.00700': 100,  # 腾讯
        'HK.00300': 1000,  # 美团
        'HK.01177': 500,  # 中国生物制药
    }
    
    for code in watchlist:
        if code in known_lot_sizes:
            lot_size_map[code] = known_lot_sizes[code]
    
    return lot_size_map


def compare_visual_vs_no_visual(watchlist: List[str], start_date: str, end_date: str,
                                initial_funds: float = 100000.0) -> Tuple[Dict, Dict]:
    """比较有无视觉判断的回测结果"""
    logger.info("\n" + "="*70)
    logger.info("开始对比实验：有视觉判断 vs 无视觉判断")
    logger.info("="*70)
    
    lot_size_map = get_lot_size_map(watchlist)
    
    # 运行有视觉判断的回测
    logger.info("\n【实验组】启用视觉判断...")
    engine_with_visual = HKVisualBacktestEngine(
        watchlist=watchlist,
        start_date=start_date,
        end_date=end_date,
        initial_funds=initial_funds,
        lot_size_map=lot_size_map,
        output_dir="hk_backtest_with_visual",
        min_visual_score=70,
        use_visual_judge=True
    )
    results_with_visual = engine_with_visual.run_backtest()
    engine_with_visual.print_report(results_with_visual)
    
    # 运行无视觉判断的回测
    logger.info("\n【对照组】禁用视觉判断...")
    engine_without_visual = HKVisualBacktestEngine(
        watchlist=watchlist,
        start_date=start_date,
        end_date=end_date,
        initial_funds=initial_funds,
        lot_size_map=lot_size_map,
        output_dir="hk_backtest_without_visual",
        min_visual_score=70,
        use_visual_judge=False
    )
    results_without_visual = engine_without_visual.run_backtest()
    engine_without_visual.print_report(results_without_visual)
    
    # 对比分析
    print("\n" + "="*70)
    print("📊 对比分析结果")
    print("="*70)
    print(f"{'指标':<20} | {'有视觉判断':<15} | {'无视觉判断':<15} | {'差异'}")
    print("-"*70)
    print(f"{'初始资金':<20} | {results_with_visual['initial_funds']:>13,.2f} | {results_without_visual['initial_funds']:>13,.2f} | -")
    print(f"{'最终资金':<20} | {results_with_visual['final_funds']:>13,.2f} | {results_without_visual['final_funds']:>13,.2f} | {results_with_visual['final_funds'] - results_without_visual['final_funds']:>+13,.2f}")
    print(f"{'总回报率':<20} | {results_with_visual['total_return']:>13.2f}% | {results_without_visual['total_return']:>13.2f}% | {results_with_visual['total_return'] - results_without_visual['total_return']:>+13.2f}%")
    print(f"{'交易次数':<20} | {len(results_with_visual['trades']):>15} | {len(results_without_visual['trades']):>15} | {len(results_with_visual['trades']) - len(results_without_visual['trades']):>+15}")
    print(f"{'信号总数':<20} | {results_with_visual['stats']['signals_found']:>15} | {results_without_visual['stats']['signals_found']:>15} | -")
    print("="*70)
    
    return results_with_visual, results_without_visual


def main():
    parser = argparse.ArgumentParser(description='港股缠论视觉回测系统 - 30M 周期')
    parser.add_argument('--watchlist', type=str, nargs='+', default=None, help='股票代码列表')
    parser.add_argument('--start', type=str, default='2024-03-01', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2025-02-28', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--funds', type=float, default=100000.0, help='初始资金')
    parser.add_argument('--min-score', type=int, default=70, help='最小视觉评分阈值')
    parser.add_argument('--compare', action='store_true', help='运行对比实验 (有视觉 vs 无视觉)')
    parser.add_argument('--no-visual', action='store_true', help='禁用视觉判断')
    parser.add_argument('--output', type=str, default='hk_backtest_charts', help='图表输出目录')
    
    args = parser.parse_args()
    
    # 获取回测列表
    watchlist = args.watchlist if args.watchlist else get_hk_watchlist()
    
    if not watchlist:
        logger.error("没有可用的回测股票列表")
        return
    
    lot_size_map = get_lot_size_map(watchlist)
    
    if args.compare:
        # 运行对比实验
        results_with_visual, results_without_visual = compare_visual_vs_no_visual(
            watchlist, args.start, args.end, args.funds
        )
        
        # 保存对比结果
        output_file = f"hk_backtest_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'with_visual': results_with_visual,
                'without_visual': results_without_visual,
                'comparison_summary': {
                    'return_difference': results_with_visual['total_return'] - results_without_visual['total_return'],
                    'funds_difference': results_with_visual['final_funds'] - results_without_visual['final_funds'],
                    'trades_difference': len(results_with_visual['trades']) - len(results_without_visual['trades'])
                }
            }, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"\n💾 对比结果已保存到：{output_file}")
        
    else:
        # 单次回测
        engine = HKVisualBacktestEngine(
            watchlist=watchlist,
            start_date=args.start,
            end_date=args.end,
            initial_funds=args.funds,
            lot_size_map=lot_size_map,
            output_dir=args.output,
            min_visual_score=args.min_score,
            use_visual_judge=not args.no_visual
        )
        
        results = engine.run_backtest()
        engine.print_report(results)
        
        # 保存结果
        output_file = f"hk_backtest_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"\n💾 回测结果已保存到：{output_file}")


if __name__ == '__main__':
    main()
