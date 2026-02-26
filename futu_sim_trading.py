from datetime import datetime
import logging
import subprocess
import time
import os
import sys
from typing import Dict, Any, Optional, Tuple
import numpy as np
from futu import *

# 导入视觉裁判模块
sys.path.insert(0, '/Users/jijunchen/.openclaw/workspace/chan.py')
try:
    from visual_judge import VisualJudge
    VISUAL_JUDGE_AVAILABLE = True
except ImportError:
    VISUAL_JUDGE_AVAILABLE = False
    logging.warning("visual_judge.py 未找到，将使用本地降级算法")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Configuration dictionary
CONFIG = {
    'MAX_POSITION_RATIO': 0.2,  # 单只股票 20% 仓位
    'SCAN_CYCLE': 60,  # seconds
    'VISUAL_SCORING_THRESHOLD': 0.7,  # 视觉评分阈值（70 分）
    'SELL_POINT_ONE_THRESHOLD': 0.02,  # 2% threshold for sell point one
    'SELL_POINT_TWO_THRESHOLD': 0.015,  # 1.5% threshold for sell point two
    'SELL_POINT_THREE_THRESHOLD': 0.01,  # 1% threshold for sell point three
    'RETRY_ATTEMPTS': 3,
    'RETRY_DELAY': 2,  # seconds
    'TRADE_SYMBOL': 'HK.00700',  # Example symbol
    'ACCOUNT_ID': None,  # To be set based on your Futu account
    'SCAN_PERIOD': 'K_30M',  # 扫描周期
    'WATCHLIST_GROUP': '港股',  # 自选股组
}

class FutuSimTrading:
    def __init__(self):
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.trade_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
        self.current_positions = {}
        self.total_assets = 0
        self.init_account_info()
    
    def init_account_info(self):
        """Initialize account information"""
        try:
            ret_code, data = self.trade_ctx.get_acc_list()
            if ret_code == RET_OK:
                for acc_info in data.itertuples():
                    self.account_id = acc_info.acc_id
                    break
            else:
                logging.error(f"Failed to get account list: {data}")
                raise Exception("Account initialization failed")
                
            # Get initial total assets
            ret_code, data = self.trade_ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)
            if ret_code == RET_OK:
                self.total_assets = float(data.iloc[0]['total_assets'])
            else:
                logging.warning(f"Failed to get initial assets: {data}")
                self.total_assets = 100000  # Default starting amount
        except Exception as e:
            logging.error(f"Error initializing account info: {str(e)}")
            raise
    
    def ctime_to_datetime(self, ctime_obj):
        """
        Convert CTime object to datetime object
        修复 CTime 转换错误：使用 CTime 的属性而非 to_datetime() 方法
        """
        if hasattr(ctime_obj, 'year'):
            return datetime(
                year=ctime_obj.year,
                month=ctime_obj.month,
                day=ctime_obj.day,
                hour=getattr(ctime_obj, 'hour', 0),
                minute=getattr(ctime_obj, 'minute', 0),
                second=getattr(ctime_obj, 'second', 0)
            )
        else:
            # If it's already a datetime-like object, return as is
            return ctime_obj
    
    def fetch_kline_data(self, symbol: str, period: str, count: int) -> Optional[Dict[str, Any]]:
        """
        Fetch K-line data for a given symbol
        Must subscribe to market data before fetching K-line
        """
        for attempt in range(CONFIG['RETRY_ATTEMPTS']):
            try:
                # Subscribe to market data first (required by Futu API)
                sub_ret, sub_msg = self.quote_ctx.subscribe(
                    [symbol], 
                    [SubType.K_30M] if period == 'K_30M' else [SubType.K_60M],
                    subscribe_push=False
                )
                if sub_ret != RET_OK:
                    logging.warning(f"Subscribe failed for {symbol}: {sub_msg}")
                
                # Fetch K-line data
                ret_code, data = self.quote_ctx.get_cur_kline(
                    symbol, 
                    count, 
                    period, 
                    AuType.QFQ
                )
                
                if ret_code == RET_OK:
                    # Convert CTime objects to datetime
                    converted_data = data.copy()
                    if 'time_key' in converted_data.columns:
                        converted_data['time_key'] = converted_data['time_key'].apply(
                            lambda x: self.ctime_to_datetime(x)
                        )
                    
                    result = {
                        'open': converted_data['open'].values,
                        'high': converted_data['high'].values,
                        'low': converted_data['low'].values,
                        'close': converted_data['close'].values,
                        'volume': converted_data['volume'].values,
                        'time': converted_data['time_key'].values
                    }
                    return result
                else:
                    logging.warning(f"Attempt {attempt + 1}: Failed to fetch kline data: {data}")
                    if attempt < CONFIG['RETRY_ATTEMPTS'] - 1:
                        time.sleep(CONFIG['RETRY_DELAY'])
                    else:
                        logging.error(f"Failed to fetch kline data after {CONFIG['RETRY_ATTEMPTS']} attempts")
                        return None
                        
            except Exception as e:
                logging.error(f"Exception in fetch_kline_data: {str(e)}")
                if attempt < CONFIG['RETRY_ATTEMPTS'] - 1:
                    time.sleep(CONFIG['RETRY_DELAY'])
                else:
                    return None
        
        return None
    
    def identify_one_sell(self, kline_data: Dict[str, Any]) -> bool:
        """
        Identify first type of sell point based on Chuan theory
        """
        try:
            close_prices = kline_data['close']
            
            if len(close_prices) < 3:
                return False
            
            # Check for bearish reversal pattern
            current_close = close_prices[-1]
            prev_close = close_prices[-2]
            threshold = CONFIG['SELL_POINT_ONE_THRESHOLD']
            
            if (prev_close - current_close) / prev_close > threshold:
                logging.info("First sell point identified")
                return True
                
            return False
        except Exception as e:
            logging.error(f"Error in identify_one_sell: {str(e)}")
            return False
    
    def identify_two_sell(self, kline_data: Dict[str, Any]) -> bool:
        """
        Identify second type of sell point based on Chuan theory
        """
        try:
            close_prices = kline_data['close']
            high_prices = kline_data['high']
            
            if len(close_prices) < 4:
                return False
            
            threshold = CONFIG['SELL_POINT_TWO_THRESHOLD']
            
            # Check for potential double top
            recent_highs = high_prices[-4:]
            if len(recent_highs) >= 2 and abs(recent_highs[-1] - recent_highs[-2]) / recent_highs[-2] < 0.01:
                if len(close_prices) >= 5:
                    if (close_prices[-2] - close_prices[-1]) / close_prices[-2] > threshold:
                        logging.info("Second sell point identified")
                        return True
                        
            return False
        except Exception as e:
            logging.error(f"Error in identify_two_sell: {str(e)}")
            return False
    
    def identify_three_sell(self, kline_data: Dict[str, Any]) -> bool:
        """
        Identify third type of sell point based on Chuan theory
        """
        try:
            close_prices = kline_data['close']
            low_prices = kline_data['low']
            
            if len(close_prices) < 5:
                return False
            
            threshold = CONFIG['SELL_POINT_THREE_THRESHOLD']
            
            # Look for breakdown below support levels
            recent_lows = low_prices[-5:-1]
            min_low = min(recent_lows)
            
            if close_prices[-1] < min_low and (min_low - close_prices[-1]) / min_low > threshold:
                logging.info("Third sell point identified")
                return True
                
            return False
        except Exception as e:
            logging.error(f"Error in identify_three_sell: {str(e)}")
            return False
    
    def call_oracle_visual_score(self, symbol: str, signal_time: datetime) -> Optional[float]:
        """
        调用 Oracle CLI 获取视觉评分
        """
        try:
            # 生成图表文件名
            date_str = signal_time.strftime('%Y%m%d')
            chart_dir = "/Users/jijunchen/.openclaw/workspace/charts"
            
            chart_30m = None
            chart_5m = None
            
            import os
            for file in os.listdir(chart_dir):
                if date_str in file and "30M" in file and symbol.replace('.', '_') in file:
                    chart_30m = os.path.join(chart_dir, file)
                if date_str in file and "5M" in file and symbol.replace('.', '_') in file:
                    chart_5m = os.path.join(chart_dir, file)
            
            if not chart_30m or not chart_5m:
                logging.warning(f"Chart files not found for {symbol} at {signal_time}")
                return None
            
            prompt = """
你是一位资深的缠论交易专家。分析提供的 30M 和 5M K 线图，对卖出信号打分（0-10 分）。

评分标准：
1. 结构完整性 (30%)：30M 上涨中枢是否清晰，c 段是否背驰于 b 段
2. 力度与形态 (40%)：拒绝急涨，有顶分型见顶迹象
3. 次级别确认 (30%)：5M 图是否有盘整背驰

决策规则：Score >= 7 则 SELL，否则 HOLD

**只输出 JSON，不要任何其他文字**：
{"score": 整数 0-10, "signal_quality": "高/中/低", "analysis": "一句话理由", "action": "SELL 或 HOLD"}
"""
            
            result = subprocess.run([
                "oracle", "--image", chart_30m, "--image", chart_5m, "--prompt", prompt
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                response = eval(result.stdout.strip())  # 使用 eval 替代 json.loads 以容错
                score = response.get('score', 0) / 10.0  # 转换为 0-1 范围
                logging.info(f"Oracle visual score for {symbol}: {score}")
                return score
            else:
                logging.error(f"Oracle CLI failed: {result.stderr}")
                return None
                
        except Exception as e:
            logging.error(f"Error getting visual score: {str(e)}")
            return None
    
    def should_buy(self, symbol: str) -> Dict[str, Any]:
        """
        检测三种缠论买点
        Returns: {
            'should_buy': bool,
            'signal_type': str,  # '1buy', '2buy', '3buy'
            'visual_score': float,
            'reason': str
        }
        """
        try:
            kline_data = self.fetch_kline_data(symbol, 'K_30M', 100)
            if kline_data is None:
                return {'should_buy': False, 'reason': 'No data', 'signal_type': None, 'visual_score': 0.0}
            
            close_prices = kline_data['close']
            high_prices = kline_data['high']
            low_prices = kline_data['low']
            
            # Get visual score
            visual_score = self.get_visual_score(kline_data)
            
            # 1 买（底背驰）：价格创新低但下跌力度减弱
            if len(close_prices) >= 10:
                recent_lows = low_prices[-10:]
                min_idx = np.argmin(recent_lows)
                
                # 最近是最低点，且开始反弹
                if min_idx == len(recent_lows) - 1 and len(close_prices) >= 3:
                    if close_prices[-1] > close_prices[-2] * 1.01:  # 反弹>1%
                        logging.info(f"1 buy point identified for {symbol} (底背驰)")
                        return {
                            'should_buy': True,
                            'signal_type': '1buy',
                            'visual_score': visual_score,
                            'reason': '1 买（底背驰）：价格创新低后反弹'
                        }
            
            # 2 买（回踩不破）：双底形态
            if len(close_prices) >= 10:
                first_bottom = min(low_prices[-10:-5])
                second_bottom = min(low_prices[-5:])
                
                # 第二个低点与第一个相差<2%，且开始反弹
                if abs(first_bottom - second_bottom) / first_bottom < 0.02:
                    if close_prices[-1] > close_prices[-2]:
                        logging.info(f"2 buy point identified for {symbol} (回踩不破)")
                        return {
                            'should_buy': True,
                            'signal_type': '2buy',
                            'visual_score': visual_score,
                            'reason': '2 买（回踩不破）：双底形态形成'
                        }
            
            # 3 买（突破回踩）：突破中枢后回踩确认
            if len(close_prices) >= 10:
                recent_high = max(high_prices[-10:])
                current_price = close_prices[-1]
                
                # 价格接近最近 10 根 K 线的最高点 (>98%)
                if current_price > recent_high * 0.98:
                    logging.info(f"3 buy point identified for {symbol} (突破回踩)")
                    return {
                        'should_buy': True,
                        'signal_type': '3buy',
                        'visual_score': visual_score,
                        'reason': '3 买（突破回踩）：价格接近近期高点'
                    }
            
            return {'should_buy': False, 'reason': 'No buy signal', 'signal_type': None, 'visual_score': visual_score}
            
        except Exception as e:
            logging.error(f"Error in should_buy: {str(e)}")
            return {'should_buy': False, 'reason': str(e), 'signal_type': None, 'visual_score': 0.0}
    
    def get_visual_score(self, market_data: Dict[str, Any]) -> float:
        """
        Get visual score (fallback if Oracle CLI fails)
        """
        try:
            close_prices = market_data['close']
            if len(close_prices) < 2:
                return 0.5
            
            trend = (close_prices[-1] - close_prices[0]) / close_prices[0]
            volatility = np.std(np.diff(close_prices)) / np.mean(close_prices)
            
            # Calculate a score between 0 and 1 (higher means more bearish)
            score = max(0, min(1, 0.8 * (volatility * 10) + 0.2 * (1 if trend < 0 else 0)))
            
            logging.info(f"Fallback visual score calculated: {score:.3f}")
            return score
            
        except Exception as e:
            logging.error(f"Error getting fallback visual score: {str(e)}")
            return 0.5
    
    def should_sell(self, symbol: str) -> Dict[str, Any]:
        """
        Determine if we should sell based on Chuan theory sell points and visual scoring
        已修改为使用 K_30M 周期
        Returns: {
            'should_sell': bool,
            'reason': str,
            'visual_score': float
        }
        """
        try:
            # 统一使用 K_30M 周期 (与扫描周期一致，避免订阅冲突)
            kline_data = self.fetch_kline_data(symbol, 'K_30M', 100)
            if kline_data is None:
                logging.warning(f"Could not fetch kline data for {symbol}, skipping sell check")
                return {'should_sell': False, 'reason': 'No data', 'visual_score': 0.0}
            
            # Check for each type of sell point
            sell_point_one = self.identify_one_sell(kline_data)
            sell_point_two = self.identify_two_sell(kline_data)
            sell_point_three = self.identify_three_sell(kline_data)
            
            # Get visual score
            visual_score = self.get_visual_score(kline_data)
            
            # Determine if sell condition is met
            chuan_theory_sell = sell_point_one or sell_point_two or sell_point_three
            
            if chuan_theory_sell:
                logging.info(f"Sell condition met for {symbol}. "
                           f"Chuan Theory: {chuan_theory_sell}, "
                           f"Visual Score: {visual_score:.3f}")
                return {'should_sell': True, 'reason': 'Chuan sell signal', 'visual_score': visual_score}
            
            return {'should_sell': False, 'reason': 'No sell signal', 'visual_score': visual_score}
        except Exception as e:
            logging.error(f"Error in should_sell: {str(e)}")
            return {'should_sell': False, 'reason': str(e), 'visual_score': 0.0}
    
    def open_position(self, symbol: str, investment_amount: float) -> bool:
        """
        Open a new position for a given symbol
        """
        try:
            # Get current price
            ret_code, data = self.quote_ctx.get_market_snapshot(symbol)
            if ret_code != RET_OK:
                logging.error(f"Failed to get market snapshot for {symbol}: {data}")
                return False
            
            current_price = float(data.iloc[0]['last_price'])
            
            # Calculate quantity (round to lot size)
            quantity = int(investment_amount / current_price / 100) * 100
            if quantity <= 0:
                logging.error(f"Quantity too small for {symbol}")
                return False
            
            # Place buy order (price = market * 1.01 to ensure execution)
            ret_code, data = self.trade_ctx.place_order(
                price=current_price * 1.01,
                qty=quantity,
                code=symbol,
                trd_side=TrdSide.BUY,
                order_type=OrderType.NORMAL,
                trd_env=TrdEnv.SIMULATE
            )
            
            if ret_code == RET_OK:
                logging.info(f"Successfully placed buy order for {quantity} shares of {symbol} at {current_price}")
                return True
            else:
                logging.error(f"Failed to place buy order: {data}")
                return False
                
        except Exception as e:
            logging.error(f"Error opening position for {symbol}: {str(e)}")
            return False
    
    def close_position(self, symbol: str, quantity: int = None):
        """
        Close position for a given symbol
        """
        try:
            # Get current position
            ret_code, data = self.trade_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
            if ret_code != RET_OK:
                logging.error(f"Failed to get position list: {data}")
                return False
            
            # Find position for the symbol
            position_row = data[data['code'] == symbol]
            if position_row.empty:
                logging.info(f"No position found for {symbol}")
                return True
            
            quantity = int(position_row.iloc[0]['qty'])
            if quantity <= 0:
                logging.info(f"No long position to close for {symbol}")
                return True
            
            # Place sell order to close position
            ret_code, data = self.trade_ctx.place_order(
                price=0,  # Market order
                qty=quantity,
                code=symbol,
                trd_side=TrdSide.SELL,
                order_type=OrderType.MARKET,
                trd_env=TrdEnv.SIMULATE
            )
            
            if ret_code == RET_OK:
                logging.info(f"Successfully placed sell order for {quantity} shares of {symbol}")
                return True
            else:
                logging.error(f"Failed to place sell order: {data}")
                return False
                
        except Exception as e:
            logging.error(f"Error closing position for {symbol}: {str(e)}")
            return False
    
    def update_portfolio_value(self):
        """
        Update total portfolio value
        """
        try:
            ret_code, data = self.trade_ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)
            if ret_code == RET_OK:
                self.total_assets = float(data.iloc[0]['total_assets'])
            else:
                logging.warning(f"Failed to update portfolio value: {data}")
        except Exception as e:
            logging.error(f"Error updating portfolio value: {str(e)}")
    
    def can_open_new_position(self, investment_amount: float) -> bool:
        """
        Check if we can open a new position without exceeding MAX_POSITION_RATIO
        """
        try:
            self.update_portfolio_value()
            current_investment = sum(self.current_positions.values())
            proposed_total = current_investment + investment_amount
            
            max_allowed = self.total_assets * CONFIG['MAX_POSITION_RATIO']
            
            if proposed_total <= max_allowed:
                return True
            else:
                logging.info(f"Cannot open new position. Current investment: {current_investment}, "
                           f"Proposed addition: {investment_amount}, Max allowed: {max_allowed}")
                return False
        except Exception as e:
            logging.error(f"Error checking position capacity: {str(e)}")
            return False
    
    def run_trading_cycle(self):
        """
        Main trading cycle
        """
        while True:
            try:
                logging.info("Starting trading cycle...")
                
                # Check for positions that need to be closed
                symbols_to_check = list(self.current_positions.keys())
                for symbol in symbols_to_check:
                    if self.should_sell(symbol):
                        success = self.close_position(symbol)
                        if success:
                            del self.current_positions[symbol]
                            logging.info(f"Position closed for {symbol}")
                
                # Update current positions
                self.update_current_positions()
                
                # Wait for next cycle
                time.sleep(CONFIG['SCAN_CYCLE'])
                
            except KeyboardInterrupt:
                logging.info("Trading stopped by user")
                break
            except Exception as e:
                logging.error(f"Error in trading cycle: {str(e)}")
                time.sleep(CONFIG['RETRY_DELAY'])
    
    def update_current_positions(self):
        """
        Update the current positions dictionary
        """
        try:
            ret_code, data = self.trade_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
            if ret_code == RET_OK:
                self.current_positions = {}
                for _, row in data.iterrows():
                    if float(row['qty']) > 0:
                        self.current_positions[row['code']] = float(row['pl_val'])
            else:
                logging.error(f"Failed to update current positions: {data}")
        except Exception as e:
            logging.error(f"Error updating current positions: {str(e)}")
    
    def run_single_scan(self):
        """
        Single scan mode - for crontab scheduled tasks
        Scans once and exits
        """
        try:
            logging.info("="*60)
            logging.info("🔍 开始单次扫描")
            logging.info("="*60)
            
            # Get watchlist stocks
            ret_code, watchlist_data = self.quote_ctx.get_user_security(
                CONFIG['WATCHLIST_GROUP']
            )
            
            if ret_code != RET_OK or watchlist_data is None or len(watchlist_data) == 0:
                logging.warning(f"无法获取自选股组 '{CONFIG['WATCHLIST_GROUP']}'，使用默认股票")
                symbols_to_scan = [CONFIG['TRADE_SYMBOL']]
            else:
                symbols_to_scan = [row['code'] for _, row in watchlist_data.iterrows()]
                logging.info(f"✅ 获取到 {len(symbols_to_scan)} 只股票")
            
            # Update current positions
            self.update_current_positions()
            logging.info(f"📊 当前持仓：{len(self.current_positions)} 只股票")
            
            # Scan each stock
            signals_found = 0
            for symbol in symbols_to_scan:
                try:
                    logging.info(f"\n📈 扫描 {symbol}...")
                    
                    # Fetch K-line data
                    kline_data = self.fetch_kline_data(symbol, CONFIG['SCAN_PERIOD'], 100)
                    if kline_data is None:
                        logging.warning(f"无法获取 {symbol} 的 K 线数据")
                        continue
                    
                    # Check for sell signals (if holding position)
                    if symbol in self.current_positions:
                        sell_result = self.should_sell(symbol)
                        if sell_result['should_sell']:
                            logging.info(f"🔴 检测到卖点：{symbol} | 视觉评分：{sell_result['visual_score']:.2f}")
                            logging.info(f"   理由：{sell_result['reason']}")
                    
                    # Check for buy signals (if not holding)
                    else:
                        buy_result = self.should_buy(symbol)
                        if buy_result['should_buy']:
                            logging.info(f"🟢 检测到买点：{symbol} | 类型：{buy_result['signal_type']} | 视觉评分：{buy_result['visual_score']:.2f}")
                            logging.info(f"   理由：{buy_result['reason']}")
                    
                    signals_found += 1
                    
                except Exception as e:
                    logging.error(f"扫描 {symbol} 时出错：{str(e)}")
                    continue
            
            logging.info("\n" + "="*60)
            logging.info(f"✅ 扫描完成：共扫描 {signals_found}/{len(symbols_to_scan)} 只股票")
            logging.info("="*60)
            
        except Exception as e:
            logging.error(f"单次扫描失败：{str(e)}")
            raise

def main():
    """
    Main function to run the trading system
    """
    import sys
    
    # Check command line arguments
    single_scan = '--single' in sys.argv or '--once' in sys.argv
    
    trader = FutuSimTrading()
    
    try:
        if single_scan:
            # Single scan mode (for crontab)
            logging.info("🔍 单次扫描模式 (Single Scan Mode)")
            trader.run_single_scan()
        else:
            # Continuous mode
            logging.info("🔄 持续扫描模式 (Continuous Mode) - 按 Ctrl+C 停止")
            trader.run_trading_cycle()
    except KeyboardInterrupt:
        logging.info("Shutting down trading system...")
    except Exception as e:
        logging.error(f"Critical error in main: {str(e)}")
    finally:
        # Clean up connections
        trader.quote_ctx.close()
        trader.trade_ctx.close()

if __name__ == "__main__":
    main()
