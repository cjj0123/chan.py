import asyncio
import logging
from App.BaseUSTradingController import BaseUSTradingController
from ib_insync import Stock, LimitOrder

logger = logging.getLogger(__name__)

class IBTradingController(BaseUSTradingController):
    """
    美股交易控制器 (IB 专属)
    """
    def __init__(self, us_watchlist_group="美股", discord_bot=None):
        super().__init__(venue="IB", us_watchlist_group=us_watchlist_group, discord_bot=discord_bot)
        self._last_assets_log_signature = None
        # IB 专属初始化 (如果有的话)

    async def get_account_assets_async(self):
        """异步获取账户资产 - 纯净 IB 通道"""
        if self.ib and self.ib.isConnected():
            return await self._get_ib_assets_async()
        return 0.0, 0.0, []

    async def _get_ib_assets_async(self):
        """原有的 IB 资金获取逻辑"""
        try:
            # 1. 尝试获取缓存值 (增加重试次数限制，防止死循环)
            for i in range(5):
                vals = self.ib.accountValues()
                if vals: break
                await asyncio.sleep(0.5)
            
            port = self.ib.portfolio()
            if not vals:
                self.log_message.emit("⚠️  [IB-资产] 账户数据 (accountValues) 为空，跳过本次解析")
                return 0.0, 0.0, []
            
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
                
                # 🛡️ [补救逻辑] 通过 reqTickers 获取实时价格，避免错误地将成本价 (avgCost) 报送为市价
                ticker_contracts = [p.contract for p in pos_list if p.position != 0]
                tickers = {}
                if ticker_contracts:
                    try:
                        ticker_data = self.ib.reqTickers(*ticker_contracts)
                        tickers = {t.contract.symbol: t for t in ticker_data}
                    except: pass

                for p in pos_list:
                    if p.position != 0:
                        symbol = p.contract.symbol
                        ticker = tickers.get(symbol)
                        # 优先取 last, 兜底取 close 或 avgCost (极简兜底)
                        mkt_price = getattr(ticker, 'last', 0) or getattr(ticker, 'close', 0) or p.avgCost
                        
                        positions_data.append({
                            'symbol': symbol,
                            'qty': int(p.position),
                            'mkt_value': round(p.position * mkt_price, 2),
                            'avg_cost': round(p.avgCost, 2),
                            'mkt_price': mkt_price
                        })
            else:
                for item in actual_items:
                    if item.position != 0:
                        positions_data.append({
                            'symbol': item.contract.symbol,
                            'qty': int(item.position),
                            'mkt_value': round(item.marketValue, 2),
                            'avg_cost': round(item.averageCost, 2),
                            'mkt_price': item.marketPrice
                        })
            log_signature = (
                round(available, 2),
                round(total, 2),
                len(positions_data),
            )
            if log_signature != self._last_assets_log_signature:
                self.log_message.emit(
                    f"🔌 [IB-持仓自愈] 资产查询返回: 可用资金=${available:.2f}, 总资产=${total:.2f}, 持仓数=${len(positions_data)}"
                )
                self._last_assets_log_signature = log_signature
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
                # 🛡️ [风控加固] 拦截在单，防止队列内高频 or 延迟的双 SELL 击穿持仓
                if hasattr(self, 'check_pending_orders') and self.check_pending_orders(code, 'SELL'):
                    self.log_message.emit(f"⏳ [美股-IB] {symbol} 存在未完成 SELL 订单，跳过当前指令")
                    return
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
