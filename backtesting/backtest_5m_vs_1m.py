#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多周期离顶对比回测脚本
- 30M 买入
- 可选 1M 或 5M 见卖点一出即离场
- 支持时间范围加长
"""

import os
import sys
import logging
import argparse
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.enhanced_backtester import EnhancedBacktestEngine, HKStockBroker, EnhancedBacktestReporter
from backtesting.backtester import BacktestDataIterator, BacktestStrategyAdapter
from ChanConfig import CChanConfig

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ComparisonEngine(EnhancedBacktestEngine):
    """
    自适应逃顶周期回测引擎：30M买入，{sell_freq}卖点一出即平仓。
    """
    def __init__(self, sell_freq: str = '1M', **kwargs):
        super().__init__(**kwargs)
        self.sell_freq = sell_freq.upper() # '1M' or '5M'
        
    def run(self, config_override: Dict = None) -> Dict[str, Any]:
        self.logger.info(f"🚀 启动 30M->{self.sell_freq} 高频平仓回测引擎...")
        
        # 1. 创建经纪商
        broker_kwargs = {
            'initial_funds': self.initial_funds, 
            'lot_size_map': self.lot_size_map,
            'use_hk_costs': self.use_hk_costs,
            'enable_stop_loss': False # 禁用自带止损
        }
        broker = HKStockBroker(**broker_kwargs)
        
        # 2. 创建主策略适配器 (对应 30M 触发)
        chan_config = self._create_chan_config()
        strategy_adapter = BacktestStrategyAdapter(
            live_trader_instance=None,
            chan_config=chan_config,
            freq=self.freq  # "30M"
        )
        
        # 3. 创建逃脱分析专用适配器 
        exit_chan_config = self._create_chan_config()
        exit_adapter = BacktestStrategyAdapter(
            live_trader_instance=None,
            chan_config=exit_chan_config,
            freq=self.sell_freq
        )
        
        reporter = EnhancedBacktestReporter(broker, strategy_adapter, chan_config)
        
        # 4. 初始化数据迭代器
        data_iterator = BacktestDataIterator(
            loader=self.loader,
            watchlist=self.watchlist,
            freq=self.freq,
            start_date=self.start_date,
            end_date=self.end_date,
            lot_size_map=self.lot_size_map,
            required_freqs=["30M", self.sell_freq, "DAY"] # 👈 注入所需逃脱档位 
        )
        
        if data_iterator.max_index == 0:
            self.logger.error("❌ 无有效时间点进行回测")
            return {'error': 'No valid time points'}
        
        self.logger.info(f"✅ 数据加载完成，共 {data_iterator.max_index} 个时间点")
        
        previous_date = None
        self._last_signal_time = {} # 记录处理状态
        
        # 5. 主循环
        for current_time, snapshot in data_iterator:
            # 每日 T+1 额度释放
            current_date = current_time.date()
            if previous_date is None or current_date != previous_date:
                broker.update_t1_status()
                previous_date = current_date
            
            # ================================================================
            # 🌟 新增 Step 1.5: 检查逃逸
            # ================================================================
            for code in list(broker.positions.keys()):
                code_data = snapshot.get(code)
                if not code_data or self.sell_freq not in code_data:
                    continue
                
                try:
                    chan_exit = exit_adapter._prepare_chan_instance(code, code_data.get(self.sell_freq), self.sell_freq)
                    if chan_exit:
                        all_bsps = chan_exit.get_bsp()
                        if all_bsps:
                            last_bsp = all_bsps[-1]
                            bsp_time = last_bsp.klu.time
                            
                            last_time = self._last_signal_time.get(code)
                            if last_time != bsp_time and not last_bsp.is_buy:
                                self._last_signal_time[code] = bsp_time
                                
                                # 触发卖出
                                qty = broker.get_position_quantity(code)
                                current_price = code_data.get(self.sell_freq)[-1].close
                                
                                if qty > 0:
                                    success = broker.execute_trade(code, 'SELL', qty, current_price, current_time)
                                    if success:
                                        self.logger.info(f"🚨 [{self.sell_freq} 逃顶离场] {code} at {current_time} Price={current_price:.3f}, Type={last_bsp.type2str()}")
                                        reporter.record_trade({
                                            'time': current_time,
                                            'code': code,
                                            'action': 'SELL_EXIT',
                                            'qty': qty,
                                            'price': current_price,
                                            'cost': current_price * qty * 0.001,
                                            'funds_after': broker.available_funds
                                        })
                except Exception as e:
                     self.logger.debug(f"{self.sell_freq} 分析异常: {e}")

            # ================================================================
            # Step 2: 30M 买卖点信号触发 (常规)
            # ================================================================
            trade_signals = []
            for code in self.watchlist:
                if code not in snapshot:
                    continue
                code_data = snapshot[code]
                kline_list_30m = code_data.get('30M', [])
                
                signal = strategy_adapter.get_signal(code, code_data, self.lot_size_map)
                if signal and signal.get('is_valid_for_trade', True):
                    signal['position_qty'] = broker.get_position_quantity(code)
                    if signal['is_buy']:
                        signal['score'] = self._score_buy_signal(kline_list_30m, signal)
                        signal['is_valid_for_trade'] = signal['score'] >= 50
                    else:
                        signal['score'] = 99
                    if signal['is_valid_for_trade']:
                        trade_signals.append(signal)

            # 常规 30M 卖出 
            sells = [s for s in trade_signals if not s['is_buy']]
            for signal in sells:
                code = signal['code']
                qty = signal['position_qty']
                price = signal['signal_price']
                if qty > 0:
                    success = broker.execute_trade(code, 'SELL', qty, price, current_time)

            # 30M 买入
            buys = sorted([s for s in trade_signals if s['is_buy']], key=lambda x: x.get('score', 0), reverse=True)
            for signal in buys:
                code = signal['code']
                price = signal['signal_price']
                lot_size = signal.get('lot_size', 100)
                code_data = snapshot.get(code, {})
                kline_list_30m = code_data.get('30M', [])
                
                if broker.get_position_quantity(code) == 0:
                    atr = self._calculate_atr(kline_list_30m, period=14)
                    if atr > 0:
                        final_qty = broker.calculate_atr_position_size(code, price, atr, lot_size)
                    else:
                        qty = broker.calculate_position_size(code, broker.available_funds, price, max_investment_ratio=0.5)
                        final_qty = (qty // lot_size) * lot_size
                    
                    if final_qty > 0:
                        success = broker.execute_trade(code, 'BUY', final_qty, price, current_time)

        final_time = data_iterator.timeline[-1] if data_iterator.timeline else datetime.now()
        results = reporter.calculate_performance(final_time)
        return results

def main():
    parser = argparse.ArgumentParser(description='30M买入+多周期(1M/5M)逃顶比较')
    parser.add_argument('--start', type=str, default='2025-01-01', help='开始日期')
    parser.add_argument('--end', type=str, default='2025-06-30', help='结束日期')
    parser.add_argument('--codes', type=str, nargs='+', default=["HK.00836"], help='代码')
    parser.add_argument('--sell-freq', type=str, default='1M', choices=['1M', '5M'], help='卖出参考周期')
    
    args = parser.parse_args()
    
    engine = ComparisonEngine(
        sell_freq=args.sell_freq,
        initial_funds=100000,
        start_date=args.start,
        end_date=args.end,
        watchlist=args.codes,
        use_hk_costs=True,
        use_ml=False
    )
    
    results = engine.run()
    results['sell_freq'] = args.sell_freq # 植入对比标记
    engine.generate_report(results, "backtest_reports")
    
    # 打印简要结论便于 python3 直接吐出 stdout
    print(f"--- {args.sell_freq} 成果总结 ---")
    print(f"周期: {args.sell_freq}")
    print(f"总资产率: {results.get('total_return_pct', 0)*100:.2f}%")
    print(f"最大回撤: {results.get('max_drawdown_pct', 0)*100:.2f}%")
    print(f"交易笔数: {results.get('trades_count', 0)}")

if __name__ == '__main__':
    main()
