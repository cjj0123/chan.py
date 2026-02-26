#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货港股视觉交易系统 - 修复版
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from futu import *
from visual_judge import VisualJudge

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
                 hk_watchlist_group: str = "港股",
                 min_visual_score: int = 70,
                 max_position_ratio: float = 0.2,
                 dry_run: bool = True):
        """
        初始化港股视觉交易系统
        
        Args:
            hk_watchlist_group: 自选股组名
            min_visual_score: 最小视觉评分阈值
            max_position_ratio: 单票最大仓位比例
            dry_run: 是否为模拟盘模式
        """
        self.hk_watchlist_group = hk_watchlist_group
        self.min_visual_score = min_visual_score
        self.max_position_ratio = max_position_ratio
        self.dry_run = dry_run
        
        # 创建图表目录
        self.charts_dir = "charts"
        os.makedirs(self.charts_dir, exist_ok=True)
        
        # 初始化富途连接
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
        
        # 交易环境
        self.trd_env = TrdEnv.SIMULATE if dry_run else TrdEnv.REAL
        
        # 缠论配置
        self.chan_config = CChanConfig({
            "bi_strict": False,
            "one_bi_zs": True,
            "bs_type": '1,1p,2,2s,3a,3b'
        })
        
        # 视觉评分器
        self.visual_judge = VisualJudge(use_mock=False)
        
        logger.info(f"初始化完成 - 模拟盘: {dry_run}, 评分阈值: {min_visual_score}")
    
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
            包含价格、市值等信息的字典
        """
        try:
            ret, data = self.quote_ctx.get_market_snapshot([code])
            if ret == RET_OK and not data.empty:
                stock_info = data.iloc[0].to_dict()
                return {
                    'current_price': stock_info['last_price'],
                    'market_val': stock_info.get('market_val', 0),
                    'turnover_rate': stock_info.get('turnover_rate', 0),
                    'volume': stock_info.get('volume', 0)
                }
            else:
                logger.warning(f"无法获取 {code} 的市场快照")
                return {}
        except Exception as e:
            logger.error(f"获取股票信息异常 {code}: {e}")
            return {}
    
    def calculate_position_size(self, current_price: float, available_funds: float) -> int:
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
        min_lot_size = 100  # 默认100股一手
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
        from pandas.tseries.holiday import AbstractHolidayCalendar, Holiday
        from pandas.tseries.offsets import CustomBusinessDay
        
        # 港股节假日（简化版，主要节假日）
        class HKHolidays(AbstractHolidayCalendar):
            rules = [
                Holiday('New Year', month=1, day=1),
                Holiday('Lunar New Year 1', month=2, day=10),  # 春节（示例日期）
                Holiday('Lunar New Year 2', month=2, day=11),
                Holiday('Lunar New Year 3', month=2, day=12),
                Holiday('Good Friday', month=3, day=29),  # 耶稣受难节（示例）
                Holiday('Easter Monday', month=4, day=1),  # 复活节星期一
                Holiday('Labour Day', month=5, day=1),
                Holiday('MidAutumn', month=9, day=17),  # 中秋节（示例）
                Holiday('National Day', month=10, day=1),
                Holiday('Christmas', month=12, day=25),
                Holiday('Boxing Day', month=12, day=26),
            ]
        
        total_hours = 0.0
        current = start_time
        
        while current < end_time:
            # 检查是否是工作日（周一到周五）
            if current.weekday() >= 5:  # 周六或周日
                current += timedelta(days=1)
                current = current.replace(hour=0, minute=0, second=0)
                continue
            
            # 获取当天的交易时段
            morning_start = current.replace(hour=9, minute=30, second=0, microsecond=0)
            morning_end = current.replace(hour=12, minute=0, second=0, microsecond=0)
            afternoon_start = current.replace(hour=13, minute=0, second=0, microsecond=0)
            afternoon_end = current.replace(hour=16, minute=0, second=0, microsecond=0)
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
            # 获取30分钟K线数据
            end_time = datetime.now()
            start_time = end_time - timedelta(days=30)
            
            chan_30m = CChan(
                code=code,
                begin_time=start_time.strftime("%Y-%m-%d"),
                end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                data_src=DATA_SRC.FUTU,
                lv_list=[KL_TYPE.K_30M],
                config=self.chan_config
            )
            
            # 获取最新的买卖点
            latest_bsps = chan_30m.get_latest_bsp(number=1)
            if not latest_bsps:
                logger.debug(f"{code} 未发现买卖点")
                return None
            
            bsp = latest_bsps[0]
            bsp_type = bsp.type2str()
            is_buy = bsp.is_buy
            price = bsp.klu.close
            
            # ====== 时间过滤：只交易最近4个交易小时内的信号 ======
            # 将CTime转换为datetime
            bsp_ctime = bsp.klu.time
            bsp_time = datetime(bsp_ctime.year, bsp_ctime.month, bsp_ctime.day, 
                               bsp_ctime.hour, bsp_ctime.minute, bsp_ctime.second)
            
            now = datetime.now()
            trading_hours = self.calculate_trading_hours(bsp_time, now)
            
            if trading_hours > 4:
                logger.info(f"{code} {bsp_type} 信号产生于 {bsp_time.strftime('%Y-%m-%d %H:%M')}，"
                           f"距今 {trading_hours:.1f} 个交易小时，超过4小时窗口，跳过")
                return None
            
            logger.info(f"{code} {bsp_type} 信号在4小时窗口内（{trading_hours:.1f}个交易小时前），继续分析")
            
            result = {
                'code': code,
                'bsp_type': bsp_type,
                'is_buy_signal': is_buy,
                'bsp_price': price,
                'bsp_datetime': bsp.klu.time,
                'chan_analysis': {
                    'chan_30m': chan_30m
                }
            }
            
            logger.info(f"{code} 缠论分析: {bsp_type} 信号, 价格: {price}")
            return result
            
        except Exception as e:
            logger.error(f"CChan分析异常 {code}: {e}")
            return None
    
    def _customize_macd_colors(self, plot_driver):
        """
        自定义MACD颜色 - 使用鲜艳的红绿色提高AI识别度
        """
        try:
            # 遍历所有axes，找到MACD副图
            for ax in plot_driver.figure.axes:
                # 检查是否是MACD图（通过是否有bar来判断）
                for container in ax.containers:
                    if hasattr(container, 'get_label') and 'macd' in str(container.get_label()).lower():
                        # 设置MACD柱状图颜色
                        for i, bar in enumerate(container):
                            if bar.get_height() >= 0:
                                bar.set_color('#FF0000')  # 鲜艳红色（正值）
                            else:
                                bar.set_color('#00FF00')  # 鲜艳绿色（负值）
                            bar.set_alpha(0.9)  # 高透明度
                
                # 修改DIF和DEA线颜色
                for line in ax.lines:
                    label = str(line.get_label()).lower()
                    if 'dif' in label:
                        line.set_color('#FFA500')  # 橙色DIF线
                        line.set_linewidth(1.5)
                    elif 'dea' in label:
                        line.set_color('#0000FF')  # 蓝色DEA线
                        line.set_linewidth(1.5)
        except Exception as e:
            logger.warning(f"自定义MACD颜色失败: {e}")
    
    def generate_charts(self, code: str, chan_30m) -> List[str]:
        """
        生成技术图表（AI视觉优化版）
        
        优化点：
        1. 副图加入MACD
        2. MACD颜色鲜艳（红绿柱高对比度）
        3. 画笔线宽加粗到2.0
        4. 中枢半透明填充(alpha=0.3)
        5. 淡化网格线
        
        Args:
            code: 股票代码
            chan_30m: 30分钟缠论对象
            
        Returns:
            图表文件路径列表
        """
        chart_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_code = code.replace('.', '_').replace('-', '_')
        
        try:
            # 生成30分钟图（AI视觉优化配置）
            plot_30m = CPlotDriver(
                chan_30m,
                plot_config={
                    "plot_kline": True,
                    "plot_bi": True,
                    "plot_zs": True,
                    "plot_bsp": True,
                    "plot_macd": True  # 新增：副图显示MACD
                },
                plot_para={
                    "figure": {
                        "w": 16,  # 增加宽度
                        "h": 12,  # 增加高度容纳MACD副图
                        "macd_h": 0.25,  # MACD副图占25%高度
                        "grid": None  # 去掉网格线
                    },
                    "bi": {
                        "color": "#FFD700",  # 金黄色画笔，更醒目
                        "linewidth": 2.0,  # 笔线加粗
                        "show_num": False
                    },
                    "zs": {
                        "color": "#FF8C00",  # 深橙色中枢边框
                        "linewidth": 2,
                        "facecolor": "#FFA500",  # 橙色填充
                        "alpha": 0.3  # 半透明，不遮挡K线
                    },
                    "macd": {
                        "width": 0.6  # MACD柱状图宽度
                    }
                }
            )
            
            # 自定义MACD颜色（覆盖默认颜色）
            self._customize_macd_colors(plot_30m)
            
            chart_30m_path = f"{self.charts_dir}/{safe_code}_{timestamp}_30M.png"
            plt.savefig(chart_30m_path, bbox_inches='tight', dpi=120, facecolor='white')
            plt.close('all')
            chart_paths.append(chart_30m_path)
            
            # 获取5分钟数据并生成图表
            end_time = datetime.now()
            start_time = end_time - timedelta(days=7)  # 5分钟图看一周
            
            chan_5m = CChan(
                code=code,
                begin_time=start_time.strftime("%Y-%m-%d"),
                end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                data_src=DATA_SRC.FUTU,
                lv_list=[KL_TYPE.K_5M],
                config=self.chan_config
            )
            
            plot_5m = CPlotDriver(
                chan_5m,
                plot_config={
                    "plot_kline": True,
                    "plot_bi": True,
                    "plot_zs": True,
                    "plot_bsp": True,
                    "plot_macd": True  # 新增：副图显示MACD
                },
                plot_para={
                    "figure": {
                        "w": 16,
                        "h": 12,
                        "macd_h": 0.25,
                        "grid": None  # 去掉网格线
                    },
                    "bi": {
                        "color": "#FFD700",  # 金黄色画笔
                        "linewidth": 2.0,  # 笔线加粗
                        "show_num": False
                    },
                    "zs": {
                        "color": "#FF8C00",  # 深橙色中枢边框
                        "linewidth": 2,
                        "facecolor": "#FFA500",  # 橙色填充
                        "alpha": 0.3  # 半透明
                    },
                    "macd": {
                        "width": 0.6
                    }
                }
            )
            
            # 自定义MACD颜色
            self._customize_macd_colors(plot_5m)
            
            chart_5m_path = f"{self.charts_dir}/{safe_code}_{timestamp}_5M.png"
            plt.savefig(chart_5m_path, bbox_inches='tight', dpi=120, facecolor='white')
            plt.close('all')
            chart_paths.append(chart_5m_path)
            
            logger.info(f"生成图表: {chart_paths}")
            return chart_paths
            
        except Exception as e:
            logger.error(f"生成图表异常 {code}: {e}")
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
            logger.warning(f"无效数量 {quantity}，跳过交易 {code}")
            return False
        
        try:
            if action.upper() == 'BUY':
                # 买单使用略高价格确保成交
                order_price = price * 1.01
                ret, data = self.trd_ctx.place_order(
                    price=order_price,
                    qty=quantity,
                    code=code,
                    trd_side=TrdSide.BUY,
                    order_type=OrderType.ENHANCE_LIMIT,
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
                # 卖单使用略低价格确保成交
                order_price = price * 0.99
                ret, data = self.trd_ctx.place_order(
                    price=order_price,
                    qty=quantity,
                    code=code,
                    trd_side=TrdSide.SELL,
                    order_type=OrderType.ENHANCE_LIMIT,
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
        获取可用资金
        
        Returns:
            可用资金金额
        """
        # 模拟盘模式下使用固定初始资金
        if self.dry_run:
            initial_capital = 1000000.0  # 100万港币模拟资金
            logger.info(f"模拟盘初始资金: {initial_capital}")
            return initial_capital
        
        # 实盘模式查询真实资金
        try:
            ret, data = self.trd_ctx.accinfo_query(trd_env=self.trd_env)
            if ret == RET_OK and not data.empty:
                available_funds = data.iloc[0]['avl_withdrawal_cash']
                logger.info(f"可用资金: {available_funds}")
                return available_funds
            else:
                logger.error(f"获取账户信息失败: {data}")
                return 0.0
        except Exception as e:
            logger.error(f"获取资金信息异常: {e}")
            return 0.0
    
    def scan_and_trade(self):
        """扫描股票并执行交易"""
        logger.info("开始扫描交易...")
        
        # 获取自选股
        watchlist_codes = self.get_watchlist_codes()
        if not watchlist_codes:
            logger.warning("没有获取到自选股，退出扫描")
            return
        
        # 获取可用资金
        available_funds = self.get_available_funds()
        if available_funds <= 0:
            logger.error("可用资金不足，退出扫描")
            return
        
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
            
            # 记录信号类型（买入或卖出）
            bsp_type = chan_result.get('bsp_type', '未知')
            is_buy = chan_result.get('is_buy_signal', False)
            logger.info(f"{code} 信号类型: {bsp_type}, 是否买入: {is_buy}")
            
            # ====== 持仓过滤逻辑 ======
            # 查询当前持仓数量
            position_qty = self.get_position_quantity(code)
            
            # 已持仓股票跳过买点
            if is_buy and position_qty > 0:
                logger.info(f"{code} 已有持仓({position_qty}股)，跳过买入")
                continue
            
            # 未持仓股票跳过卖点
            if not is_buy and position_qty <= 0:
                logger.info(f"{code} 无持仓，跳过卖出分析")
                continue
            
            # 生成图表（需要交易的股票才生成图表进行视觉评分）
            chart_paths = self.generate_charts(code, chan_result['chan_analysis']['chan_30m'])
            if not chart_paths:
                logger.warning(f"{code} 图表生成失败，跳过")
                continue
            
            # 视觉评分（无论买入卖出都进行）
            try:
                visual_result = self.visual_judge.evaluate(chart_paths)
                score = visual_result.get('score', 0)
                action = visual_result.get('action', 'WAIT')
                analysis = visual_result.get('analysis', '')
                
                logger.info(f"{code} 视觉评分: {score}/100, 建议: {action}, 分析: {analysis}")
                
                # 根据信号类型执行不同操作
                if is_buy:
                    # 买入信号处理
                    if score < self.min_visual_score or action != 'BUY':
                        logger.info(f"{code} 买入信号但评分({score})低于阈值({self.min_visual_score})或建议不买入，跳过")
                        continue
                    
                    # 计算购买数量
                    buy_quantity = self.calculate_position_size(current_price, available_funds)
                    if buy_quantity <= 0:
                        logger.warning(f"{code} 计算出的购买数量无效: {buy_quantity}")
                        continue
                    
                    logger.info(f"{code} 满足买入条件 - 价格: {current_price}, 数量: {buy_quantity}, 评分: {score}")
                    
                    # 执行买入交易
                    if self.execute_trade(code, 'BUY', buy_quantity, current_price):
                        logger.info(f"✅ 成功下单买入 {code}")
                    else:
                        logger.error(f"❌ 买入下单失败 {code}")
                else:
                    # 卖出信号处理
                    # 卖出阈值：视觉评分 <= 30 分（3分以下）说明顶部特征明显，建议卖出
                    SELL_SCORE_THRESHOLD = 30
                    
                    if score <= SELL_SCORE_THRESHOLD:
                        logger.info(f"{code} 卖出信号 ({bsp_type}) 且视觉评分仅 {score}/100，顶部特征明显，强烈建议卖出！")
                        
                        # 获取当前持仓数量
                        sell_quantity = self.get_position_quantity(code)
                        if sell_quantity <= 0:
                            logger.warning(f"{code} 无持仓，无法卖出")
                            continue
                        
                        logger.info(f"{code} 满足卖出条件 - 价格: {current_price}, 数量: {sell_quantity}, 评分: {score}")
                        
                        # 执行卖出交易
                        if self.execute_trade(code, 'SELL', sell_quantity, current_price):
                            logger.info(f"✅ 成功下单卖出 {code}")
                        else:
                            logger.error(f"❌ 卖出下单失败 {code}")
                    else:
                        logger.info(f"{code} 卖出信号 ({bsp_type}) 但视觉评分 {score}/100 高于阈值 {SELL_SCORE_THRESHOLD}，趋势仍健康，暂不卖出")
                    
            except Exception as e:
                logger.error(f"视觉评分异常 {code}: {e}")
                continue
        
        logger.info("扫描交易完成")

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
        trader = FutuHKVisualTrading(
            hk_watchlist_group="港股",
            min_visual_score=70,
            max_position_ratio=0.2,
            dry_run=True  # 设为True为模拟盘，False为实盘
        )
        
        # 持续运行
        while True:
            trader.scan_and_trade()
            logger.info("等待下一轮扫描...")
            time.sleep(60 * 10)  # 每10分钟扫描一次
            
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
