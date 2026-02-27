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

# 自动加载 API Key
try:
    from load_api_key import load_api_keys
    if load_api_keys():
        print("✅ API Key 已从 memory/api_keys.md 加载")
    else:
        # 备用方案：直接设置
        import os
        os.environ["GOOGLE_API_KEY"] = "AIzaSyCyOShkz9hhPPLxYrI6Oc4eHq_I6muZF0Q"
        print("✅ API Key 已使用备用配置")
except Exception as e:
    import os
    os.environ["GOOGLE_API_KEY"] = "AIzaSyCyOShkz9hhPPLxYrI6Oc4eHq_I6muZF0Q"
    print(f"⚠️ API Key 加载异常，使用备用配置")

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
        
        # 缠论配置 - 启用MACD计算
        self.chan_config = CChanConfig({
            "bi_strict": False,
            "one_bi_zs": True,
            "bs_type": '1,1p,2,2s,3a,3b',
            "macd": {"fast": 12, "slow": 26, "signal": 9}  # 启用MACD计算
        })
        
        # 视觉评分器
        self.visual_judge = VisualJudge(use_mock=False)
        
        # 检查 memo CLI 是否可用（用于发送 Apple Notes 备忘录）
        self.memo_available = shutil.which("memo") is not None
        if not self.memo_available:
            logger.warning("memo CLI 未安装，Apple Notes 通知功能不可用")
        
        logger.info(f"初始化完成 - 模拟盘: {dry_run}, 评分阈值: {min_visual_score}")
    
    def send_scan_result_to_notes(self, scan_summary):
        """
        将扫描结果发送到 Apple Notes 备忘录（仅在有信号时发送，嵌入图表图片）
        """
        try:
            # 如果没有有效信号，跳过发送
            if scan_summary.get('valid_signals', 0) == 0:
                logger.info("📭 无有效信号，跳过备忘录通知")
                return
            
            now = datetime.now()
            title = "🎯 港股交易信号 - " + now.strftime('%Y-%m-%d %H:%M')
            
            # 构建文本内容
            text_lines = [
                "🎯 港股缠论视觉交易信号",
                "═══════════════════════════════",
                "",
                "⏰ 扫描时间：" + now.strftime('%Y-%m-%d %H:%M:%S'),
                "✅ 有效信号：" + str(scan_summary.get('valid_signals', 0)) + "个",
                ""
            ]
            
            # 收集所有图表路径
            all_chart_paths = []
            
            # 卖出信号
            sell_signals = scan_summary.get('sell_signals', [])
            if sell_signals:
                text_lines.append("【卖出信号】" + str(len(sell_signals)) + "个")
                for i, signal in enumerate(sell_signals, 1):
                    code = signal.get('code', 'N/A')
                    bsp_type = signal.get('bsp_type', '未知')
                    score = signal.get('score', 0)
                    qty = signal.get('position_qty', 0)
                    price = signal.get('current_price', 0)
                    chart_paths = signal.get('chart_paths', [])
                    
                    text_lines.append(str(i) + ". " + str(code) + " - " + str(bsp_type) + " (评分：" + str(score) + ")")
                    text_lines.append("    持仓：" + str(int(qty)) + "股 @ " + "{:.2f}".format(price))
                    
                    if chart_paths:
                        all_chart_paths.extend(chart_paths)
                    text_lines.append("")
            
            # 买入信号
            buy_signals = scan_summary.get('buy_signals', [])
            if buy_signals:
                text_lines.append("【买入信号】" + str(len(buy_signals)) + "个")
                for i, signal in enumerate(buy_signals, 1):
                    code = signal.get('code', 'N/A')
                    bsp_type = signal.get('bsp_type', '未知')
                    score = signal.get('score', 0)
                    qty = signal.get('buy_quantity', 0)
                    price = signal.get('current_price', 0)
                    cost = signal.get('estimated_cost', qty * price)
                    chart_paths = signal.get('chart_paths', [])
                    
                    text_lines.append(str(i) + ". " + str(code) + " - " + str(bsp_type) + " (评分：" + str(score) + ")")
                    text_lines.append("    买入：" + str(int(qty)) + "股 @ " + "{:.2f}".format(price) + " (约 " + "{:,.0f}".format(cost) + " HKD)")
                    
                    if chart_paths:
                        all_chart_paths.extend(chart_paths)
                    text_lines.append("")
            
            # 资金变动
            initial = scan_summary.get('initial_funds', 0)
            final = scan_summary.get('final_funds', 0)
            text_lines.append("═══════════════════════════════")
            text_lines.append("💰 资金：" + "{:,.0f}".format(initial) + " → " + "{:,.0f}".format(final) + " HKD")
            
            text_content = "\n".join(text_lines)
            
            # AppleScript: 创建备忘录并插入图片
            escaped_title = title.replace('"', '\\"')
            escaped_text = text_content.replace('"', '\\"').replace("\n", "\\n")
            
            # 1. 创建文本备忘录
            script1 = 'tell application "Notes"\n    make new note with properties {name:"' + escaped_title + '", body:"' + escaped_text + '"}\nend tell'
            
            result = subprocess.run(["osascript", "-e", script1], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                logger.info("✅ 备忘录已创建：" + title)
                
                # 2. 插入图表图片
                if all_chart_paths:
                    for chart_path in all_chart_paths:
                        if os.path.exists(chart_path):
                            abs_path = os.path.abspath(chart_path)
                            script2 = 'tell application "Notes"\n    tell note "' + escaped_title + '"\n        insert image from file "' + abs_path + '"\n    end tell\nend tell'
                            subprocess.run(["osascript", "-e", script2], capture_output=True, timeout=10)
                    
                    logger.info("📊 已插入 " + str(len(all_chart_paths)) + " 张图表")
            else:
                logger.error("❌ 创建备忘录失败：" + result.stderr)
            
        except Exception as e:
            logger.error("❌ 发送备忘录异常：" + str(e))
    
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
                    'market_val': stock_info.get('market_val', 0),
                    'turnover_rate': stock_info.get('turnover_rate', 0),
                    'volume': stock_info.get('volume', 0),
                    'lot_size': int(stock_info.get('lot_size', 100))  # 每手股数
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
            is_buy = bsp.is_buy  # 信任 CChan 的 is_buy 判断
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
        自定义MACD颜色 - AI视觉优化版
        红柱: 上涨动能 (鲜红 #FF0000)
        绿柱: 下跌动能 (鲜绿 #00FF00)
        DIF线: 快线 (白色 #FFFFFF)
        DEA线: 慢线 (黄色 #FFFF00)
        """
        try:
            # 遍历所有axes，找到MACD副图
            for ax in plot_driver.figure.axes:
                # 设置MACD柱状图颜色
                for container in ax.containers:
                    if hasattr(container, '__iter__'):  # bar容器
                        for bar in container:
                            if hasattr(bar, 'get_height'):
                                if bar.get_height() >= 0:
                                    bar.set_color('#FF0000')  # 鲜艳红色（上涨）
                                    bar.set_edgecolor('#8B0000')  # 深红边框
                                else:
                                    bar.set_color('#00FF00')  # 鲜艳绿色（下跌）
                                    bar.set_edgecolor('#006400')  # 深绿边框
                                bar.set_alpha(0.85)  # 高透明度
                
                # 修改DIF和DEA线颜色
                for line in ax.lines:
                    label = str(line.get_label()).lower() if line.get_label() else ''
                    if 'dif' in label or 'DIF' in str(line.get_label()):
                        line.set_color('#FFFFFF')  # 白色DIF线（快线）
                        line.set_linewidth(2.0)
                        line.set_alpha(0.9)
                    elif 'dea' in label or 'DEA' in str(line.get_label()):
                        line.set_color('#FFFF00')  # 黄色DEA线（慢线）
                        line.set_linewidth(2.0)
                        line.set_alpha(0.9)
                    
                # 设置MACD图背景色为深色，增强对比度
                ax.set_facecolor('#1a1a1a')  # 深灰背景
                ax.tick_params(colors='white')  # 白色刻度
                ax.xaxis.label.set_color('white')
                ax.yaxis.label.set_color('white')
                
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
                        "color": "#FFFF00",  # 黄色 (Yellow) - 笔
                        "show_num": False
                    },
                    "zs": {
                        "color": "#4169E1",  # 皇家蓝 (Royal Blue) - 中枢边框
                        "linewidth": 2
                    },
                    "bsp": {
                        "fontsize": 12,
                        "buy_color": "red",
                        "sell_color": "green"
                    },
                    "macd": {
                        "width": 0.6
                    }
                }
            )
            
            # 自定义MACD颜色（覆盖默认颜色）
            self._customize_macd_colors(plot_30m)
            
            chart_30m_path = f"{self.charts_dir}/{safe_code}_{timestamp}_30M.png"
            plt.savefig(chart_30m_path, bbox_inches='tight', dpi=120, facecolor='white')
            plt.close('all')
            chart_paths.append(chart_30m_path)
            
            # 获取5分钟数据并生成图表（用于Gemini辅助判断背驰）
            end_time = datetime.now()
            start_time = end_time - timedelta(days=7)  # 7天数据
            
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
                    "plot_macd": True
                },
                plot_para={
                    "figure": {
                        "w": 16,
                        "h": 12,
                        "macd_h": 0.25,
                        "grid": None
                    },
                    "bi": {
                        "color": "#FFFF00",
                        "show_num": False
                    },
                    "zs": {
                        "color": "#4169E1",
                        "linewidth": 2
                    },
                    "bsp": {
                        "fontsize": 12,
                        "buy_color": "red",
                        "sell_color": "green"
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
        
    def scan_and_trade(self):
        """
        批量扫描并执行交易
        逻辑：收集所有信号 → 卖点优先 → 同类型按评分排序执行
        """
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
        
        # ========== 第一阶段：收集所有有效信号 ==========
        all_signals = []
        
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
            bsp_type_display = f"{'b' if is_buy else 's'}{bsp_type}"
            logger.info(f"{code} 信号类型: {bsp_type_display}, 是否买入: {is_buy}")
            
            # 持仓过滤
            position_qty = self.get_position_quantity(code)
            
            if is_buy and position_qty > 0:
                logger.info(f"{code} 已有持仓({position_qty}股)，跳过买入")
                continue
            
            if not is_buy and position_qty <= 0:
                logger.info(f"{code} 无持仓，跳过卖出")
                continue
            
            # 生成图表
            chart_paths = self.generate_charts(code, chan_result['chan_analysis']['chan_30m'])
            if not chart_paths:
                logger.warning(f"{code} 图表生成失败，跳过")
                continue
            
            # 视觉评分
            try:
                visual_result = self.visual_judge.evaluate(chart_paths)
                score = visual_result.get('score', 0)
                action = visual_result.get('action', 'WAIT')
                analysis = visual_result.get('analysis', '')
                
                logger.info(f"{code} 视觉评分: {score}/100, 建议: {action}")
                
                # 只收集达到阈值的信号
                if score >= self.min_visual_score:
                    # 获取每手股数
                    lot_size = stock_info.get('lot_size', 100)
                    signal_data = {
                        'code': code,
                        'is_buy': is_buy,
                        'bsp_type': bsp_type,
                        'score': score,
                        'current_price': current_price,
                        'position_qty': position_qty,
                        'lot_size': lot_size,
                        'chart_paths': chart_paths,
                        'visual_result': visual_result
                    }
                    all_signals.append(signal_data)
                    logger.info(f"✅ {code} 信号收集成功 (评分: {score})")
                else:
                    logger.info(f"{code} 评分({score})低于阈值({self.min_visual_score})，不收集")
                    
            except Exception as e:
                logger.error(f"视觉评分异常 {code}: {e}")
                continue
        
        logger.info(f"共收集到 {len(all_signals)} 个有效信号")
        
        # ========== 第二阶段：分离并排序信号 ==========
        # 即使没有信号也继续执行，让备忘录函数处理
        sell_signals = [s for s in all_signals if not s['is_buy']]
        buy_signals = [s for s in all_signals if s['is_buy']]
        
        # 按评分从高到低排序
        sell_signals.sort(key=lambda x: x['score'], reverse=True)
        buy_signals.sort(key=lambda x: x['score'], reverse=True)
        
        logger.info(f"卖出信号: {len(sell_signals)}个, 买入信号: {len(buy_signals)}个")
        
        # ========== 第三阶段：先执行卖点（优先）==========
        if sell_signals:
            logger.info(f"\n>>> 开始执行卖出操作（共{len(sell_signals)}个）")
            for i, signal in enumerate(sell_signals, 1):
                code = signal['code']
                score = signal['score']
                qty = signal['position_qty']
                price = signal['current_price']
                bsp_type = signal['bsp_type']
                
                logger.info(f"\n[{i}/{len(sell_signals)}] 卖出 {code} - {bsp_type} - 评分: {score}")
                
                if self.execute_trade(code, 'SELL', qty, price):
                    # 卖出成功，释放资金
                    released_funds = price * qty
                    available_funds += released_funds
                    logger.info(f"✅ 卖出成功 {code}, 释放资金: {released_funds:.2f}, 当前可用: {available_funds:.2f}")
                else:
                    logger.error(f"❌ 卖出失败 {code}")
        
        # ========== 第四阶段：再执行买点 ==========
        if buy_signals:
            logger.info(f"\n>>> 开始执行买入操作（共{len(buy_signals)}个）")
            for i, signal in enumerate(buy_signals, 1):
                code = signal['code']
                score = signal['score']
                price = signal['current_price']
                bsp_type = signal['bsp_type']
                
                # 计算可买入数量
                buy_quantity = self.calculate_position_size(price, available_funds, signal.get('lot_size', 100))
                
                if buy_quantity <= 0:
                    logger.warning(f"[{i}/{len(buy_signals)}] {code} 资金不足，跳过 (可用: {available_funds:.2f})")
                    continue
                
                required_funds = price * buy_quantity
                
                logger.info(f"\n[{i}/{len(buy_signals)}] 买入 {code} - {bsp_type} - 评分: {score}")
                logger.info(f"   计划买入: {buy_quantity}股, 预计花费: {required_funds:.2f}")
                
                if self.execute_trade(code, 'BUY', buy_quantity, price):
                    # 买入成功，扣除资金
                    available_funds -= required_funds
                    logger.info(f"✅ 买入成功 {code}, 剩余资金: {available_funds:.2f}")
                else:
                    logger.error(f"❌ 买入失败 {code}")
        
        logger.info(f"\n扫描交易完成，最终可用资金: {available_funds:.2f}")
        
        # ========== 第五阶段：发送扫描结果到备忘录 ==========
        try:
            scan_summary = {
                'total_stocks': len(watchlist_codes),
                'valid_signals': len(all_signals),
                'sell_signals': sell_signals,
                'buy_signals': buy_signals,
                'executed_sells': [],  # 简化处理，实际可记录详细交易信息
                'executed_buys': [],
                'filtered_signals': [],
                'initial_funds': available_funds_at_start,
                'final_funds': available_funds
            }
            self.send_scan_result_to_notes(scan_summary)
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
