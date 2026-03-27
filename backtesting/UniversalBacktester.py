#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Universal Backtester (Next-Gen)
- Accurate Market Split: HK (T+0), CN (T+1)
- ML model (SignalValidator) validation accurately hooked
- Live Controller continuous risk mechanics (ATR trailing stop limiters)
"""

import os
import sys
import math
import logging
import argparse
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.backtester import BacktestBroker, BacktestReporter, BacktestStrategyAdapter, BacktestDataIterator, BacktestKLineUnit
from BacktestDataLoader import BacktestDataLoader
from config import TRADING_CONFIG, CHAN_CONFIG
from ML.SignalValidator import SignalValidator

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class UniversalBroker(BacktestBroker):
    """
    通用市场经纪商，支持 A股 (T+1) 和 港股 (T+0)，精确计算各自成本及涨跌停。
    """
    def __init__(self, market: str = 'HK', initial_funds: float = 100000.0, lot_size_map: Dict[str, int] = None):
        super().__init__(initial_funds, lot_size_map)
        self.market = market.upper() # 'HK' or 'CN'
        self.enable_stop_loss = True
        self.stop_loss_state: Dict[str, Dict] = {}
        self.structure_barrier: Dict[str, Dict] = {} # 结构锁阻滞

    def get_available_position_quantity(self, code: str) -> int:
        pos = self.positions.get(code, {})
        if self.market == 'CN':
            return pos.get('available_qty', 0)
        return pos.get('qty', 0)

    def update_t1_status(self):
        """A股 T+1 释放可用"""
        if self.market == 'CN':
            for code, pos in self.positions.items():
                pos['available_qty'] = pos['qty']

    def calculate_cost(self, amount: float, is_buy: bool) -> float:
        if self.market == 'HK':
            commission = max(3.0, amount * 0.0003)
            stamp_duty = math.ceil(amount * 0.001)
            trading_fee = amount * 0.0000565
            clearing_fee = amount * 0.00002
            return commission + stamp_duty + trading_fee + clearing_fee
        else:
            # 简化 A股 成本：佣金 0.03%，卖方印花税 0.05%
            commission = max(5.0, amount * 0.0003)
            stamp = amount * 0.0005 if not is_buy else 0.0
            return commission + stamp

    def execute_trade(self, code: str, action: str, quantity: int, price: float, timestamp: pd.Timestamp) -> bool:
        if quantity <= 0: return False
        lot_size = self.get_lot_size(code)
        if quantity % lot_size != 0: quantity = (quantity // lot_size) * lot_size
        if quantity <= 0: return False

        trade_amount = price * quantity
        cost = self.calculate_cost(trade_amount, is_buy=(action.upper() == 'BUY'))

        if action.upper() == 'BUY':
            if self.available_funds < (trade_amount + cost): return False
            self.available_funds -= (trade_amount + cost)
            if code not in self.positions:
                self.positions[code] = {'qty': 0, 'available_qty': 0, 'avg_price': 0.0}
            
            pos = self.positions[code]
            old_qty = pos['qty']
            new_qty = old_qty + quantity
            pos['avg_price'] = ((old_qty * pos['avg_price']) + (price * quantity)) / new_qty
            pos['qty'] = new_qty
            if self.market != 'CN': # 港股实时可用
                pos['available_qty'] = new_qty
                
            self.trades.append({'time': timestamp, 'code': code, 'action': 'BUY', 'qty': quantity, 'price': price, 'cost': cost, 'funds_after': self.available_funds})
            return True

        elif 'SELL' in action.upper():
            available = self.get_available_position_quantity(code)
            if available < quantity: return False
            self.available_funds += (trade_amount - cost)
            self.positions[code]['qty'] -= quantity
            if self.positions[code]['qty'] <= 0:
                del self.positions[code]
            else:
                self.positions[code]['available_qty'] -= quantity

            self.trades.append({'time': timestamp, 'code': code, 'action': action.upper(), 'qty': quantity, 'price': price, 'cost': cost, 'funds_after': self.available_funds})
            return True
        return False

class UniversalBacktester:
    def __init__(self, market: str = 'HK', initial_funds: float = 100000.0, 
                 start_date: str = '2025-01-01', end_date: str = '2025-05-30', 
                 watchlist: List[str] = None, use_ml: bool = True, 
                 atr_stop_trail: float = 2.5, enable_quick_retreat: bool = True,
                 sell_freq: str = None):
        self.market = market.upper()
        self.initial_funds = initial_funds
        self.start_date = start_date
        self.end_date = end_date
        self.watchlist = watchlist if watchlist else []
        self.use_ml = use_ml
        self.atr_stop_trail = atr_stop_trail
        self.enable_quick_retreat = enable_quick_retreat
        self.sell_freq = sell_freq
        self.broker = UniversalBroker(market=self.market, initial_funds=initial_funds)
        self.validator = SignalValidator() if SignalValidator else None
        self.trade_log = []

    def _calculate_atr(self, kline_list: List[BacktestKLineUnit], period: int = 14) -> float:
        if len(kline_list) < period: return 0.0
        tr_list = []
        for i in range(1, len(kline_list)):
            cur = kline_list[i]
            prev = kline_list[i-1]
            tr = max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
            tr_list.append(tr)
        return float(np.mean(tr_list[-period:])) if tr_list else 0.0

    def run(self, required_freqs: List[str] = None):
        loader = BacktestDataLoader()
        lot_sizes = {c: 100 for c in self.watchlist} # 简化配置
        
        req_freqs = ["30M", "1M", "DAY"]
        if self.sell_freq and self.sell_freq not in req_freqs:
            req_freqs.append(self.sell_freq)
            
        data_iterator = BacktestDataIterator(
            loader=loader,
            watchlist=self.watchlist,
            freq="30M",
            start_date=self.start_date,
            end_date=self.end_date,
            lot_size_map=lot_sizes,
            required_freqs=req_freqs
        )

        from ChanConfig import CChanConfig
        # 允许拉1,2,3类点
        cfg = CChanConfig()
        cfg.bs_type = '1,1p,2,2s,3a,3b'
        strategy_adapter = BacktestStrategyAdapter(None, cfg, freq="30M")
        
        exit_adapter = None
        if self.sell_freq:
            exit_cfg = CChanConfig()
            exit_cfg.bs_type = '1,1p,2,2s,3a,3b'
            exit_adapter = BacktestStrategyAdapter(None, exit_cfg, freq=self.sell_freq)

        last_date = None
        for current_time, snapshot in data_iterator:
            cur_date = current_time.date()
            if last_date is None or cur_date != last_date:
                self.broker.update_t1_status()
                last_date = cur_date

            # ---- 风控模块 (Trailing Stops) ----
            for code in list(self.broker.positions.keys()):
                pos_data = snapshot.get(code)
                if not pos_data: continue
                # 假设拉最新的 1M 逃跑或 30M 价格
                cur_kline = pos_data.get('1M', pos_data.get('30M', []))[-1]
                cur_price = cur_kline.close
                
                # 🌟 [关键修复] 优先判断是否触发小级别缠论卖点逃顶
                if exit_adapter and self.sell_freq in pos_data:
                    sig_exit = exit_adapter.get_signal(code, pos_data, lot_sizes)
                    if sig_exit:
                        logger.info(f"DEBUG: 5M signal check -> {code} at {current_time} IsBuy={sig_exit['is_buy']} Type={sig_exit['bsp_type']}")
                    if sig_exit and not sig_exit['is_buy'] and sig_exit.get('is_valid_for_trade', True):
                        qty = self.broker.get_available_position_quantity(code)
                        if qty > 0 and self.broker.execute_trade(code, 'SELL_STOP', qty, cur_price, current_time):
                            logger.info(f"⚡️ [{self.sell_freq} 缠论卖点暴击逃顶] {code} at {current_time} Type={sig_exit['bsp_type']}")
                            if code in self.broker.stop_loss_state: del self.broker.stop_loss_state[code]
                            continue # 已经卖出，跳过后续价格止损逻辑
                
                tracker = self.broker.stop_loss_state.get(code)
                if not tracker: continue
                
                if cur_price > tracker['highest_price']: tracker['highest_price'] = cur_price
                
                highest = tracker['highest_price']
                entry_price = tracker['entry_price']
                atr = tracker['atr']
                
                # 港股的双重止损：2.5倍ATR移动，或1.2倍固定
                trail_active = tracker.get('trail_active', False)
                profit_threshold = entry_price + (atr * 1.5)
                
                if not trail_active and cur_price >= profit_threshold:
                    tracker['trail_active'] = True
                    trail_active = True
                    
                stop_price = highest - (atr * self.atr_stop_trail) if trail_active else entry_price - (atr * 1.2)
                
                # 特殊：5M级快速回撤 (1.0 ATR)
                is_quick_retreat = self.enable_quick_retreat and trail_active and (highest - cur_price) > (1.0 * atr)

                if cur_price < stop_price or is_quick_retreat:
                    qty = self.broker.get_available_position_quantity(code)
                    if qty > 0 and self.broker.execute_trade(code, 'SELL_STOP', qty, cur_price, current_time):
                        logger.info(f"🚨 [风控止损] {code} at {current_time} Price={cur_price:.3f} (QuickRetreat={is_quick_retreat})")
                        del self.broker.stop_loss_state[code]

            # ---- 信号扫描模块 ----
            for code in self.watchlist:
                if code not in snapshot: continue
                sig = strategy_adapter.get_signal(code, snapshot[code], lot_sizes)
                if not sig or not sig.get('is_valid_for_trade', True): continue

                is_buy = sig['is_buy']
                price = sig['signal_price']

                # ML 验证对接
                if self.use_ml and self.validator:
                    try:
                        chan_main = sig['chan_analysis']['chan_multi_level'][0]
                        bsp = sig['chan_analysis']['bsp_instance']
                        # 仅在买入时用 ML 过滤增添 Alpha
                        if is_buy:
                            res = self.validator.validate_signal(chan_main, bsp)
                            prob = res.get('prob', 0.0)
                            if prob < 0.70: continue # 剔除概率不达标的信号
                            sig['ml_prob'] = prob
                    except Exception as e_ml:
                        logger.debug(f"Validator exception {e_ml}")

                if is_buy and self.broker.get_position_quantity(code) == 0:
                    atr = self._calculate_atr(snapshot[code].get('30M', []), 14)
                    if atr > 0:
                        qty = self.broker.calculate_position_size(code, self.broker.available_funds, price, max_investment_ratio=0.5)
                        if qty > 0 and self.broker.execute_trade(code, 'BUY', qty, price, current_time):
                            self.broker.stop_loss_state[code] = {
                                'highest_price': price,
                                'atr': atr,
                                'entry_price': price,
                                'trail_active': False
                            }
                elif not is_buy:
                    qty = self.broker.get_available_position_quantity(code)
                    if qty > 0 and self.broker.execute_trade(code, 'SELL', qty, price, current_time):
                        if code in self.broker.stop_loss_state: del self.broker.stop_loss_state[code]

        res = self.broker.get_final_performance(data_iterator.timeline[-1])
        logger.info(f"🏆 绩效结果 {self.market}: 期末权益 {res['final_portfolio_value']:.2f}, 回报 {res['total_return_pct']*100:.2f}%")
        return res

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', type=str, default='HK')
    parser.add_argument('--codes', type=str, nargs='+', default=["HK.00700", "HK.00836"])
    args = parser.parse_args()
    
    tester = UniversalBacktester(market=args.market, watchlist=args.codes)
    tester.run()
