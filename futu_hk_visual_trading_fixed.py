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
    
    def generate_charts(self, code: str, chan_30m) -> List[str]:
        """
        生成技术图表
        
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
            # 生成30分钟图
            plot_30m = CPlotDriver(
                chan_30m,
                plot_config={
                    "plot_kline": True,
                    "plot_bi": True,
                    "plot_zs": True,
                    "plot_bsp": True
                },
                plot_para={
                    "figure": {"w": 14, "h": 8}
                }
            )
            chart_30m_path = f"{self.charts_dir}/{safe_code}_{timestamp}_30M.png"
            plt.savefig(chart_30m_path, bbox_inches='tight', dpi=100)
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
                    "plot_bsp": True
                },
                plot_para={
                    "figure": {"w": 14, "h": 8}
                }
            )
            chart_5m_path = f"{self.charts_dir}/{safe_code}_{timestamp}_5M.png"
            plt.savefig(chart_5m_path, bbox_inches='tight', dpi=100)
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
            if not chan_result or not chan_result.get('is_buy_signal'):
                logger.debug(f"{code} 无买入信号，跳过")
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
                
                logger.info(f"{code} 视觉评分: {score}, 建议: {action}")
                
                # 检查评分阈值
                if score < self.min_visual_score or action != 'BUY':
                    logger.info(f"{code} 评分({score})低于阈值({self.min_visual_score})或建议不买入，跳过")
                    continue
                
                # 计算购买数量
                buy_quantity = self.calculate_position_size(current_price, available_funds)
                if buy_quantity <= 0:
                    logger.warning(f"{code} 计算出的购买数量无效: {buy_quantity}")
                    continue
                
                logger.info(f"{code} 满足交易条件 - 价格: {current_price}, 数量: {buy_quantity}, 评分: {score}")
                
                # 执行交易
                if self.execute_trade(code, 'BUY', buy_quantity, current_price):
                    logger.info(f"成功下单买入 {code}")
                else:
                    logger.error(f"下单失败 {code}")
                    
            except Exception as e:
                logger.error(f"视觉评分异常 {code}: {e}")
                continue
        
        logger.info("扫描交易完成")

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
