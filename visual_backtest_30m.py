#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视觉辅助回测系统 - 30M 周期
- 只使用 30M K 线
- 买点买入，卖点卖出
- 买入时使用 Gemini API 视觉评分 >= 70 分才买入
"""

import os
import sys
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Common.CEnum import KL_TYPE
from Chan import CChan
from ChanConfig import CChanConfig
from DataAPI.MockStockAPI import register_kline_data, clear_kline_data
from backtester import BacktestKLineUnit, BacktestDataLoader
from visual_judge import VisualJudge

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('visual_backtest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class VisualBacktestBroker:
    """模拟交易账户和经纪商"""
    
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
    
    def calculate_position_size(self, code: str, current_price: float, max_investment_ratio: float = 0.2) -> int:
        """计算应买入的股数"""
        lot_size = self.lot_size_map.get(code, 100)
        max_amount = self.available_funds * max_investment_ratio
        quantity = int(max_amount / current_price / lot_size) * lot_size
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


class VisualBacktestEngine:
    """视觉辅助回测引擎（使用 Gemini API 评分）"""
    
    def __init__(self, code: str, start_date: str, end_date: str, 
                 initial_funds: float = 100000.0,
                 lot_size_map: Dict[str, int] = None,
                 output_dir: str = "visual_backtest_charts",
                 min_visual_score: int = 70):
        self.code = code
        self.start_date = start_date
        self.end_date = end_date
        self.initial_funds = initial_funds
        self.lot_size_map = lot_size_map or {}
        self.output_dir = output_dir
        self.min_visual_score = min_visual_score
        
        os.makedirs(output_dir, exist_ok=True)
        
        self.loader = BacktestDataLoader()
        self.broker = VisualBacktestBroker(initial_funds, self.lot_size_map)
        self.visual_judge = VisualJudge(use_mock=False)  # 使用真实 Gemini API
        
        # 回测状态
        self.current_position = 0  # 0=空仓，1=持仓
        self.entry_price = 0
        self.entry_time = None
        self.visual_scores: List[Dict] = []  # 记录每次视觉评分
        
        # 加载数据
        self.klines_30m = None
        self.klines_day = None
    
    def load_data(self) -> bool:
        """加载 K 线数据"""
        logger.info(f"📥 加载 {self.code} 数据...")
        
        self.klines_30m = self.loader.load_kline_data(self.code, "30M", self.start_date, self.end_date)
        self.klines_day = self.loader.load_kline_data(self.code, "DAY", self.start_date, self.end_date)
        
        if not self.klines_30m:
            logger.error("无法加载 30M 数据")
            return False
        
        logger.info(f"✅ 加载完成：30M={len(self.klines_30m)}, DAY={len(self.klines_day) if self.klines_day else 0}")
        return True
    
    def analyze_kline(self, klines: List[BacktestKLineUnit]) -> Optional[CChan]:
        """分析 K 线数据，返回 CChan 实例"""
        if not klines:
            return None
        
        # 注册数据
        clear_kline_data()
        register_kline_data(self.code, KL_TYPE.K_30M, klines)
        
        # 创建缠论配置
        chan_config = CChanConfig(
            trigger_step=False,
            trigger_step_print=False,
            divergence_rate=0.8,
            mean_strategy=False,
            max_bi_num=1000,
        )
        
        # 创建 CChan 实例
        chan = CChan(
            code=self.code,
            data_src="custom:MockStockAPI.MockStockAPI",
            lv_list=[KL_TYPE.K_30M],
            config=chan_config,
            autype=0,
        )
        
        try:
            chan.trigger_load({KL_TYPE.K_30M: klines})
            return chan
        except Exception as e:
            logger.error(f"CChan 分析失败：{e}")
            return None
    
    def get_bsp_signal(self, chan: CChan) -> Optional[Dict]:
        """获取 BSP 信号"""
        try:
            latest_bsps = chan.get_latest_bsp(number=1)
            if not latest_bsps:
                return None
            
            bsp = latest_bsps[0]
            return {
                'type': bsp.type2str(),
                'is_buy': bsp.is_buy,
                'price': bsp.klu.close,
                'time': bsp.klu.timestamp,
                'bsp_instance': bsp
            }
        except Exception as e:
            logger.error(f"获取 BSP 失败：{e}")
            return None
    
    def generate_chart(self, chan: CChan, signal: Dict, step: int) -> str:
        """生成图表并返回路径"""
        try:
            from ChanPlot import CChanPlot
            
            plot_driver = CChanPlot(chan)
            
            # 配置图表
            plot_driver.plot(
                show=False,
                save_path=os.path.join(self.output_dir, f"{self.code}_step{step:05d}_{signal['type']}.png"),
                plot_kline=True,
                plot_bsp=True,
                plot_bi=True,
                plot_seg=True,
                plot_zs=True,
            )
            
            return os.path.join(self.output_dir, f"{self.code}_step{step:05d}_{signal['type']}.png")
        except Exception as e:
            logger.error(f"生成图表失败：{e}")
            return ""
    
    def get_gemini_visual_score(self, signal: Dict, chart_path: str) -> int:
        """使用 Gemini API 获取视觉评分"""
        try:
            # 由于我们只有 30M 数据，只传递一张图表
            # VisualJudge 期望至少一张图片
            if not os.path.exists(chart_path):
                logger.warning(f"图表文件不存在：{chart_path}")
                return 0
            
            # 调用 VisualJudge
            # 注意：由于我们只有 30M 图，传递同一张图两次作为占位符
            result = self.visual_judge.evaluate([chart_path, chart_path], signal['type'])
            
            score = result.get('score', 0)
            action = result.get('action', 'WAIT')
            reasoning = result.get('reasoning', '')
            
            logger.info(f"🤖 Gemini 评分：{score}, 动作：{action}")
            logger.info(f"   分析：{reasoning[:100]}...")
            
            return score
            
        except Exception as e:
            logger.error(f"Gemini API 调用失败：{e}")
            return 0
    
    def run_backtest(self) -> Dict[str, Any]:
        """运行回测"""
        logger.info(f"🚀 开始回测 {self.code} ({self.start_date} - {self.end_date})")
        
        if not self.load_data():
            return {'error': '数据加载失败'}
        
        step = 0
        signals_found = 0
        trades_executed = 0
        buys_with_high_score = 0
        gemini_calls = 0
        
        # 逐步处理每根 K 线
        for i in range(len(self.klines_30m)):
            current_klines = self.klines_30m[:i+1]
            current_time = current_klines[-1].timestamp
            
            # 分析当前 K 线数据
            chan = self.analyze_kline(current_klines)
            if not chan:
                continue
            
            # 获取 BSP 信号
            signal = self.get_bsp_signal(chan)
            if not signal:
                continue
            
            signals_found += 1
            
            # 检查是否是新的信号（与上一次不同）
            if hasattr(self, 'last_signal_type') and self.last_signal_type == signal['type']:
                continue
            self.last_signal_type = signal['type']
            
            step += 1
            logger.info(f"📍 步骤 {step}: 发现 {signal['type']} 信号，方向={'买' if signal['is_buy'] else '卖'}，价格={signal['price']:.2f}")
            
            # 生成图表
            chart_path = self.generate_chart(chan, signal, step)
            
            # 获取 Gemini 视觉评分
            visual_score = 0
            if signal['is_buy']:
                # 买入信号需要 Gemini 评分
                gemini_calls += 1
                visual_score = self.get_gemini_visual_score(signal, chart_path)
            else:
                # 卖出信号自动执行（评分设为 100）
                visual_score = 100
            
            # 记录评分
            self.visual_scores.append({
                'step': step,
                'time': str(current_time),
                'type': signal['type'],
                'is_buy': signal['is_buy'],
                'price': signal['price'],
                'visual_score': visual_score,
                'chart': chart_path
            })
            
            # 执行交易
            if signal['is_buy']:
                # 买入：需要评分 >= 阈值 且当前空仓
                if visual_score >= self.min_visual_score and self.current_position == 0:
                    qty = self.broker.calculate_position_size(self.code, signal['price'])
                    if qty > 0:
                        if self.broker.execute_trade(self.code, 'BUY', qty, signal['price'], current_time):
                            self.current_position = 1
                            self.entry_price = signal['price']
                            self.entry_time = current_time
                            trades_executed += 1
                            buys_with_high_score += 1
                            logger.info(f"✅ 执行买入：{qty}股 @ {signal['price']:.2f} (评分={visual_score})")
                else:
                    reason = "评分不足" if visual_score < self.min_visual_score else "已持仓"
                    logger.info(f"⏭️ 跳过买入：{reason} (评分={visual_score}, 阈值={self.min_visual_score})")
            
            elif not signal['is_buy']:
                # 卖出：有持仓就卖出
                if self.current_position == 1:
                    qty = self.broker.get_position_quantity(self.code)
                    if qty > 0:
                        if self.broker.execute_trade(self.code, 'SELL', qty, signal['price'], current_time):
                            self.current_position = 0
                            profit = (signal['price'] - self.entry_price) * qty
                            profit_pct = (signal['price'] - self.entry_price) / self.entry_price * 100
                            trades_executed += 1
                            logger.info(f"✅ 执行卖出：{qty}股 @ {signal['price']:.2f}, 盈亏={profit:.2f} ({profit_pct:.2f}%)")
        
        # 生成结果
        results = {
            'code': self.code,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'initial_funds': self.initial_funds,
            'final_funds': self.broker.available_funds,
            'total_return': (self.broker.available_funds - self.initial_funds) / self.initial_funds * 100,
            'signals_found': signals_found,
            'gemini_calls': gemini_calls,
            'trades_executed': trades_executed,
            'buys_with_high_score': buys_with_high_score,
            'trade_history': self.broker.trade_history,
            'visual_scores': self.visual_scores,
            'final_positions': self.broker.positions
        }
        
        return results
    
    def print_report(self, results: Dict[str, Any]):
        """打印回测报告"""
        print("\n" + "="*60)
        print("📊 回测报告")
        print("="*60)
        print(f"股票代码：{results['code']}")
        print(f"回测区间：{results['start_date']} 至 {results['end_date']}")
        print(f"初始资金：{results['initial_funds']:,.2f} HKD")
        print(f"最终资金：{results['final_funds']:,.2f} HKD")
        print(f"总回报率：{results['total_return']:.2f}%")
        print("-"*60)
        print(f"发现信号数：{results['signals_found']}")
        print(f"Gemini 调用数：{results['gemini_calls']}")
        print(f"执行交易数：{results['trades_executed']}")
        print(f"高分买入数：{results['buys_with_high_score']}")
        print("-"*60)
        
        if results['trade_history']:
            print("\n📝 交易明细:")
            for trade in results['trade_history']:
                action = "🟢 买入" if trade['action'] == 'BUY' else "🔴 卖出"
                print(f"  {trade['timestamp']} {action} {trade['quantity']}股 @ {trade['price']:.2f}")
        
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description='视觉辅助回测系统 - 30M 周期（Gemini API 评分）')
    parser.add_argument('--code', type=str, default='HK.00700', help='股票代码')
    parser.add_argument('--start', type=str, default='2024-03-01', help='开始日期')
    parser.add_argument('--end', type=str, default='2025-02-28', help='结束日期')
    parser.add_argument('--funds', type=float, default=100000.0, help='初始资金')
    parser.add_argument('--min-score', type=int, default=70, help='最小视觉评分阈值')
    parser.add_argument('--output', type=str, default='visual_backtest_charts', help='图表输出目录')
    
    args = parser.parse_args()
    
    # 加载每手股数
    lot_size_map = {
        'HK.00700': 100,
    }
    
    engine = VisualBacktestEngine(
        code=args.code,
        start_date=args.start,
        end_date=args.end,
        initial_funds=args.funds,
        lot_size_map=lot_size_map,
        output_dir=args.output,
        min_visual_score=args.min_score
    )
    
    results = engine.run_backtest()
    engine.print_report(results)
    
    # 保存结果
    import json
    output_file = f"visual_backtest_results_{args.code.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        # 转换时间戳为字符串
        results_copy = results.copy()
        results_copy['trade_history'] = []
        for trade in results['trade_history']:
            trade_copy = trade.copy()
            trade_copy['timestamp'] = str(trade['timestamp'])
            results_copy['trade_history'].append(trade_copy)
        json.dump(results_copy, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 结果已保存到：{output_file}")


if __name__ == '__main__':
    main()
