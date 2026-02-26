from futu import *
import logging

logger = logging.getLogger(__name__)

class HKMarket:
    """
    港股市场相关操作类
    """
    def __init__(self, quote_ctx):
        self.quote_ctx = quote_ctx

    def get_lot_size(self, stock_code: str) -> int:
        """
        获取港股每手股数
        
        Args:
            stock_code (str): 股票代码
            
        Returns:
            int: 每手股数，默认为100
        """
        try:
            # 获取股票基本信息
            ret, data = self.quote_ctx.get_stock_basicinfo(Market.HK, [stock_code])
            if ret == RET_OK and len(data) > 0:
                lot_size = data.iloc[0]['lot_size']
                return lot_size if lot_size else 100
            else:
                logger.error(f"获取 {stock_code} 基本信息失败: {data}")
                return 100
        except Exception as e:
            logger.error(f"获取 {stock_code} 每手股数时发生异常: {e}")
            return 100