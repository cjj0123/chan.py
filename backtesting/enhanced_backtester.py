#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版港股回测引擎
- 精确的港股交易成本计算
- 参数优化功能
- 详细的绩效分析
"""

import os
import sys
import math
import json
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Callable
from itertools import product

import pandas as pd
import numpy as np

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入基础回测组件
from backtesting.backtester import BacktestBroker, BacktestReporter, BacktestStrategyAdapter
from BacktestDataLoader import BacktestDataLoader, BacktestKLineUnit

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backtest_enhanced.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# 港股精确交易成本计算
# ============================================================================

class HKStockBroker(BacktestBroker):
    """
    港股交易经纪商，精确计算交易成本
    
    港股交易费用明细：
    - 佣金：0.03% (最低 3 港元)
    - 印花税：0.1% (向上取整，买卖双边)
    - 交易费：0.00565% (买卖双边)
    - 中央结算费：0.002% (买卖双边)
    """
    
    # 港股费用标准
    HK_COST_RATES = {
        'commission_rate': 0.0003,      # 佣金费率 0.03%
        'commission_min': 3.0,          # 最低佣金 3 港元
        'stamp_duty_rate': 0.001,       # 印花税 0.1%
        'trading_fee_rate': 0.0000565,  # 交易费 0.00565%
        'clearing_fee_rate': 0.00002,   # 中央结算费 0.002%
    }
    
    def __init__(self, initial_funds: float = 100000.0, 
                 lot_size_map: Dict[str, int] = None,
                 use_hk_costs: bool = True):
        """
        初始化港股经纪商
        
        Args:
            initial_funds: 初始资金
            lot_size_map: 每手股数配置
            use_hk_costs: 是否使用港股精确成本计算
        """
        super().__init__(initial_funds, lot_size_map)
        self.use_hk_costs = use_hk_costs
        self.cost_details: List[Dict] = []  # 记录每笔交易的成本明细
    
    def calculate_hk_cost(self, amount: float, is_buy: bool) -> Tuple[float, Dict]:
        """
        计算港股交易总成本
        
        Args:
            amount: 交易金额
            is_buy: 是否为买入
            
        Returns:
            (总成本，成本明细字典)
        """
        # 佣金
        commission = max(self.HK_COST_RATES['commission_min'], 
                        amount * self.HK_COST_RATES['commission_rate'])
        
        # 印花税 (向上取整)
        stamp_duty = math.ceil(amount * self.HK_COST_RATES['stamp_duty_rate'])
        
        # 交易费
        trading_fee = amount * self.HK_COST_RATES['trading_fee_rate']
        
        # 中央结算费
        clearing_fee = amount * self.HK_COST_RATES['clearing_fee_rate']
        
        total_cost = commission + stamp_duty + trading_fee + clearing_fee
        
        cost_detail = {
            'commission': commission,
            'stamp_duty': stamp_duty,
            'trading_fee': trading_fee,
            'clearing_fee': clearing_fee,
            'total': total_cost
        }
        
        return total_cost, cost_detail
    
    def execute_trade(self, code: str, action: str, quantity: int, 
                      price: float, timestamp: pd.Timestamp) -> bool:
        """
        执行模拟交易（使用港股精确成本）
        
        Args:
            code: 股票代码
            action: 'BUY' 或 'SELL'
            quantity: 数量
            price: 价格
            timestamp: 时间戳
            
        Returns:
            是否执行成功
        """
        if quantity <= 0:
            return False
        
        lot_size = self.get_lot_size(code)
        if quantity % lot_size != 0:
            quantity = (quantity // lot_size) * lot_size
            if quantity == 0:
                return False
        
        trade_amount = price * quantity
        action_upper = action.upper()
        
        if self.use_hk_costs:
            # 使用港股精确成本
            cost, cost_detail = self.calculate_hk_cost(trade_amount, is_buy=(action_upper == 'BUY'))
        else:
            # 使用简化成本
            cost = trade_amount * self.transaction_cost_rate
            cost_detail = {'total': cost}
        
        if action_upper == 'BUY':
            required_funds = trade_amount + cost
            if self.available_funds < required_funds:
                logger.warning(f"BUY {code}: 资金不足。需要 {required_funds:.2f}, 拥有 {self.available_funds:.2f}")
                return False
            
            self.available_funds -= required_funds
            
            # 更新持仓
            if code not in self.positions:
                self.positions[code] = {'qty': 0, 'avg_price': 0.0}
            
            old_qty = self.positions[code]['qty']
            new_qty = old_qty + quantity
            old_cost = old_qty * self.positions[code]['avg_price']
            new_avg_price = (old_cost + price * quantity) / new_qty if new_qty > 0 else price
            
            self.positions[code]['qty'] = new_qty
            self.positions[code]['avg_price'] = new_avg_price
            
            trade_record = {
                'time': timestamp, 
                'code': code, 
                'action': 'BUY', 
                'qty': quantity, 
                'price': price,
                'amount': trade_amount,
                'cost': cost,
                'cost_detail': cost_detail,
                'funds_after': self.available_funds
            }
            self.trades.append(trade_record)
            self.cost_details.append({'time': timestamp, 'code': code, 'action': 'BUY', **cost_detail})
            
            logger.info(f"BUY {code}: Qty={quantity}, Price={price:.3f}, Cost={cost:.2f}")
            return True
            
        elif action_upper == 'SELL':
            if self.get_position_quantity(code) < quantity:
                logger.warning(f"SELL {code}: 持仓不足 {quantity} 股，当前持仓 {self.get_position_quantity(code)}")
                return False
            
            # 卖出收入减去成本
            revenue = trade_amount - cost
            self.available_funds += revenue
            
            # 更新持仓
            self.positions[code]['qty'] -= quantity
            if self.positions[code]['qty'] == 0:
                del self.positions[code]
            
            trade_record = {
                'time': timestamp, 
                'code': code, 
                'action': 'SELL', 
                'qty': quantity, 
                'price': price,
                'amount': trade_amount,
                'cost': cost,
                'cost_detail': cost_detail,
                'funds_after': self.available_funds
            }
            self.trades.append(trade_record)
            self.cost_details.append({'time': timestamp, 'code': code, 'action': 'SELL', **cost_detail})
            
            logger.info(f"SELL {code}: Qty={quantity}, Price={price:.3f}, Revenue={revenue:.2f}")
            return True
            
        return False
    
    def get_cost_statistics(self) -> Dict[str, float]:
        """获取交易成本统计"""
        if not self.cost_details:
            return {'total_cost': 0.0}
        
        total_commission = sum(d.get('commission', 0) for d in self.cost_details)
        total_stamp_duty = sum(d.get('stamp_duty', 0) for d in self.cost_details)
        total_trading_fee = sum(d.get('trading_fee', 0) for d in self.cost_details)
        total_clearing_fee = sum(d.get('clearing_fee', 0) for d in self.cost_details)
        
        return {
            'total_cost': sum(d.get('total', 0) for d in self.cost_details),
            'total_commission': total_commission,
            'total_stamp_duty': total_stamp_duty,
            'total_trading_fee': total_trading_fee,
            'total_clearing_fee': total_clearing_fee,
        }


# ============================================================================
# 增强的回测报告
# ============================================================================

class EnhancedBacktestReporter(BacktestReporter):
    """增强的回测报告生成器"""
    
    def __init__(self, broker: HKStockBroker, strategy_adapter: Any, config: Any = None):
        super().__init__(broker, strategy_adapter, config)
        self.broker: HKStockBroker = broker  # 类型提示
    
    def calculate_performance(self, end_time: pd.Timestamp) -> Dict[str, Any]:
        """计算增强的绩效指标"""
        perf = super().calculate_performance(end_time)
        
        # 添加成本统计
        cost_stats = self.broker.get_cost_statistics()
        perf['cost_statistics'] = cost_stats
        
        # 添加更详细的统计
        perf.update(self._calculate_advanced_stats(end_time))
        
        return perf
    
    def _calculate_advanced_stats(self, end_time: pd.Timestamp) -> Dict[str, Any]:
        """计算高级统计指标"""
        stats = {}
        
        # 获取交易列表
        buys = [t for t in self.broker.trades if t['action'] == 'BUY']
        sells = [t for t in self.broker.trades if t['action'] == 'SELL']
        
        # 胜率计算
        if sells:
            # 简单计算：每笔卖出的盈亏
            winning_trades = 0
            total_profit = 0
            total_loss = 0
            
            for sell in sells:
                # 找到对应的买入
                matching_buys = [b for b in buys 
                                if b['code'] == sell['code'] 
                                and b['time'] < sell['time']
                                and b['qty'] <= sell['qty']]
                
                if matching_buys:
                    avg_buy_price = sum(b['price'] for b in matching_buys) / len(matching_buys)
                    profit = (sell['price'] - avg_buy_price) * sell['qty']
                    
                    if profit > 0:
                        winning_trades += 1
                        total_profit += profit
                    else:
                        total_loss += abs(profit)
            
            stats['win_rate'] = winning_trades / len(sells) if sells else 0
            stats['avg_profit'] = total_profit / winning_trades if winning_trades > 0 else 0
            stats['avg_loss'] = total_loss / (len(sells) - winning_trades) if (len(sells) - winning_trades) > 0 else 0
            stats['profit_loss_ratio'] = stats['avg_profit'] / stats['avg_loss'] if stats['avg_loss'] > 0 else float('inf')
        
        # 年化回报率 (假设 252 个交易日)
        if buys:
            first_trade_time = min(t['time'] for t in buys)
            days = (end_time - first_trade_time).days
            if days > 0:
                total_return = self.broker.get_final_performance(end_time)['total_return_pct']
                stats['annualized_return'] = (1 + total_return) ** (365 / days) - 1
            else:
                stats['annualized_return'] = 0
        else:
            stats['annualized_return'] = 0
        
        # 交易频率
        stats['trades_per_month'] = len(self.broker.trades) / max(1, (end_time - buys[0]['time']).days / 30) if buys else 0
        
        return stats
    
    def generate_detailed_report(self, results: Dict[str, Any], 
                                  start_time_str: str, end_time_str: str) -> str:
        """生成详细的回测报告"""
        report_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        report = []
        report.append(f"# 港股缠论回测详细报告\n")
        report.append(f"*生成时间：{report_time}*\n")
        
        # 1. 回测参数
        report.append("## 📋 1. 回测参数\n")
        report.append(f"- **回测范围**: {start_time_str} 至 {end_time_str}")
        report.append(f"- **初始资金**: {results['initial_funds']:,.2f} HKD")
        report.append(f"- **主频率**: 30M")
        report.append(f"- **使用港股精确成本**: {self.broker.use_hk_costs}")
        report.append("")
        
        # 2. 核心绩效指标
        report.append("## 📊 2. 核心绩效指标\n")
        report.append(f"- **期末总资产**: {results['final_portfolio_value']:,.2f} HKD")
        report.append(f"- **最终现金**: {results['final_cash']:,.2f} HKD")
        report.append(f"- **总回报率**: **{results['total_return_pct'] * 100:.2f}%**")
        report.append(f"- **年化回报率**: **{results.get('annualized_return', 0) * 100:.2f}%**")
        report.append(f"- **最大回撤**: **{results['max_drawdown_pct'] * 100:.2f}%**")
        report.append(f"- **夏普比率**: {self._calculate_sharpe_ratio():.2f}")
        report.append("")
        
        # 3. 交易统计
        report.append("## 📈 3. 交易统计\n")
        report.append(f"- **总交易次数**: {results['trades_count']}")
        report.append(f"- **买入次数**: {results['total_buys']}")
        report.append(f"- **卖出次数**: {results['total_sells']}")
        report.append(f"- **胜率**: {results.get('win_rate', 0) * 100:.2f}%")
        report.append(f"- **盈亏比**: {results.get('profit_loss_ratio', 0):.2f}")
        report.append(f"- **月均交易**: {results.get('trades_per_month', 0):.1f} 笔")
        report.append("")
        
        # 4. 成本统计
        report.append("## 💰 4. 交易成本明细\n")
        cost_stats = results.get('cost_statistics', {})
        report.append(f"- **总交易成本**: {cost_stats.get('total_cost', 0):,.2f} HKD")
        report.append(f"  - 佣金：{cost_stats.get('total_commission', 0):,.2f} HKD")
        report.append(f"  - 印花税：{cost_stats.get('total_stamp_duty', 0):,.2f} HKD")
        report.append(f"  - 交易费：{cost_stats.get('total_trading_fee', 0):,.2f} HKD")
        report.append(f"  - 中央结算费：{cost_stats.get('total_clearing_fee', 0):,.2f} HKD")
        report.append("")
        
        # 5. 最终持仓
        report.append("## 📦 5. 最终持仓\n")
        if results['final_positions']:
            report.append("| 股票代码 | 持仓数量 | 平均成本 |")
            report.append("|---------|---------|---------|")
            for code, pos in results['final_positions'].items():
                report.append(f"| {code} | {pos['qty']:,} | {pos['avg_price']:.3f} |")
        else:
            report.append("回测结束时无持仓。")
        report.append("")
        
        # 6. 交易明细
        report.append("## 📝 6. 交易明细 (前 50 笔)\n")
        if self.trade_log:
            report.append("| 时间 | 代码 | 动作 | 数量 | 价格 | 成本 |")
            report.append("|------|------|------|------|------|------|")
            for trade in self.trade_log[:50]:
                report.append(
                    f"| {trade['time'].strftime('%Y-%m-%d %H:%M')} | "
                    f"{trade['code']} | {trade['action']} | "
                    f"{trade['qty']:,} | {trade['price']:.3f} | "
                    f"{trade['cost']:.2f} |"
                )
            if len(self.trade_log) > 50:
                report.append(f"\n*... 共 {len(self.trade_log)} 笔交易*")
        else:
            report.append("无交易记录。")
        report.append("")
        
        # 7. 建议
        report.append("## 💡 7. 总结与建议\n")
        if results['total_return_pct'] > 0:
            report.append("✅ 策略在回测期间实现盈利。")
        else:
            report.append("⚠️ 策略在回测期间出现亏损，建议优化参数。")
        
        if results.get('max_drawdown_pct', 0) > 0.2:
            report.append("⚠️ 最大回撤超过 20%，建议降低仓位或增加过滤条件。")
        
        if results.get('win_rate', 0) < 0.4:
            report.append("⚠️ 胜率低于 40%，建议优化入场信号。")
        
        return "\n".join(report)
    
    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """计算夏普比率"""
        if not self.trade_log:
            return 0.0
        
        # 计算收益率序列
        returns = []
        prev_value = self.broker.initial_funds
        
        for trade in sorted(self.trade_log, key=lambda x: x['time']):
            current_value = trade['funds_after'] + sum(
                p['qty'] * p['avg_price'] for p in self.broker.positions.values()
            )
            if prev_value > 0:
                returns.append((current_value - prev_value) / prev_value)
            prev_value = current_value
        
        if not returns or np.std(returns) == 0:
            return 0.0
        
        # 年化夏普比率
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        sharpe = (mean_return - risk_free_rate / 252) / std_return * np.sqrt(252)
        
        return sharpe
    
    def export_to_json(self, results: Dict[str, Any], filename: str):
        """导出 JSON 格式结果"""
        # 转换时间对象为字符串
        export_results = {}
        for k, v in results.items():
            if isinstance(v, dict):
                export_results[k] = {}
                for k2, v2 in v.items():
                    if isinstance(v2, pd.Timestamp):
                        export_results[k][k2] = v2.isoformat()
                    else:
                        export_results[k][k2] = v2
            elif isinstance(v, pd.Timestamp):
                export_results[k] = v.isoformat()
            else:
                export_results[k] = v
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_results, f, indent=2, ensure_ascii=False)
        logger.info(f"✅ 结果已导出：{filename}")
    
    def export_trades_to_csv(self, filename: str):
        """导出交易明细 CSV"""
        if not self.trade_log:
            return
        
        df = pd.DataFrame(self.trade_log)
        df['time'] = df['time'].apply(lambda x: x.isoformat() if isinstance(x, pd.Timestamp) else str(x))
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 交易明细已导出：{filename}")


# ============================================================================
# 参数优化器
# ============================================================================

class ParameterOptimizer:
    """策略参数优化器"""
    
    def __init__(self, base_config: Dict[str, Any]):
        """
        初始化优化器
        
        Args:
            base_config: 基础配置
        """
        self.base_config = base_config
        self.logger = logging.getLogger(__name__ + ".Optimizer")
    
    def grid_search(self, param_grid: Dict[str, List[Any]], 
                    backtest_func: Callable[[Dict], Dict],
                    metric: str = 'total_return_pct') -> pd.DataFrame:
        """
        网格搜索最优参数
        
        Args:
            param_grid: 参数网格 {param_name: [values]}
            backtest_func: 回测函数，接收配置字典，返回结果字典
            metric: 优化目标指标
            
        Returns:
            结果 DataFrame，按目标指标排序
        """
        results = []
        
        # 生成所有参数组合
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(product(*param_values))
        
        self.logger.info(f"🔍 开始网格搜索，共 {len(combinations)} 个参数组合")
        
        for i, combo in enumerate(combinations):
            config = self.base_config.copy()
            
            # 应用当前参数组合
            for j, name in enumerate(param_names):
                config[name] = combo[j]
            
            try:
                # 运行回测
                result = backtest_func(config)
                result_row = {**config, **result}
                results.append(result_row)
                
                self.logger.info(
                    f"[{i+1}/{len(combinations)}] {config} => "
                    f"{metric}={result.get(metric, 0):.4f}"
                )
            except Exception as e:
                self.logger.error(f"[{i+1}/{len(combinations)}] 回测失败：{e}")
                continue
        
        # 转换为 DataFrame 并排序
        df = pd.DataFrame(results)
        if metric in df.columns:
            df = df.sort_values(metric, ascending=False)
        
        return df
    
    def get_best_params(self, results_df: pd.DataFrame, 
                        metric: str = 'total_return_pct') -> Dict[str, Any]:
        """获取最优参数"""
        if results_df.empty:
            return self.base_config
        
        best_row = results_df.iloc[0]
        param_names = list(self.base_config.keys())
        
        return {k: best_row[k] for k in param_names if k in best_row}


# ============================================================================
# 增强的回测引擎
# ============================================================================

class EnhancedBacktestEngine:
    """增强的回测引擎"""
    
    def __init__(self, 
                 initial_funds: float = 100000.0,
                 start_date: str = "2024-01-01",
                 end_date: str = "2025-12-31",
                 watchlist: List[str] = None,
                 lot_size_file: str = "stock_cache/lot_size_config.json",
                 use_hk_costs: bool = True):
        """
        初始化回测引擎
        
        Args:
            initial_funds: 初始资金
            start_date: 开始日期
            end_date: 结束日期
            watchlist: 股票列表
            lot_size_file: 每手股数配置文件
            use_hk_costs: 是否使用港股精确成本
        """
        self.initial_funds = initial_funds
        self.start_date = start_date
        self.end_date = end_date
        self.watchlist = watchlist or ["HK.00700", "HK.00836", "HK.02688"]
        self.use_hk_costs = use_hk_costs
        
        # 加载每手股数配置
        self.lot_size_map = self._load_lot_size_map(lot_size_file)
        
        # 初始化组件
        self.loader = BacktestDataLoader()
        self.chan_config = self._create_chan_config()
        
        self.logger = logging.getLogger(__name__)
    
    def _load_lot_size_map(self, lot_size_file: str) -> Dict[str, int]:
        """加载每手股数配置"""
        if os.path.exists(lot_size_file):
            with open(lot_size_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 默认配置
        return {
            "HK.00700": 100,
            "HK.00836": 500,
            "HK.02688": 1000,
        }
    
    def _create_chan_config(self):
        """创建缠论配置"""
        try:
            from ChanConfig import CChanConfig
            return CChanConfig({
                "bi_strict": True,
                "one_bi_zs": False,
                "seg_algo": "chan",
                "bs_type": '1,1p,2,2s,3a,3b',
                "macd": {"fast": 12, "slow": 26, "signal": 9},
                "divergence_rate": float("inf"),
                "min_zs_cnt": 0,
                "bsp2_follow_1": False,
                "bsp3_follow_1": False,
                "bs1_peak": False,
                "macd_algo": "peak",
                "zs_algo": "normal",
            })
        except ImportError:
            self.logger.warning("⚠️ CChanConfig 未找到，使用默认配置")
            return None
    
    def run(self, config_override: Dict = None) -> Dict[str, Any]:
        """
        运行回测
        
        Args:
            config_override: 配置覆盖
            
        Returns:
            回测结果
        """
        self.logger.info("🚀 开始运行回测...")
        self.logger.info(f"📅 日期范围：{self.start_date} 至 {self.end_date}")
        self.logger.info(f"📊 股票列表：{self.watchlist}")
        
        # 创建经纪商
        broker = HKStockBroker(
            initial_funds=self.initial_funds,
            lot_size_map=self.lot_size_map,
            use_hk_costs=self.use_hk_costs
        )
        
        # 创建策略适配器
        strategy_adapter = BacktestStrategyAdapter(
            live_trader_instance=None,
            chan_config=self.chan_config
        )
        
        # 创建报告器
        reporter = EnhancedBacktestReporter(broker, strategy_adapter, self.chan_config)
        
        # 数据迭代器
        from backtesting.backtester import BacktestDataIterator
        data_iterator = BacktestDataIterator(
            loader=self.loader,
            watchlist=self.watchlist,
            freq="30M",
            start_date=self.start_date,
            end_date=self.end_date,
            lot_size_map=self.lot_size_map
        )
        
        if data_iterator.max_index == 0:
            self.logger.error("❌ 无有效时间点进行回测")
            return {'error': 'No valid time points'}
        
        self.logger.info(f"✅ 数据加载完成，共 {data_iterator.max_index} 个时间点")
        
        # 主循环
        for current_time, snapshot in data_iterator:
            trade_signals = []
            
            for code in self.watchlist:
                if code not in snapshot:
                    continue
                
                signal = strategy_adapter.get_signal(code, snapshot[code], self.lot_size_map)
                
                if signal:
                    signal['position_qty'] = broker.get_position_quantity(code)
                    signal['score'] = 99
                    signal['is_valid_for_trade'] = True
                    trade_signals.append(signal)
            
            if not trade_signals:
                continue
            
            # 处理卖出
            sells = sorted([s for s in trade_signals if not s['is_buy']], 
                          key=lambda x: x.get('score', 0), reverse=True)
            for signal in sells:
                code = signal['code']
                qty = signal['position_qty']
                price = signal['signal_price']
                
                self.logger.debug(f"尝试处理 SELL 信号: {code}, qty={qty}, price={price}")
                if qty > 0:
                    success = broker.execute_trade(code, 'SELL', qty, price, current_time)
                    if success:
                        reporter.record_trade({
                            'time': current_time,
                            'code': code,
                            'action': 'SELL',
                            'qty': qty,
                            'price': price,
                            'cost': price * qty * 0.001,  # 估算
                            'funds_after': broker.available_funds
                        })
                    else:
                        self.logger.debug(f"SELL 信号被拒: {code}, qty={qty}")
            
            # 处理买入
            buys = sorted([s for s in trade_signals if s['is_buy']], 
                         key=lambda x: x.get('score', 0), reverse=True)
            for signal in buys:
                code = signal['code']
                price = signal['signal_price']
                lot_size = signal.get('lot_size', 100)
                
                self.logger.debug(f"尝试处理 BUY 信号: {code}, price={price}, lot_size={lot_size}, current_qty={broker.get_position_quantity(code)}")
                if broker.get_position_quantity(code) == 0:
                    qty = broker.calculate_position_size(code, broker.available_funds, price)
                    final_qty = (qty // lot_size) * lot_size
                    self.logger.debug(f"计算出来的买入数量: raw_qty={qty}, final_qty={final_qty}, funds={broker.available_funds}")
                    
                    if final_qty > 0:
                        success = broker.execute_trade(code, 'BUY', final_qty, price, current_time)
                        if success:
                            reporter.record_trade({
                                'time': current_time,
                                'code': code,
                                'action': 'BUY',
                                'qty': final_qty,
                                'price': price,
                                'cost': price * final_qty * 0.001,  # 估算
                                'funds_after': broker.available_funds
                            })
                        else:
                            self.logger.debug(f"BUY 信号执行失败: {code}, qty={final_qty}, funds={broker.available_funds}")
                    else:
                        self.logger.debug(f"买入数量被 lot_size({lot_size}) 截断为 0: {code}")
        
        # 生成结果
        final_time = data_iterator.timeline[-1] if data_iterator.timeline else datetime.now()
        results = reporter.calculate_performance(final_time)
        
        self.logger.info("✅ 回测完成")
        self.logger.info(f"📈 总回报率：{results['total_return_pct'] * 100:.2f}%")
        
        return results
    
    def generate_report(self, results: Dict[str, Any], output_dir: str = "backtest_reports"):
        """生成回测报告"""
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 创建报告器
        broker = HKStockBroker(
            initial_funds=self.initial_funds,
            lot_size_map=self.lot_size_map,
            use_hk_costs=self.use_hk_costs
        )
        reporter = EnhancedBacktestReporter(broker, None, self.chan_config)
        
        # 生成 Markdown 报告
        report_md = reporter.generate_detailed_report(results, self.start_date, self.end_date)
        report_file = os.path.join(output_dir, f"report_{timestamp}.md")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_md)
        self.logger.info(f"✅ 报告已保存：{report_file}")
        
        # 导出 JSON
        json_file = os.path.join(output_dir, f"results_{timestamp}.json")
        reporter.export_to_json(results, json_file)
        
        # 导出 CSV
        csv_file = os.path.join(output_dir, f"trades_{timestamp}.csv")
        reporter.export_trades_to_csv(csv_file)
        
        return report_file


# ============================================================================
# 主函数
# ============================================================================

def run_backtest(config: Dict = None) -> Dict[str, Any]:
    """运行回测的便捷函数"""
    if config is None:
        config = {}
    
    engine = EnhancedBacktestEngine(
        initial_funds=config.get('initial_funds', 100000),
        start_date=config.get('start_date', '2024-01-01'),
        end_date=config.get('end_date', '2025-12-31'),
        watchlist=config.get('watchlist'),
        use_hk_costs=config.get('use_hk_costs', True)
    )
    
    return engine.run()


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='增强版港股回测引擎')
    parser.add_argument('--initial-funds', type=float, default=100000, help='初始资金')
    parser.add_argument('--start', type=str, default='2024-01-01', help='开始日期')
    parser.add_argument('--end', type=str, default='2025-12-31', help='结束日期')
    parser.add_argument('--watchlist', type=str, nargs='+', default=None, help='股票列表')
    parser.add_argument('--no-hk-costs', action='store_true', help='不使用港股精确成本')
    parser.add_argument('--output-dir', type=str, default='backtest_reports', help='输出目录')
    
    args = parser.parse_args()
    
    engine = EnhancedBacktestEngine(
        initial_funds=args.initial_funds,
        start_date=args.start,
        end_date=args.end,
        watchlist=args.watchlist,
        use_hk_costs=not args.no_hk_costs
    )
    
    results = engine.run()
    engine.generate_report(results, args.output_dir)


if __name__ == '__main__':
    main()
