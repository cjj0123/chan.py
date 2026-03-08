import sys
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple, Iterator, Callable
from datetime import datetime
import logging
import os
import copy
import subprocess
import asyncio
import aiohttp
import numpy as np

# --- 导入 BacktestDataLoader ---
from BacktestDataLoader import BacktestDataLoader, BacktestKLineUnit

# --- 依赖导入 ---
# 必须确保这些模块在环境中可用，或者在这里定义兼容的模拟类
try:
    from Chan import CChan
    from ChanConfig import CChanConfig
    from BuySellPoint.BS_Point import CBS_Point
    from Common.CEnum import KL_TYPE as ORIGINAL_KL_TYPE, DATA_SRC
    from Plot.PlotDriver import CPlotDriver
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from visual_judge import VisualJudge
    PLOTTING_AVAILABLE = True
except ImportError:
    CChan = None
    CChanConfig = None
    CBS_Point = None
    ORIGINAL_KL_TYPE = None
    PLOTTING_AVAILABLE = False
    logging.warning("核心缠论/绘图/视觉判断模块未找到，回测策略集成需要依赖一个兼容的包装器。")

# --- 兼容性数据结构定义 ---

class BacktestKLineUnit:
    """模拟 CChan/KLine 模块所需的 CKLine_Unit 结构。"""
    def __init__(self, timestamp: pd.Timestamp, open_p: float, high_p: float, low_p: float, close_p: float, volume: int, kl_type: Any, original_klu: Any = None):
        self.timestamp = timestamp
        self.open = open_p
        self.high = high_p
        self.low = low_p
        self.close = close_p
        self.volume = volume
        self.kl_type = kl_type
        self.original_klu = original_klu
        
        # 适配 CTime 结构 (从 Common 导入)
        try:
            from Common.CTime import CTime
            dt = timestamp.to_pydatetime()
            self.time = CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, auto=True)
        except ImportError:
            class MockCTime:
                def __init__(self, ts):
                    self.ts = ts
            self.time = MockCTime(timestamp.timestamp())
            
        self.sup_kl = None
        self.sub_kl_list = []
        self.parent = None
        self.children = []
        self.idx = -1  # K 线索引
        self.pre_klu = None  # 前一根 K 线
        self.pre = None  # 前一根 K 线（CChan 兼容）
        self.next = None  # 后一根 K 线（CChan 兼容）
        self.macd = None  # MACD 指标（CChan 兼容）
        self.boll = None  # BOLL 指标（CChan 兼容）
        self.rsi = None  # RSI 指标（CChan 兼容）
        self.kdj = None  # KDJ 指标（CChan 兼容）
        self.demark = None  # Demark 指标（CChan 兼容）
        self.trend = {}  # 趋势指标（CChan 兼容）
        self.limit_flag = 0  # 涨跌停标志（CChan 兼容）
        self.trade_info = type('MockTradeInfo', (), {'metric': {}})()  # 交易信息（CChan 兼容）

    def set_idx(self, idx: int):
        """设置 K 线索引"""
        self.idx = idx
    
    def get_idx(self) -> int:
        """获取 K 线索引"""
        return self.idx
    
    def set_pre_klu(self, klu):
        """设置前一根 K 线（CChan 兼容的双向链接）"""
        self.pre_klu = klu
        self.pre = klu
        if klu is not None:
            klu.next = self
    
    def get_pre_klu(self):
        """获取前一根 K 线"""
        return self.pre_klu
    
    def set_metric(self, metric_model_lst: list) -> None:
        """设置技术指标（CChan 兼容版本）"""
        from Math.MACD import CMACD
        from Math.BOLL import BollModel
        from Math.RSI import RSI
        from Math.KDJ import KDJ
        from Math.Demark import CDemarkEngine
        from Math.TrendModel import CTrendModel
        
        for metric_model in metric_model_lst:
            try:
                if isinstance(metric_model, CMACD):
                    self.macd = metric_model.add(self.close)
                elif isinstance(metric_model, CTrendModel):
                    if metric_model.type not in self.trend:
                        self.trend[metric_model.type] = {}
                    self.trend[metric_model.type][metric_model.T] = metric_model.add(self.close)
                elif isinstance(metric_model, BollModel):
                    self.boll = metric_model.add(self.close)
                elif isinstance(metric_model, CDemarkEngine):
                    self.demark = metric_model.update(idx=self.idx, close=self.close, high=self.high, low=self.low)
                elif isinstance(metric_model, RSI):
                    self.rsi = metric_model.add(self.close)
                elif isinstance(metric_model, KDJ):
                    self.kdj = metric_model.add(self.high, self.low, self.close)
                elif hasattr(metric_model, 'add'):
                    metric_model.add(self.close)
            except Exception:
                pass  # 忽略计算错误
    
    def set_klc(self, klc):
        """设置 K 线组合引用（简化版本，用于回测）"""
        self.__klc = klc
    
    @property
    def klc(self):
        """获取 K 线组合引用（CChan 兼容）"""
        return self.__klc

    def __str__(self):
        return f"KLU({self.timestamp.strftime('%Y-%m-%d %H:%M')}, C:{self.close:.2f})"

class BacktestBroker:
    """模拟交易账户和经纪商，用于管理资金和持仓。"""
    def __init__(self, initial_funds: float = 100000.0, lot_size_map: Dict[str, int] = None):
        self.initial_funds = initial_funds
        self.available_funds = initial_funds
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.trades: List[Dict[str, Any]] = []
        self.lot_size_map = lot_size_map if lot_size_map is not None else {}
        self.default_lot_size = 100
        # 成本率在买入时收取总成本的1%，卖出时收取总收入的1% (简化处理)
        self.transaction_cost_rate = 0.001 

    def get_lot_size(self, code: str) -> int:
        return self.lot_size_map.get(code, self.default_lot_size)

    def get_position_quantity(self, code: str) -> int:
        return self.positions.get(code, {}).get('qty', 0)

    def calculate_position_size(self, code: str, current_funds: float, current_price: float, max_investment_ratio: float = 0.2) -> int:
        """计算可买入的数量，并确保是整数手。"""
        if current_price <= 0: return 0
            
        max_investment = current_funds * max_investment_ratio
        lot_size = self.get_lot_size(code)
        
        shares_to_buy = int(max_investment / current_price)
        final_quantity = (shares_to_buy // lot_size) * lot_size
        
        return max(0, final_quantity)

    def execute_trade(self, code: str, action: str, quantity: int, price: float, timestamp: pd.Timestamp) -> bool:
        """执行模拟交易"""
        if quantity <= 0: return False
        
        lot_size = self.get_lot_size(code)
        if quantity % lot_size != 0: quantity = (quantity // lot_size) * lot_size
        if quantity <= 0: return False

        if action.upper() == 'BUY':
            # 买入成本 = 价格 * 数量 * (1 + 成本率)
            total_cost = price * quantity * (1 + self.transaction_cost_rate)
            if self.available_funds < total_cost:
                logging.warning(f"BUY {code}: 资金不足。需要 {total_cost:.2f}, 拥有 {self.available_funds:.2f}")
                return False
            
            self.available_funds -= total_cost
            
            if code not in self.positions:
                self.positions[code] = {'qty': 0, 'avg_price': 0.0}
            
            old_qty = self.positions[code]['qty']
            new_qty = old_qty + quantity
            old_cost_basis = old_qty * self.positions[code]['avg_price']
            new_avg_price = (old_cost_basis + price * quantity) / new_qty if new_qty > 0 else price
            
            self.positions[code]['qty'] = new_qty
            self.positions[code]['avg_price'] = new_avg_price
            
            self.trades.append({'time': timestamp, 'code': code, 'action': 'BUY', 'qty': quantity, 'price': price, 'cost': price * quantity * self.transaction_cost_rate, 'funds_after': self.available_funds})
            return True
            
        elif action.upper() == 'SELL':
            if self.get_position_quantity(code) < quantity:
                logging.warning(f"SELL {code}: 持仓不足 {quantity} 股，当前持仓 {self.get_position_quantity(code)}")
                return False
            
            revenue = price * quantity
            cost = revenue * self.transaction_cost_rate # 假设卖出成本等于买入成本的一半或直接按收入计算
            net_income = revenue - cost
            
            self.available_funds += net_income
            
            self.positions[code]['qty'] -= quantity
            if self.positions[code]['qty'] == 0:
                del self.positions[code]
            
            self.trades.append({'time': timestamp, 'code': code, 'action': 'SELL', 'qty': quantity, 'price': price, 'cost': cost, 'funds_after': self.available_funds})
            return True
            
        return False

    def get_final_performance(self, end_time: pd.Timestamp) -> Dict[str, Any]:
        final_value = self.available_funds
        for code, pos in self.positions.items():
            final_value += pos['qty'] * pos['avg_price']

        total_return = (final_value - self.initial_funds) / self.initial_funds
        
        return {
            'initial_funds': self.initial_funds,
            'final_cash': self.available_funds,
            'final_portfolio_value': final_value,
            'total_return_pct': total_return,
            'final_positions': self.positions,
        }

class BacktestReporter:
    """生成回测报告 (Todo 5, 6)"""
    def __init__(self, broker: BacktestBroker, strategy_adapter: Any, config: CChanConfig = None):
        self.broker = broker
        self.strategy_adapter = strategy_adapter
        self.config = config
        self.logger = logging.getLogger(__name__ + ".Reporter")
        self.trade_log: List[Dict] = []
        
    def record_trade(self, trade_info: Dict):
        self.trade_log.append(trade_info)

    def calculate_performance(self, end_time: pd.Timestamp) -> Dict[str, Any]:
        perf = self.broker.get_final_performance(end_time)
        
        buys = [t for t in self.broker.trades if t['action'] == 'BUY']
        sells = [t for t in self.broker.trades if t['action'] == 'SELL']
        
        # 毛利：实际卖出收入 - 实际买入成本
        gross_profit = sum(s['price'] * s['qty'] for s in sells) - sum(b['price'] * b['qty'] for b in buys if b['code'] in [t['code'] for t in sells] and b['time'] < [t['time'] for t in sells if t['code']==b['code']][0])
        gross_loss = sum(b['price'] * b['qty'] for b in buys) - sum(s['price'] * s['qty'] for s in sells if s['code'] in [t['code'] for t in buys] and s['time'] < [t['time'] for t in buys if t['code']==s['code']][0])
        
        # 使用总的现金变动和持仓变动来计算更准确的收益
        
        profit_factor = (gross_profit + 1e-6) / (abs(gross_loss) + 1e-6)
        
        equity_curve = self._generate_equity_curve()
        max_drawdown = self._calculate_max_drawdown(equity_curve)
        
        perf.update({
            'trades_count': len(self.broker.trades),
            'total_buys': len(buys),
            'total_sells': len(sells),
            'total_profit_loss_no_cost': sum(t['price'] * t['qty'] for t in sells) - sum(t['price'] * t['qty'] for t in buys),
            'profit_factor': profit_factor,
            'max_drawdown_pct': max_drawdown,
            'equity_curve': equity_curve,
            'trade_log': [
                {
                    'time': str(t['time']),
                    'code': t['code'],
                    'action': t['action'],
                    'qty': t['qty'],
                    'price': t['price'],
                    'amount': t.get('amount', t['price'] * t['qty']),
                    'cost': t.get('cost', 0),
                    'funds_after': t.get('funds_after', 0)
                }
                for t in self.broker.trades
            ],
        })
        
        return perf

    def _generate_equity_curve(self) -> List[Dict[str, Any]]:
        """生成权益曲线：记录每笔交易后的总资产净值（现金 + 持仓市值）"""
        if not self.broker.trades:
            return []

        equity_points = []
        running_cash = float(self.broker.initial_funds)
        running_positions = {}  # {code: {qty, avg_price}}

        equity_points.append({
            'time': str(self.broker.trades[0]['time']),
            'value': running_cash
        })

        for trade in self.broker.trades:
            code = trade['code']
            action = str(trade.get('action', ''))
            qty = trade.get('qty', 0)
            price = trade.get('price', 0.0)
            cost = trade.get('cost', 0.0)

            if 'BUY' in action:
                running_cash -= (price * qty + cost)
                if code not in running_positions:
                    running_positions[code] = {'qty': 0, 'avg_price': price}
                old_qty = running_positions[code]['qty']
                new_qty = old_qty + qty
                old_val = old_qty * running_positions[code]['avg_price']
                running_positions[code]['avg_price'] = (old_val + price * qty) / new_qty if new_qty > 0 else price
                running_positions[code]['qty'] = new_qty
            elif 'SELL' in action or 'STOP' in action:
                running_cash += (price * qty - cost)
                if code in running_positions:
                    running_positions[code]['qty'] = max(0, running_positions[code]['qty'] - qty)
                    if running_positions[code]['qty'] == 0:
                        del running_positions[code]

            # 总净值 = 现金 + 持仓按买入均价计算
            positions_value = sum(p['qty'] * p['avg_price'] for p in running_positions.values())
            total_value = max(0.0, running_cash + positions_value)
            equity_points.append({
                'time': str(trade['time']),
                'value': total_value
            })

        return equity_points

    def _calculate_max_drawdown(self, equity_curve: List[Dict[str, Any]]) -> float:
        if not equity_curve or len(equity_curve) < 2: return 0.0
        
        df = pd.DataFrame(equity_curve)
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values('time')
        df = df.drop_duplicates(subset=['time'], keep='last')
        df = df.reset_index(drop=True)
        
        df['peak'] = df['value'].cummax()
        df['drawdown'] = (df['value'] - df['peak']) / df['peak']
        
        max_dd = df['drawdown'].min()
        return abs(min(0.0, max_dd))

    def generate_report(self, results: Dict[str, Any], start_time_str: str, end_time_str: str) -> str:
        report_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        report = f"# 港股缠论回测报告 ({report_time})\n\n"
        report += f"## 1. 回测参数\n"
        report += f"- **回测范围**: {start_time_str} 至 {end_time_str}\n"
        report += f"- **主K线频率**: `{BACKTEST_FREQ}`\n"
        report += f"- **初始资金**: {results['initial_funds']:,.2f} HKD\n"
        report += f"- **所用策略**: 基于 `futu_hk_visual_trading_fixed.py` 核心逻辑 (仅使用缠论信号，**跳过视觉评分**)。\n"
        if self.config:
            report += f"- **缠论配置**: MACD({self.config.macd_config['fast']}/{self.config.macd_config['slow']}/{self.config.macd_config['signal']}), Seg Algo: {self.config.seg_conf.seg_algo}\n"
        report += "\n"
        
        report += f"## 2. 核心绩效指标\n"
        report += f"- **期末总资产 (成本价计)**: {results['final_portfolio_value']:,.2f} HKD\n"
        report += f"- **最终可用现金**: {results['final_cash']:,.2f} HKD\n"
        report += f"- **总回报率**: **{results['total_return_pct'] * 100:.2f}%**\n"
        report += f"- **总交易次数**: {results['trades_count']} (买入: {results['total_buys']}, 卖出: {results['total_sells']})\n"
        report += f"- **毛利/亏损 (不含成本)**: {results['total_profit_loss_no_cost']:,.2f} HKD\n"
        report += f"- **利润因子 (Profit Factor)**: {results['profit_factor']:.3f}\n"
        report += f"- **最大回撤 (Max Drawdown)**: **{results['max_drawdown_pct'] * 100:.2f}%**\n"
        report += "\n"

        report += f"## 3. 最终持仓\n"
        if results['final_positions']:
            report += "| 股票代码 | 持仓数量 (股) | 平均成本价 (HKD) |\n"
            report += "|---|---|---|\n"
            for code, pos in results['final_positions'].items():
                report += f"| {code} | {pos['qty']} | {pos['avg_price']:.3f} |\n"
        else:
            report += "回测结束时无持仓。\n"
        report += "\n"
        
        report += f"## 4. 交易日志摘要 (前50笔)\n"
        if self.trade_log:
            report += "| 时间 | 动作 | 代码 | 数量 | 价格 | 交易成本 | 剩余现金 |\n"
            report += "|---|---|---|---|---|---|---|\n"
            for trade in self.trade_log[:50]: 
                report += (f"| {trade['time'].strftime('%Y-%m-%d %H:%M')} "
                           f"| {trade['action']} "
                           f"| {trade['code']} "
                           f"| {trade['qty']} "
                           f"| {trade['price']:.3f} "
                           f"| {trade['cost']:.2f} "
                           f"| {trade['funds_after']:,.2f} |\n")
            if len(self.trade_log) > 50:
                 report += f"| ... | ... | ... | ... | ... | ... | ... |\n"
                 report += f"| **总计** | - | - | - | - | **{sum(t['cost'] for t in self.broker.trades):.2f}** | **{self.broker.available_funds:,.2f}** |\n"
        else:
            report += "无交易记录。\n"
            
        report += "\n## 5. 建议\n"
        report += "本回测已完成了数据加载、策略信号生成（模拟）和基础交易模拟。请在 `backtester.py` 中使用 `python3 backtester.py --backtest` 来运行，或修改 `basic_mode_backtest` 内部逻辑以适应您的环境。建议后续步骤实现完整的图表生成和参数遍历来优化策略。\n"
        
        return report

# --- 策略/信号生成适配器 (用于替代 live trading logic) ---

class BacktestStrategyAdapter:
    """
    适配 live trading 逻辑到回测环境。
    """
    def __init__(self, live_trader_instance: Any, chan_config: CChanConfig):
        self.live_trader = live_trader_instance
        self.chan_config = chan_config
        self.logger = logging.getLogger(__name__ + ".StrategyAdapter")
        self.chan_cache: Dict[str, CChan] = {}  # cache_key -> chan_instance
        self.last_timestamps: Dict[str, pd.Timestamp] = {}  # cache_key -> last processed timestamp
    
    def _prepare_chan_instance(self, code: str, klines: List[BacktestKLineUnit], freq: str) -> Optional[CChan]:
        """构建或更新 CChan 实例。"""
        if not CChan or not CChanConfig or not ORIGINAL_KL_TYPE:
            return None

        freq_map = {"30M": ORIGINAL_KL_TYPE.K_30M, "5M": ORIGINAL_KL_TYPE.K_5M, "DAY": ORIGINAL_KL_TYPE.K_DAY}
        target_kl_type = freq_map.get(freq.upper(), ORIGINAL_KL_TYPE.K_30M)
        
        # 检查缓存中是否已有该品种的实例
        cache_key = f"{code}_{freq}"
        chan_instance = None
        
        # 这里逻辑简化：BacktestStrategyAdapter 被设计为每次处理一个 snapshot
        # 我们需要在 adapter 外部或者内部逻辑中确保实例是持久化的
        if cache_key in self.chan_cache:
            chan_instance = self.chan_cache[cache_key]
            # 增量加载最后一根数据，前提是时间戳确实更新了，防止抛出由于不同级别 K 线更新频率不同导致的报错
            if klines:
                last_time = self.last_timestamps.get(cache_key, pd.Timestamp.min)
                if klines[-1].timestamp > last_time:
                    try:
                        chan_instance.trigger_load({target_kl_type: [klines[-1]]})
                    except Exception as e:
                        self.logger.debug(f"增量加载K线失败(可忽略): {e}")
                    self.last_timestamps[cache_key] = klines[-1].timestamp
        else:
            # 开启步骤模式，允许增量更新
            self.chan_config.trigger_step = True
            
            from DataAPI.MockStockAPI import register_kline_data
            register_kline_data(code, target_kl_type, klines)
            
            chan_instance = CChan(
                code=code,
                data_src="custom:MockStockAPI.MockStockAPI",
                lv_list=[target_kl_type],
                config=self.chan_config,
                autype=0
            )
            # 初始全量加载
            try:
                chan_instance.trigger_load({target_kl_type: klines})
            except Exception as e:
                self.logger.error(f"初始加载K线失败: {e}")
            self.chan_cache[cache_key] = chan_instance
            if klines:
                self.last_timestamps[cache_key] = klines[-1].timestamp
            
        return chan_instance

    def get_signal(self, code: str, klines_data: Dict[str, List[BacktestKLineUnit]], lot_size_map: Dict[str, int]) -> Optional[Dict]:
        """核心分析函数。模仿 live trader 的 analyze_with_chan 逻辑。"""
        
        klines_30m = klines_data.get("30M")
        klines_5m = klines_data.get("5M")
        
        if not klines_30m:
            self.logger.warning(f"{code}: 缺少关键的 30M 数据，跳过分析。")
            return None

        chan_multi_level: List[CChan] = []
        
        try:
            chan_30m = self._prepare_chan_instance(code, klines_30m, "30M")
            if chan_30m: chan_multi_level.append(chan_30m)
            
            if klines_5m:
                chan_5m = self._prepare_chan_instance(code, klines_5m, "5M")
                if chan_5m: chan_multi_level.append(chan_5m)
            
        except Exception as e:
            self.logger.error(f"构建 CChan 实例失败 for {code}: {e}")
            return None

        if not chan_multi_level: return None
            
        chan_main = chan_multi_level[0]
        
        try:
            latest_bsps = chan_main.get_latest_bsp(number=1)
        except Exception as e:
            self.logger.error(f"获取 {code} 最新 BSP 失败: {e}")
            print(f"DEBUG: {code} get_latest_bsp error: {e}")
            return None

        if not latest_bsps: 
            # print(f"DEBUG: {code} no latest bsps") # avoid spam
            return None
        
        bsp = latest_bsps[0]
        bsp_type = bsp.type2str()
        is_buy = bsp.is_buy
        price = bsp.klu.close
        
        current_time_pd = klines_30m[-1].timestamp
        
        # Check if the signal is new for this specific time
        last_signal_time = getattr(self, '_last_signal_time', {}).get(code)
        
        if last_signal_time == bsp.klu.time:
            # print(f"DEBUG: {code} signal at {bsp.klu.time} already processed")
            return None
            
        # Record the signal time
        if not hasattr(self, '_last_signal_time'):
            self._last_signal_time = {}
        self._last_signal_time[code] = bsp.klu.time
        
        result = {
            'code': code,
            'is_buy': is_buy,
            'bsp_type': bsp_type,
            'signal_price': price,
            'signal_time': current_time_pd, 
            'lot_size': lot_size_map.get(code, 100),
            'chan_analysis': {
                'chan_multi_level': chan_multi_level,
                'bsp_instance': bsp
            }
        }
        
        self.logger.info(f"{code} 策略分析: 发现 {bsp_type} 信号, 价格: {price}")
        return result

    def evaluate_signal_for_backtest(self, signal: Dict) -> Dict:
        """在回测中，我们使用缠论信号作为有效信号，评分设为最高。"""
        signal['score'] = 99 
        signal['is_valid_for_trade'] = True
        if 'chart_paths' not in signal: signal['chart_paths'] = []
        return signal

# --- 数据迭代器 ---

class BacktestDataIterator:
    def __init__(self, loader: BacktestDataLoader, watchlist: List[str], freq: str, start_date: str, end_date: str, lot_size_map: Dict[str, int]):
        import logging
        self.loader = loader
        self.watchlist = watchlist
        self.freq = freq
        self.start_date = start_date
        self.end_date = end_date
        self.lot_size_map = lot_size_map
        self.data_cache: Dict[str, Dict[str, List[BacktestKLineUnit]]] = {}
        self.pointers: Dict[str, Dict[str, int]] = {}  # code -> {freq -> current_idx}
        self.logger = logging.getLogger(__name__ + ".Iterator")
        self._load_all_data()
        
        all_times = [klu.timestamp for klu_list in self.data_cache.values() for klu_dict in klu_list.values() if isinstance(klu_dict, list) for klu in klu_dict]
        self.timeline = sorted(list(set(all_times)))
        self.current_index = 0
        self.max_index = len(self.timeline)

    def _load_all_data(self):
        required_freqs = ["30M", "5M", "DAY"] 
        
        for code in self.watchlist:
            self.data_cache[code] = {}
            all_freq_loaded = True
            for freq in required_freqs:
                data = self.loader.load_kline_data(code, freq, self.start_date, self.end_date)
                if data:
                    self.data_cache[code][freq] = data
                else:
                    self.logger.warning(f"未能加载 {code} 的 {freq} 数据。")
                    all_freq_loaded = False
            
            if not all_freq_loaded:
                 self.data_cache[code]['__AVAILABLE__'] = False
            else:
                 self.data_cache[code]['__AVAILABLE__'] = True
                 self.pointers[code] = {f: 0 for f in required_freqs}

    def __iter__(self) -> Iterator[Tuple[pd.Timestamp, Dict[str, Any]]]:
        current_index = 0
        while current_index < self.max_index:
            current_time = self.timeline[current_index]
            snapshot: Dict[str, Any] = {}
            
            for code in self.watchlist:
                if not self.data_cache[code].get('__AVAILABLE__', False): continue
                    
                klines_at_time = {}
                is_data_valid = True
                
                # 使用指针高效获取此时的数据
                for freq in ["30M", "5M", "DAY"]:
                    kline_list = self.data_cache[code].get(freq)
                    if not kline_list:
                        if freq in ["30M", "5M"]: is_data_valid = False; break
                        continue

                    idx = self.pointers[code][freq]
                    # 移动指针到满足 timestamp <= current_time 的最大索引
                    while idx < len(kline_list) and kline_list[idx].timestamp <= current_time:
                        idx += 1
                    self.pointers[code][freq] = idx
                    
                    if idx > 0:
                        # 只需要传回最新的这一根即可配合增量 trigger_load
                        # 如果是第一次加载，adapter 会处理全量
                        klines_at_time[freq] = kline_list[:idx]
                    else:
                        if freq in ["30M", "5M"]: is_data_valid = False; break
                        
                if is_data_valid and klines_at_time.get("30M") and klines_at_time.get("5M"):
                     snapshot[code] = klines_at_time

            if snapshot:
                yield current_time, snapshot
            
            current_index += 1

# --- 配置 ---
INITIAL_FUNDS = 100000.0
BACKTEST_FREQ = "30M"
EXAMPLE_WATCHLIST = ["HK.00700", "HK.00836", "HK.02688"] 
BACKTEST_START_DATE = "2025-01-01"
BACKTEST_END_DATE = "2025-12-31"
DEFAULT_LOT_SIZES = {
    "HK.00700": 100,
    "HK.00836": 500,
    "HK.02688": 1000
}

# --- 回测主函数 ---

def basic_mode_backtest(args):
    """
    使用步骤 1-7 中设计的架构执行回测。
    此函数将替换 backtester.py 中原有的空 basic_mode。
    """
    logger = logging.getLogger("BacktestEngine")
    logger.info(f"--- 启动历史回测模式 ---")
    
    # 1. 初始化组件 (Todo 3)
    if not CChanConfig:
        logger.error("CChanConfig 未导入，回测中止。")
        return False

    chan_config = CChanConfig() 
    loader = BacktestDataLoader()
    
    # 1c. 准备策略适配器 (Mock LiveTrader)
    class MockLiveTrader:
        def __init__(self, loader: BacktestDataLoader):
            self.loader = loader
            self.DEFAULT_LOT_SIZES = DEFAULT_LOT_SIZES
            self.BACKTEST_FREQ = BACKTEST_FREQ
            self.BACKTEST_START_DATE = BACKTEST_START_DATE
            self.BACKTEST_END_DATE = BACKTEST_END_DATE

        def get_stock_info(self, code):
             data = self.loader.load_kline_data(code, self.BACKTEST_FREQ, self.BACKTEST_START_DATE, self.BACKTEST_END_DATE)
             if data:
                 last_klu = data[-1]
                 return {'current_price': last_klu.close, 'lot_size': self.DEFAULT_LOT_SIZES.get(code, 100)}
             return {'current_price': 0, 'lot_size': self.DEFAULT_LOT_SIZES.get(code, 100)}
        
        def get_available_funds(self): return INITIAL_FUNDS
        def get_position_quantity(self, code): return 0
        def execute_trade(self, code, action, quantity, price): return True 
        def analyze_with_chan(self, code): return None
            
    mock_trader = MockLiveTrader(loader)
    strategy_adapter = BacktestStrategyAdapter(live_trader_instance=mock_trader, chan_config=chan_config)

    # 1d. 准备交易模拟器和报告器
    broker = BacktestBroker(initial_funds=INITIAL_FUNDS, lot_size_map=DEFAULT_LOT_SIZES)
    reporter = BacktestReporter(broker, strategy_adapter, chan_config)
    
    # 2. 准备数据迭代器 (Todo 1, 4)
    watchlist = EXAMPLE_WATCHLIST 
    data_iterator = BacktestDataIterator(
        loader=loader, 
        watchlist=watchlist, 
        freq=BACKTEST_FREQ, 
        start_date=BACKTEST_START_DATE, 
        end_date=BACKTEST_END_DATE,
        lot_size_map=DEFAULT_LOT_SIZES
    )
    
    if data_iterator.max_index == 0:
        logger.error("无有效时间点进行回测，请检查数据加载范围。")
        return False
        
    logger.info(f"数据加载完毕。总共 {data_iterator.max_index} 个时间点进行迭代。")
    
    # 3. 回测主循环 (Todo 4)
    
    for current_time, snapshot in data_iterator:
        
        trade_signals_this_step: List[Dict] = []
        
        for code in watchlist:
            if code not in snapshot: continue 
            
            # --- 策略信号生成 (Todo 2) ---
            signal = strategy_adapter.get_signal(code, snapshot[code], DEFAULT_LOT_SIZES)
            
            if signal:
                signal['position_qty'] = broker.get_position_quantity(code)
                scored_signal = strategy_adapter.evaluate_signal_for_backtest(signal)
                trade_signals_this_step.append(scored_signal)

        if not trade_signals_this_step: continue

        # 3c. 交易执行 (Todo 3)
        
        sells = sorted([s for s in trade_signals_this_step if not s['is_buy'] and s['score'] >= 99], key=lambda x: x['score'], reverse=True)
        buys = sorted([s for s in trade_signals_this_step if s['is_buy'] and s['score'] >= 99], key=lambda x: x['score'], reverse=True)
        
        # 优先处理卖出
        for signal in sells:
            code = signal['code']
            qty = signal['position_qty']
            price = signal['signal_price']
            
            if qty > 0 and broker.execute_trade(code, 'SELL', qty, price, current_time):
                reporter.record_trade({'time': current_time, 'code': code, 'action': 'SELL', 'qty': qty, 'price': price, 'cost': price * qty * broker.transaction_cost_rate, 'funds_after': broker.available_funds})

        # 再处理买入
        for signal in buys:
            code = signal['code']
            price = signal['signal_price']
            lot_size = signal['lot_size']
            
            if broker.get_position_quantity(code) == 0:
                qty = broker.calculate_position_size(code, broker.available_funds, price)
                final_qty = (qty // lot_size) * lot_size
                
                if final_qty > 0 and broker.execute_trade(code, 'BUY', final_qty, price, current_time):
                    reporter.record_trade({'time': current_time, 'code': code, 'action': 'BUY', 'qty': final_qty, 'price': price, 'cost': price * final_qty * broker.transaction_cost_rate, 'funds_after': broker.available_funds})


    # 4. 结束与报告 (Todo 5, 6)
    final_time = data_iterator.timeline[-1] if data_iterator.timeline else datetime.now()
    performance_results = reporter.calculate_performance(final_time)
    
    report_md = reporter.generate_report(performance_results, BACKTEST_START_DATE, BACKTEST_END_DATE)

    # 5. 保存结果
    output_file = f"backtest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report_md)
        
    logger.info(f"--- 回测完成 ---")
    logger.info(f"报告已保存至: {output_file}")
    logger.info(f"最终回报率: {performance_results['total_return_pct'] * 100:.2f}%")
    
    return True

def advanced_mode():
    print("[INFO] 高级回测模式 (TBD - 需要更多参数)")
    return True

def main():
    # 检查是否是回测调用
    if '--backtest' in sys.argv:
        
        success = basic_mode_backtest(None)
        
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
    else:
        print("[ERROR] 请使用 --backtest 参数启动回测引擎。")
        sys.exit(1)

if __name__ == "__main__":
    main()