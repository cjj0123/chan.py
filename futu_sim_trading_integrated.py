import sys
import os
import numpy as np
import pandas as pd
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import time
import random

sys.path.insert(0, '/Users/jijunchen/.openclaw/workspace/chan.py')

from futu import *
from visual_judge import VisualJudge

# 定义周期常量
class Period:
    K_1M = KLType.K_1M
    K_5M = KLType.K_5M
    K_15M = KLType.K_15M
    K_30M = KLType.K_30M
    K_60M = KLType.K_60M
    K_DAY = KLType.K_DAY

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/Users/jijunchen/.openclaw/workspace/chan.py/trading.log'),
        logging.StreamHandler()
    ]
)

class ChanTheoryTrader:
    def __init__(self, api_svr_ip='127.0.0.1', api_svr_port=11111):
        self.quote_ctx = OpenQuoteContext(api_svr_ip, api_svr_port)
        self.trd_ctx = OpenHKTradeContext(api_svr_ip, api_svr_port)
        self.position_cache = {}
        self.order_cache = {}
        
        # 缓存用于缠论分析的数据结构
        self.kline_cache = {}
        self.last_signal_time = {}
        
        # 初始化交易账户信息
        self.account_info = self.get_account_info()
        logging.info(f"账户信息: {self.account_info}")

    def get_account_info(self):
        """获取账户信息"""
        try:
            accinfo = self.trd_ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)
            if accinfo[0] == RET_OK:
                return accinfo[1].iloc[0]
            else:
                logging.error(f"获取账户信息失败: {accinfo[1]}")
                return None
        except Exception as e:
            logging.error(f"获取账户信息异常: {e}")
            return None

    def get_market_data(self, symbol: str, period: str, num_klines: int = 100) -> Dict[str, Any]:
        """获取市场数据并进行基本技术指标计算"""
        try:
            from futu import SubType, AuType
            
            # 先订阅
            sub_ret, sub_msg = self.quote_ctx.subscribe(
                [symbol], 
                [SubType.K_30M if period == 'K_30M' else SubType.K_60M],
                subscribe_push=False
            )
            if sub_ret != RET_OK:
                logging.warning(f"订阅失败: {sub_msg}")
            
            # 获取K线数据
            ret_code, ret_data = self.quote_ctx.get_cur_kline(
                symbol, 
                num_klines, 
                period, 
                AuType.QFQ
            )
            
            if ret_code != RET_OK:
                logging.error(f"获取K线数据失败: {ret_data}")
                return {}

            df = ret_data
            if df.empty or len(df) < 20:
                logging.warning(f"K线数据不足: {len(df)} 条记录")
                return {}

            # 计算基本技术指标
            df['MA5'] = df['close'].rolling(window=5).mean()
            df['MA10'] = df['close'].rolling(window=10).mean()
            df['MA20'] = df['close'].rolling(window=20).mean()
            df['MA60'] = df['close'].rolling(window=60).mean()

            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))

            # MACD
            exp12 = df['close'].ewm(span=12).mean()
            exp26 = df['close'].ewm(span=26).mean()
            df['MACD'] = exp12 - exp26
            df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
            df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

            # 计算波动率
            df['volatility'] = df['close'].rolling(window=20).std()

            return {
                'open': df['open'].tolist(),
                'high': df['high'].tolist(),
                'low': df['low'].tolist(),
                'close': df['close'].tolist(),
                'volume': df['volume'].tolist(),
                'ma5': df['MA5'].tolist(),
                'ma10': df['MA10'].tolist(),
                'ma20': df['MA20'].tolist(),
                'rsi': df['RSI'].tolist(),
                'macd': df['MACD'].tolist(),
                'macd_signal': df['MACD_Signal'].tolist(),
                'macd_hist': df['MACD_Hist'].tolist(),
                'volatility': df['volatility'].tolist(),
                'timestamp': df['time_key'].tolist(),
                'df': df  # 保留原始DataFrame以供进一步分析
            }
        except Exception as e:
            logging.error(f"获取市场数据异常: {e}")
            return {}

    def identify_zigzag(self, prices: List[float], deviation: float = 0.03) -> List[Tuple[int, float]]:
        """识别锯齿形态 - 缠论中的分型识别"""
        if len(prices) < 3:
            return []

        peaks_valleys = []
        direction = 0  # 0: unknown, 1: up, -1: down

        for i in range(1, len(prices) - 1):
            current = prices[i]
            prev = prices[i - 1]
            next_price = prices[i + 1]

            # 检查是否为顶分型 (当前点比两边都高)
            if current > prev and current > next_price:
                if direction == -1:  # 从下降转为上升
                    peaks_valleys.append((i, current))
                    direction = 1
                elif direction == 0:  # 初始状态
                    peaks_valleys.append((i, current))
                    direction = 1

            # 检查是否为底分型 (当前点比两边都低)
            elif current < prev and current < next_price:
                if direction == 1:  # 从上升转为下降
                    peaks_valleys.append((i, current))
                    direction = -1
                elif direction == 0:  # 初始状态
                    peaks_valleys.append((i, current))
                    direction = -1

        # 过滤掉波动太小的分型
        filtered_pvs = [peaks_valleys[0]] if peaks_valleys else []
        for i in range(1, len(peaks_valleys)):
            prev_idx, prev_price = filtered_pvs[-1]
            curr_idx, curr_price = peaks_valleys[i]
            
            # 计算价格变化百分比
            if prev_price != 0:
                change_pct = abs(curr_price - prev_price) / prev_price
                if change_pct >= deviation:
                    filtered_pvs.append((curr_idx, curr_price))

        return filtered_pvs

    def check_macd_divergence(self, prices: List[float], macd_values: List[float]) -> bool:
        """检查MACD背离"""
        if len(prices) < 50 or len(macd_values) < 50:
            return False

        recent_prices = prices[-20:]
        recent_macd = macd_values[-20:]

        # 简单的背离检测：价格创新高但MACD没创新高，或价格创新低但MACD没创新低
        price_high = max(recent_prices)
        macd_high = max(recent_macd)
        
        # 检查顶背离
        if len(prices) >= 40:
            prev_prices = prices[-40:-20]
            prev_macd = macd_values[-40:-20]
            if prev_prices and prev_macd:
                prev_price_high = max(prev_prices)
                prev_macd_high = max(prev_macd)
                
                if price_high > prev_price_high and macd_high < prev_macd_high:
                    return True  # 顶背离

        # 检查底背离
        price_low = min(recent_prices)
        macd_low = min(recent_macd)
        
        if len(prices) >= 40:
            prev_prices = prices[-40:-20]
            prev_macd = macd_values[-40:-20]
            if prev_prices and prev_macd:
                prev_price_low = min(prev_prices)
                prev_macd_low = min(prev_macd)
                
                if price_low < prev_price_low and macd_low > prev_macd_low:
                    return True  # 底背离

        return False

    def calculate_chan_segments(self, zigzag_points: List[Tuple[int, float]]) -> List[Dict]:
        """计算缠论线段"""
        if len(zigzag_points) < 3:
            return []

        segments = []
        for i in range(len(zigzag_points) - 2):
            start_idx, start_price = zigzag_points[i]
            mid_idx, mid_price = zigzag_points[i + 1]
            end_idx, end_price = zigzag_points[i + 2]

            segment = {
                'start_idx': start_idx,
                'end_idx': end_idx,
                'start_price': start_price,
                'end_price': end_price,
                'direction': 1 if end_price > start_price else -1,
                'length': end_idx - start_idx,
                'magnitude': abs(end_price - start_price)
            }
            segments.append(segment)

        return segments

    def detect_chan_signals(self, symbol: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """检测缠论买卖信号"""
        signals = {
            'buy': False,
            'sell': False,
            'confidence': 0.0,
            'details': []
        }

        if not market_data or len(market_data['close']) < 20:
            return signals

        closes = market_data['close']
        rsi_values = market_data.get('rsi', [])
        macd_values = market_data.get('macd', [])
        macd_signal_values = market_data.get('macd_signal', [])

        # 识别锯齿形态（分型）
        zigzag_points = self.identify_zigzag(closes, deviation=0.02)

        # 计算线段
        segments = self.calculate_chan_segments(zigzag_points)

        # 检查MACD背离
        has_bearish_divergence = self.check_macd_divergence(closes, macd_values)
        has_bullish_divergence = self.check_macd_divergence([-p for p in closes], [-m for m in macd_values])

        # 买入信号条件
        buy_conditions = []
        sell_conditions = []

        # 条件1: RSI超卖后回升
        if len(rsi_values) >= 3 and rsi_values[-1] > rsi_values[-2] > rsi_values[-3] and rsi_values[-3] < 30:
            buy_conditions.append("RSI超卖反弹")
        
        # 条件2: MACD金叉
        if len(macd_values) >= 2 and macd_values[-2] < macd_signal_values[-2] and macd_values[-1] > macd_signal_values[-1]:
            buy_conditions.append("MACD金叉")

        # 条件3: 形成底部分型
        if len(zigzag_points) >= 3:
            last_valley = zigzag_points[-1]
            second_last_peak = zigzag_points[-2] if len(zigzag_points) >= 2 else None
            third_last_valley = zigzag_points[-3] if len(zigzag_points) >= 3 else None
            
            if last_valley[1] > (third_last_valley[1] if third_last_valley else 0) and second_last_peak:
                buy_conditions.append("底部分型确认")

        # 条件4: 线段底部反转
        if len(segments) >= 2 and segments[-1]['direction'] == 1 and segments[-2]['direction'] == -1:
            if segments[-1]['start_price'] > segments[-2]['end_price']:
                buy_conditions.append("线段底部反转")

        # 条件5: 牛市背离
        if has_bullish_divergence:
            buy_conditions.append("MACD牛市背离")

        # 卖出信号条件
        # 条件1: RSI超买后回落
        if len(rsi_values) >= 3 and rsi_values[-1] < rsi_values[-2] < rsi_values[-3] and rsi_values[-3] > 70:
            sell_conditions.append("RSI超买回调")

        # 条件2: MACD死叉
        if len(macd_values) >= 2 and macd_values[-2] > macd_signal_values[-2] and macd_values[-1] < macd_signal_values[-1]:
            sell_conditions.append("MACD死叉")

        # 条件3: 形成顶部分型
        if len(zigzag_points) >= 3:
            last_peak = zigzag_points[-1]
            second_last_valley = zigzag_points[-2] if len(zigzag_points) >= 2 else None
            third_last_peak = zigzag_points[-3] if len(zigzag_points) >= 3 else None
            
            if last_peak[1] < (third_last_peak[1] if third_last_peak else float('inf')) and second_last_valley:
                sell_conditions.append("顶部分型确认")

        # 条件4: 线段顶部反转
        if len(segments) >= 2 and segments[-1]['direction'] == -1 and segments[-2]['direction'] == 1:
            if segments[-1]['start_price'] < segments[-2]['end_price']:
                sell_conditions.append("线段顶部反转")

        # 条件5: 熊市背离
        if has_bearish_divergence:
            sell_conditions.append("MACD熊市背离")

        # 综合判断
        if len(buy_conditions) >= 2:
            signals['buy'] = True
            signals['confidence'] = min(0.9, 0.5 + len(buy_conditions) * 0.1)
            signals['details'].extend(buy_conditions)
        elif len(sell_conditions) >= 2:
            signals['sell'] = True
            signals['confidence'] = min(0.9, 0.5 + len(sell_conditions) * 0.1)
            signals['details'].extend(sell_conditions)

        return signals

    def get_visual_score(self, symbol: str, market_data: Dict[str, Any], signal_time: datetime = None) -> float:
        """
        获取视觉评分（优先级：Gemini API > 本地降级）
        """
        try:
            # 尝试使用 Gemini API 进行视觉评分
            chart_paths = self._get_chart_paths(symbol, signal_time)
            if chart_paths:
                judge = VisualJudge(use_mock=False)
                result = judge.evaluate(chart_paths)
                if result and 'score' in result:
                    score = result['score'] / 100.0  # 转换为 0-1 范围
                    logging.info(f"💎 Gemini 评分：{symbol} - {score:.2f} | {result.get('action', 'N/A')} | {result.get('analysis', '')}")
                    return score

            # 降级到本地算法
            return self._get_local_visual_score(market_data)
        except Exception as e:
            logging.error(f"视觉评分失败：{str(e)}")
            return self._get_local_visual_score(market_data)

    def _get_chart_paths(self, symbol: str, signal_time: datetime = None) -> list:
        """获取图表路径"""
        if signal_time is None:
            signal_time = datetime.now()

        date_str = signal_time.strftime('%Y%m%d')
        symbol_file = symbol.replace('.', '_')

        # 正确的图表路径
        chart_dir = "/Users/jijunchen/.openclaw/workspace/chan.py/charts_hk_scan"

        chart_30m = None
        chart_5m = None

        import os
        if os.path.exists(chart_dir):
            for file in os.listdir(chart_dir):
                if date_str in file and symbol_file in file:
                    if "30M" in file:
                        chart_30m = os.path.join(chart_dir, file)
                    elif "5M" in file:
                        chart_5m = os.path.join(chart_dir, file)

        paths = []
        if chart_30m:
            paths.append(chart_30m)
        if chart_5m:
            paths.append(chart_5m)

        return paths if paths else None

    def _get_local_visual_score(self, market_data: Dict[str, Any]) -> float:
        """本地降级算法"""
        try:
            close_prices = market_data['close']
            if len(close_prices) < 2:
                return 0.5

            trend = (close_prices[-1] - close_prices[0]) / close_prices[0]
            volatility = np.std(np.diff(close_prices)) / np.mean(close_prices)

            score = max(0, min(1, 0.8 * (volatility * 10) + 0.2 * (1 if trend < 0 else 0)))
            logging.info(f"⚠️  本地评分：{score:.2f}")
            return score
        except Exception as e:
            logging.error(f"本地评分失败：{str(e)}")
            return 0.5

    def should_buy(self, symbol: str) -> Tuple[bool, Dict[str, Any]]:
        """决定是否买入"""
        # 获取30分钟K线数据
        kline_data = self.get_market_data(symbol, KLType.K_30M, num_klines=100)
        if not kline_data:
            logging.warning(f"无法获取 {symbol} 的K线数据")
            return False, {}

        # 检测缠论信号
        chan_signals = self.detect_chan_signals(symbol, kline_data)

        if not chan_signals['buy']:
            return False, {}

        # 获取视觉评分
        visual_score = self.get_visual_score(symbol, kline_data, datetime.now())

        # 综合判断
        final_score = (
            chan_signals['confidence'] * 0.7 +
            visual_score * 0.3
        )

        # 设置买入阈值
        buy_threshold = 0.6

        if final_score >= buy_threshold:
            # 获取实时价格
            ret, data = self.quote_ctx.get_stock_quote([symbol])
            if ret == RET_OK and not data.empty:
                current_price = data.iloc[0]['last_price']
                position_value = self.get_position_value(symbol)
                
                # 计算购买数量（使用账户总资产的一定比例）
                total_assets = self.account_info['total_assets'] if self.account_info else 100000
                allocation = min(0.1, 0.05 + visual_score * 0.05)  # 根据视觉评分调整仓位
                amount_to_invest = total_assets * allocation
                
                quantity = int(amount_to_invest / current_price)
                
                # 确保最小交易单位
                lot_size = data.iloc[0]['lot_size']
                quantity = max(quantity // lot_size * lot_size, lot_size)

                trade_details = {
                    'symbol': symbol,
                    'price': current_price,
                    'quantity': quantity,
                    'chan_confidence': chan_signals['confidence'],
                    'visual_score': visual_score,
                    'final_score': final_score,
                    'reasons': chan_signals['details']
                }

                logging.info(f"📈 买入信号: {symbol}, 价格: {current_price}, 数量: {quantity}")
                logging.info(f"   缠论置信度: {chan_signals['confidence']:.2f}, 视觉评分: {visual_score:.2f}")
                logging.info(f"   最终得分: {final_score:.2f}, 原因: {chan_signals['details']}")

                return True, trade_details

        return False, {}

    def should_sell(self, symbol: str) -> Tuple[bool, Dict[str, Any]]:
        """决定是否卖出"""
        # 获取持仓信息
        position_qty = self.get_position_quantity(symbol)
        if position_qty <= 0:
            return False, {}

        # 获取30分钟K线数据
        kline_data = self.get_market_data(symbol, KLType.K_30M, num_klines=100)
        if not kline_data:
            return False, {}

        # 检测缠论卖出信号
        chan_signals = self.detect_chan_signals(symbol, kline_data)

        if not chan_signals['sell']:
            return False, {}

        # 获取实时价格
        ret, data = self.quote_ctx.get_stock_quote([symbol])
        if ret == RET_OK and not data.empty:
            current_price = data.iloc[0]['last_price']
            avg_cost = self.get_average_cost(symbol)
            
            # 计算盈亏
            profit_loss_rate = (current_price - avg_cost) / avg_cost if avg_cost > 0 else 0

            # 综合考虑缠论信号和盈利情况
            sell_signal_strength = chan_signals['confidence']
            
            # 设置卖出条件
            should_sell = (
                sell_signal_strength >= 0.6 or  # 强烈卖出信号
                (sell_signal_strength >= 0.4 and profit_loss_rate >= 0.03) or  # 一般信号但盈利超过3%
                profit_loss_rate <= -0.08  # 止损条件
            )

            if should_sell:
                trade_details = {
                    'symbol': symbol,
                    'price': current_price,
                    'quantity': position_qty,
                    'avg_cost': avg_cost,
                    'profit_loss_rate': profit_loss_rate,
                    'chan_confidence': chan_signals['confidence'],
                    'reasons': chan_signals['details']
                }

                logging.info(f"📉 卖出信号: {symbol}, 价格: {current_price}, 数量: {position_qty}")
                logging.info(f"   平均成本: {avg_cost:.2f}, 盈亏率: {profit_loss_rate:.2%}")
                logging.info(f"   缠论置信度: {chan_signals['confidence']:.2f}, 原因: {chan_signals['details']}")

                return True, trade_details

        return False, {}

    def place_order(self, symbol: str, order_type: OrderType, price: float, qty: int) -> bool:
        """下单"""
        try:
            ret, data = self.trd_ctx.place_order(
                order_type=order_type,
                code=symbol,
                qty=qty,
                price=price,
                trd_env=TrdEnv.SIMULATE
            )
            
            if ret == RET_OK:
                order_id = data.iloc[0]['order_id']
                logging.info(f"✅ 订单已提交: {symbol}, ID: {order_id}, 类型: {order_type.name}, 价格: {price}, 数量: {qty}")
                return True
            else:
                logging.error(f"❌ 下单失败: {data}")
                return False
        except Exception as e:
            logging.error(f"下单异常: {e}")
            return False

    def get_position_quantity(self, symbol: str) -> int:
        """获取持仓数量"""
        try:
            ret, data = self.trd_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
            if ret == RET_OK and not data.empty:
                position = data[data['code'] == symbol]
                if not position.empty:
                    return int(position.iloc[0]['qty'])
            return 0
        except Exception as e:
            logging.error(f"获取持仓异常: {e}")
            return 0

    def get_position_value(self, symbol: str) -> float:
        """获取持仓市值"""
        try:
            ret, data = self.trd_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
            if ret == RET_OK and not data.empty:
                position = data[data['code'] == symbol]
                if not position.empty:
                    return float(position.iloc[0]['market_val'])
            return 0.0
        except Exception as e:
            logging.error(f"获取持仓市值异常: {e}")
            return 0.0

    def get_average_cost(self, symbol: str) -> float:
        """获取平均成本"""
        try:
            ret, data = self.trd_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
            if ret == RET_OK and not data.empty:
                position = data[data['code'] == symbol]
                if not position.empty:
                    cost = position.iloc[0]['cost_price']
                    return float(cost) if pd.notna(cost) else 0.0
            return 0.0
        except Exception as e:
            logging.error(f"获取平均成本异常: {e}")
            return 0.0

    def scan_and_trade(self, symbols: List[str]):
        """扫描股票并执行交易"""
        logging.info("开始扫描股票...")
        
        for symbol in symbols:
            try:
                # 检查是否可以交易
                ret, data = self.quote_ctx.get_stock_basicinfo(Market.HK, [SecurityType.STOCK])
                if ret == RET_OK:
                    valid_symbols = set(data['code'].tolist())
                    if symbol not in valid_symbols:
                        continue

                # 检查买入信号
                should_buy, buy_details = self.should_buy(symbol)
                if should_buy:
                    success = self.place_order(
                        symbol=symbol,
                        order_type=OrderType.NORMAL,
                        price=buy_details['price'],
                        qty=buy_details['quantity']
                    )
                    if success:
                        logging.info(f"✅ 买入订单成功: {symbol}")
                    else:
                        logging.info(f"❌ 买入订单失败: {symbol}")

                # 检查卖出信号
                should_sell, sell_details = self.should_sell(symbol)
                if should_sell:
                    success = self.place_order(
                        symbol=symbol,
                        order_type=OrderType.NORMAL,
                        price=sell_details['price'],
                        qty=sell_details['quantity']
                    )
                    if success:
                        logging.info(f"✅ 卖出订单成功: {symbol}")
                    else:
                        logging.info(f"❌ 卖出订单失败: {symbol}")

                # 添加延时避免API限制
                time.sleep(0.5)

            except Exception as e:
                logging.error(f"处理股票 {symbol} 时出错: {e}")
                continue

    def run_single_symbol_test(self, symbol: str):
        """单个股票测试"""
        logging.info(f"开始测试股票: {symbol}")
        
        # 检查买入信号
        should_buy, buy_details = self.should_buy(symbol)
        if should_buy:
            logging.info(f"发现买入信号: {buy_details}")
            # 注意：这里不实际下单，仅作演示
        else:
            logging.info("未发现买入信号")
        
        # 检查卖出信号
        should_sell, sell_details = self.should_sell(symbol)
        if should_sell:
            logging.info(f"发现卖出信号: {sell_details}")
            # 注意：这里不实际下单，仅作演示
        else:
            logging.info("未发现卖出信号")

    def close_connections(self):
        """关闭连接"""
        try:
            self.quote_ctx.close()
            self.trd_ctx.close()
            logging.info("连接已关闭")
        except Exception as e:
            logging.error(f"关闭连接时出错: {e}")


def main():
    # 创建交易实例
    trader = ChanTheoryTrader()
    
    # 测试股票列表
    test_symbols = [
        'HK.00700',  # 腾讯
        'HK.00981',  # 中芯国际
        'HK.09988',  # 阿里巴巴
        'HK.03690',  # 美团
        'HK.03988',  # 中国银行
        'HK.00388',  # 香港交易所
        'HK.00941',  # 阿里健康
        'HK.00763',  # 中兴通讯
        'HK.01810',  # 小米集团
        'HK.01378',  # 中国宏桥
    ]
    
    import argparse
    parser = argparse.ArgumentParser(description='缠论交易系统')
    parser.add_argument('--single', action='store_true', help='单只股票测试模式')
    parser.add_argument('--symbol', type=str, default='HK.00700', help='指定测试股票')
    args = parser.parse_args()
    
    try:
        if args.single:
            # 单只股票测试模式
            trader.run_single_symbol_test(args.symbol)
        else:
            # 正常扫描模式
            while True:
                trader.scan_and_trade(test_symbols)
                logging.info("本轮扫描完成，等待下一轮...")
                time.sleep(300)  # 等待5分钟
    except KeyboardInterrupt:
        logging.info("用户中断程序")
    except Exception as e:
        logging.error(f"主程序出错: {e}")
    finally:
        trader.close_connections()


if __name__ == "__main__":
    main()
