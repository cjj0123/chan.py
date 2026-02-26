import time
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import threading
import queue

# 导入富途API相关模块
from futu import *

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('futu_trading.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

@dataclass
class TradingSignal:
    stock_code: str
    direction: str  # 'BUY' or 'SELL'
    quantity: int
    price: float
    timestamp: datetime
    order_type: OrderType = OrderType.MARKET

class HKMarket:
    """港股市场相关功能类"""
    
    def __init__(self, quote_ctx):
        self.quote_ctx = quote_ctx
    
    def get_lot_size(self, stock_code: str) -> int:
        """
        获取港股每手股数
        
        Args:
            stock_code: 股票代码，如 'HK.00700'
            
        Returns:
            每手股数
        """
        try:
            # 使用富途API获取股票基本信息
            ret, data = self.quote_ctx.get_stock_basicinfo(
                Market.HK, [stock_code]
            )
            
            if ret == RET_OK and not data.empty:
                lot_size = int(data.iloc[0]['lot_size'])
                logger.info(f"获取 {stock_code} 每手股数: {lot_size}")
                return lot_size
            else:
                logger.error(f"获取 {stock_code} 每手股数失败: {data}")
                # 返回默认值
                return 100
        except Exception as e:
            logger.error(f"Error getting lot size for {stock_code}: {e}")
            return 100  # 默认返回100股每手

class TechnicalAnalyzer:
    """技术分析类"""
    
    def __init__(self):
        pass
    
    def calculate_sma(self, prices: pd.Series, period: int) -> pd.Series:
        """计算简单移动平均线"""
        return prices.rolling(window=period).mean()
    
    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """计算指数移动平均线"""
        return prices.ewm(span=period).mean()
    
    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """计算RSI指标"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_macd(self, prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算MACD指标"""
        ema_fast = self.calculate_ema(prices, fast)
        ema_slow = self.calculate_ema(prices, slow)
        macd_line = ema_fast - ema_slow
        signal_line = self.calculate_ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    def generate_signals(self, df: pd.DataFrame) -> List[TradingSignal]:
        """生成交易信号"""
        signals = []
        
        # 计算技术指标
        df['SMA_20'] = self.calculate_sma(df['close'], 20)
        df['SMA_50'] = self.calculate_sma(df['close'], 50)
        df['RSI'] = self.calculate_rsi(df['close'])
        
        # 金叉死叉策略
        for i in range(1, len(df)):
            current_price = df['close'].iloc[i]
            prev_sma20 = df['SMA_20'].iloc[i-1]
            curr_sma20 = df['SMA_20'].iloc[i]
            prev_sma50 = df['SMA_50'].iloc[i-1]
            curr_sma50 = df['SMA_50'].iloc[i]
            rsi = df['RSI'].iloc[i]
            
            # 金叉：短期均线上穿长期均线
            if prev_sma20 <= prev_sma50 and curr_sma20 > curr_sma50 and rsi < 70:
                signal = TradingSignal(
                    stock_code=df['code'].iloc[0],
                    direction='BUY',
                    quantity=1000,  # 示例数量
                    price=current_price,
                    timestamp=df.index[i],
                    order_type=OrderType.MARKET
                )
                signals.append(signal)
            
            # 死叉：短期均线下穿长期均线
            elif prev_sma20 >= prev_sma50 and curr_sma20 < curr_sma50 and rsi > 30:
                signal = TradingSignal(
                    stock_code=df['code'].iloc[0],
                    direction='SELL',
                    quantity=1000,  # 示例数量
                    price=current_price,
                    timestamp=df.index[i],
                    order_type=OrderType.MARKET
                )
                signals.append(signal)
        
        return signals

class PortfolioManager:
    """投资组合管理类"""
    
    def __init__(self, initial_capital: float = 1000000):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.positions = {}  # {stock_code: {'quantity': int, 'avg_price': float}}
        self.trades = []
        self.total_pnl = 0.0
    
    def update_position(self, stock_code: str, quantity: int, price: float, direction: str):
        """更新持仓"""
        if direction == 'BUY':
            if stock_code in self.positions:
                # 计算新的平均成本
                old_quantity = self.positions[stock_code]['quantity']
                old_avg_price = self.positions[stock_code]['avg_price']
                
                new_quantity = old_quantity + quantity
                new_avg_price = (old_quantity * old_avg_price + quantity * price) / new_quantity
                
                self.positions[stock_code] = {
                    'quantity': new_quantity,
                    'avg_price': new_avg_price
                }
            else:
                self.positions[stock_code] = {
                    'quantity': quantity,
                    'avg_price': price
                }
        elif direction == 'SELL':
            if stock_code in self.positions:
                old_quantity = self.positions[stock_code]['quantity']
                new_quantity = old_quantity - quantity
                
                if new_quantity == 0:
                    del self.positions[stock_code]
                else:
                    self.positions[stock_code]['quantity'] = new_quantity
    
    def calculate_pnl(self, stock_code: str, current_price: float) -> float:
        """计算单只股票的盈亏"""
        if stock_code not in self.positions:
            return 0.0
        
        position = self.positions[stock_code]
        avg_price = position['avg_price']
        quantity = position['quantity']
        
        pnl = (current_price - avg_price) * quantity
        return pnl
    
    def calculate_total_value(self, market_data: Dict[str, float]) -> float:
        """计算总投资价值"""
        total_value = self.current_capital
        
        for stock_code, position in self.positions.items():
            if stock_code in market_data:
                current_price = market_data[stock_code]
                market_value = current_price * position['quantity']
                total_value += market_value - (position['avg_price'] * position['quantity'])
        
        return total_value

class RiskManager:
    """风险管理类"""
    
    def __init__(self, max_position_size: float = 0.1, max_daily_loss: float = 0.05):
        self.max_position_size = max_position_size  # 单只股票最大仓位比例
        self.max_daily_loss = max_daily_loss  # 最大日亏损比例
        self.daily_loss_limit = max_daily_loss
    
    def check_position_size(self, capital: float, stock_value: float) -> bool:
        """检查仓位大小是否超限"""
        return (stock_value / capital) <= self.max_position_size
    
    def check_daily_loss(self, daily_pnl: float, capital: float) -> bool:
        """检查日亏损是否超限"""
        return abs(daily_pnl) / capital <= self.max_daily_loss
    
    def validate_order(self, stock_code: str, quantity: int, price: float, 
                      portfolio_value: float, positions: Dict) -> bool:
        """验证订单风险"""
        order_value = quantity * price
        max_position_value = portfolio_value * self.max_position_size
        
        # 检查单只股票仓位是否超限
        existing_position_value = 0
        if stock_code in positions:
            existing_pos = positions[stock_code]
            existing_position_value = existing_pos['quantity'] * price
        
        total_position_value = existing_position_value + order_value
        
        return total_position_value <= max_position_value

class FutuTradingEngine:
    """富途交易引擎主类"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.quote_ctx = OpenQuoteContext(
            host=self.config.get('host', '127.0.0.1'),
            port=self.config.get('port', 11111)
        )
        self.trade_ctx = OpenUSTradeContext(
            host=self.config.get('host', '127.0.0.1'),
            port=self.config.get('trade_port', 11111),
            security_firm=self.config.get('security_firm', SecurityFirm.FUTU_SEC)
        )
        
        # 初始化各组件
        self.hk_market = HKMarket(self.quote_ctx)
        self.analyzer = TechnicalAnalyzer()
        self.portfolio_manager = PortfolioManager(config.get('initial_capital', 1000000))
        self.risk_manager = RiskManager()
        
        # 交易队列
        self.signal_queue = queue.Queue()
        self.order_queue = queue.Queue()
        
        # 交易状态
        self.is_running = False
        self.active_orders = {}
        
        logger.info("富途交易引擎初始化完成")
    
    def get_market_snapshot(self, stock_codes: List[str]) -> Dict:
        """获取市场快照"""
        try:
            ret, data = self.quote_ctx.subscribe(stock_codes, [SubType.QUOTE])
            if ret != RET_OK:
                logger.error(f"订阅失败: {data}")
                return {}
            
            ret, snapshot = self.quote_ctx.get_stock_quote(stock_codes)
            if ret != RET_OK:
                logger.error(f"获取快照失败: {snapshot}")
                return {}
            
            market_data = {}
            for _, row in snapshot.iterrows():
                market_data[row['code']] = {
                    'last_price': row['last_price'],
                    'volume': row['volume'],
                    'turnover': row['turnover'],
                    'change_rate': row['change_rate']
                }
            
            return market_data
        except Exception as e:
            logger.error(f"获取市场快照出错: {e}")
            return {}
    
    def round_to_lot_size(self, quantity: int, lot_size: int) -> int:
        """将数量调整为整手数"""
        return (quantity // lot_size) * lot_size
    
    def place_order(self, signal: TradingSignal) -> Optional[str]:
        """下单"""
        try:
            # 获取每手股数
            lot_size = self.hk_market.get_lot_size(signal.stock_code)
            
            # 将数量调整为整手数
            adjusted_quantity = self.round_to_lot_size(signal.quantity, lot_size)
            
            if adjusted_quantity == 0:
                logger.warning(f"调整后的数量为0，无法下单: {signal.stock_code}")
                return None
            
            # 风险检查
            portfolio_value = self.portfolio_manager.calculate_total_value({})
            if not self.risk_manager.validate_order(
                signal.stock_code, adjusted_quantity, signal.price, 
                portfolio_value, self.portfolio_manager.positions
            ):
                logger.warning(f"订单风险检查不通过: {signal.stock_code}")
                return None
            
            # 下单参数
            order_id = None
            if signal.order_type == OrderType.MARKET:
                ret, data = self.trade_ctx.place_order(
                    price=signal.price,
                    qty=adjusted_quantity,
                    code=signal.stock_code,
                    trd_side=TrdSide.BUY if signal.direction == 'BUY' else TrdSide.SELL,
                    order_type=OrderType.NORMAL
                )
            else:  # LIMIT ORDER
                ret, data = self.trade_ctx.place_order(
                    price=signal.price,
                    qty=adjusted_quantity,
                    code=signal.stock_code,
                    trd_side=TrdSide.BUY if signal.direction == 'BUY' else TrdSide.SELL,
                    order_type=OrderType.LIMIT
                )
            
            if ret == RET_OK:
                order_id = str(data.iloc[0]['order_id'])
                logger.info(f"订单已提交 - ID: {order_id}, 股票: {signal.stock_code}, "
                           f"方向: {signal.direction}, 数量: {adjusted_quantity}, 价格: {signal.price}")
                
                # 更新持仓（模拟）
                self.portfolio_manager.update_position(
                    signal.stock_code, adjusted_quantity, signal.price, signal.direction
                )
                
                return order_id
            else:
                logger.error(f"下单失败: {data}")
                return None
                
        except Exception as e:
            logger.error(f"下单过程中出现错误: {e}")
            return None
    
    def process_signals(self):
        """处理交易信号"""
        while self.is_running:
            try:
                signal = self.signal_queue.get(timeout=1)
                if signal:
                    order_id = self.place_order(signal)
                    if order_id:
                        self.active_orders[order_id] = signal
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"处理交易信号时出错: {e}")
    
    def fetch_historical_data(self, stock_code: str, days: int = 30) -> pd.DataFrame:
        """获取历史数据"""
        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            
            ret, data = self.quote_ctx.get_history_kline(
                code=stock_code,
                start=start_time.strftime('%Y-%m-%d'),
                end=end_time.strftime('%Y-%m-%d'),
                ktype=KLType.K_DAY
            )
            
            if ret == RET_OK:
                return data
            else:
                logger.error(f"获取历史数据失败: {data}")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取历史数据时出错: {e}")
            return pd.DataFrame()
    
    def run_strategy(self, stock_codes: List[str]):
        """运行交易策略"""
        while self.is_running:
            try:
                for stock_code in stock_codes:
                    # 获取历史数据
                    hist_data = self.fetch_historical_data(stock_code)
                    
                    if not hist_data.empty:
                        # 生成交易信号
                        signals = self.analyzer.generate_signals(hist_data)
                        
                        # 添加到信号队列
                        for signal in signals:
                            self.signal_queue.put(signal)
                            logger.info(f"生成交易信号: {signal}")
                
                # 策略执行间隔
                time.sleep(self.config.get('strategy_interval', 60))
                
            except Exception as e:
                logger.error(f"运行策略时出错: {e}")
                time.sleep(5)
    
    def start(self, stock_codes: List[str]):
        """启动交易引擎"""
        self.is_running = True
        
        # 启动信号处理线程
        signal_thread = threading.Thread(target=self.process_signals)
        signal_thread.daemon = True
        signal_thread.start()
        
        # 启动策略线程
        strategy_thread = threading.Thread(target=self.run_strategy, args=(stock_codes,))
        strategy_thread.daemon = True
        strategy_thread.start()
        
        logger.info("交易引擎已启动")
        
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到停止信号")
            self.stop()
    
    def stop(self):
        """停止交易引擎"""
        logger.info("正在停止交易引擎...")
        self.is_running = False
        
        # 关闭连接
        self.quote_ctx.close()
        self.trade_ctx.close()
        
        logger.info("交易引擎已停止")

def main():
    """主函数"""
    # 配置参数
    config = {
        'host': '127.0.0.1',
        'port': 11111,
        'trade_port': 11111,
        'security_firm': SecurityFirm.FUTU_SEC,
        'initial_capital': 1000000,
        'strategy_interval': 60
    }
    
    # 监控的股票列表
    stock_codes = ['HK.00700', 'HK.00001', 'HK.03690']
    
    # 创建交易引擎
    engine = FutuTradingEngine(config)
    
    try:
        # 启动交易
        engine.start(stock_codes)
    except Exception as e:
        logger.error(f"交易引擎运行出错: {e}")
    finally:
        engine.stop()

if __name__ == "__main__":
    main()