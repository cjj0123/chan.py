import asyncio
import logging
from PyQt6.QtCore import pyqtSignal
from App.BaseUSTradingController import BaseUSTradingController
from ib_insync import Stock, LimitOrder

logger = logging.getLogger(__name__)

class IBTradingController(BaseUSTradingController):
    """
    美股交易控制器 (IB 专属)
    """
    def __init__(self, us_watchlist_group="美股", discord_bot=None):
        super().__init__(venue="IB", us_watchlist_group=us_watchlist_group, discord_bot=discord_bot)
        # IB 专属初始化 (如果有的话)

    async def get_account_assets_async(self):
        """异步获取账户资产 - 纯净 IB 通道"""
        if self.ib and self.ib.isConnected():
            return await self._get_ib_assets_async()
        return 0.0, 0.0, []

    async def _get_ib_assets_async(self):
        """原有的 IB 资金获取逻辑"""
        try:
            # 1. 直接获取缓存值 (ib_insync 会自动维护同步)
            vals = self.ib.accountValues()
            port = self.ib.portfolio()
            
            if not vals:
                await asyncio.sleep(0.8)
                vals = self.ib.accountValues()
                port = self.ib.portfolio()
            
            available, total = 0.0, 0.0
            found_tags = []
            available_tags = ('AvailableFunds', 'AvailableFunds-S', 'FullAvailableFunds', 'FullAvailableFunds-S', 'CashBalance', 'TotalCashBalance')
            net_liq_tags = ('NetLiquidation', 'NetLiquidation-S', 'NetLiquidationByCurrency', 'EquityWithLoanValue')
            
            for v in vals:
                if v.tag in available_tags or v.tag in net_liq_tags:
                    found_tags.append(f"{v.tag}({v.currency}):{v.value}")
                try: val_f = float(v.value)
                except: continue
                if v.tag in available_tags:
                    if v.currency == 'USD': available = val_f
                    elif v.currency == 'BASE' and available == 0.0: available = val_f
                    elif available == 0.0: available = val_f
                if v.tag in net_liq_tags:
                    if v.currency == 'USD': total = val_f
                    elif v.currency == 'BASE' and total == 0.0: total = val_f
                    elif total == 0.0: total = val_f
            
            positions_data = []
            actual_items = list(port)
            if not actual_items:
                # 💡 [兜底读取] 如果 portfolio() 缓冲尚未同步，尝试调用同步 positions() 列表
                pos_list = self.ib.positions()
                for p in pos_list:
                    if p.position != 0:
                        positions_data.append({
                            'symbol': p.contract.symbol,
                            'qty': int(p.position),
                            'mkt_value': round(p.position * p.avgCost, 2),
                            'avg_cost': round(p.avgCost, 2)
                        })
            else:
                for item in actual_items:
                    if item.position != 0:
                        positions_data.append({
                            'symbol': item.contract.symbol,
                            'qty': int(item.position),
                            'mkt_value': round(item.marketValue, 2),
                            'avg_cost': round(item.averageCost, 2)
                        })
            self.log_message.emit(f"🔌 [IB-持仓自愈] 资产查询返回: 可用资金=${available:.2f}, 总资产=${total:.2f}, 持仓数=${len(positions_data)}")
            return available, total, positions_data
        except Exception as e:
            self.log_message.emit(f"❌ IB 账户查询异常: {e}")
            return 0.0, 0.0, []

    async def _execute_trade_async(self, code: str, action: str, price: float, **kwargs):
        """异步下单 - 纯净 IB 通道"""
        symbol = code.split('.')[-1]
        qty = kwargs.get('qty', 0)
        if qty == 0:
            available, total, _ = await self.get_account_assets_async()
            qty = max(1, int(10000 / price))
            
        action = action.upper()

        try:
            contract = Stock(symbol, 'SMART', 'USD')
            await self.ib.qualifyContractsAsync(contract)
            
            if price <= 0:
                self.log_message.emit(f"⚠️ {symbol} 价格异常 ({price})，无法计算下单数量")
                return
                
            if action == "SELL":
                curr_qty = self.get_position_quantity(code)
                qty = min(qty, curr_qty)
                if qty <= 0: return

            limit_price = round(price * 1.01, 2) if action == "BUY" else round(price * 0.99, 2)
            
            order = LimitOrder(action, qty, limit_price)
            trade = self.ib.placeOrder(contract, order)
            self.log_message.emit(f"🚀 [美股-IB] 限价单提交成功: {symbol} {action} {qty} @ ${limit_price:.2f}")
            
            # 记录交易
            self._record_trade_to_db(code, action, qty, price, **kwargs)
            # 启动订单跟踪
            asyncio.create_task(
                self._track_order_status_async(None, code, action, qty, limit_price, "IB", trade)
            )
            return True

        except Exception as e:
            self.log_message.emit(f"❌ [美股-IB] 下单异常: {e}")
            return False
