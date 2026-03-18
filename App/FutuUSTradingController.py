import asyncio
import logging
import threading
from typing import Tuple
from App.BaseUSTradingController import BaseUSTradingController
from futu import OpenUSTradeContext, TrdEnv, TrdSide, OrderType, RET_OK

logger = logging.getLogger(__name__)

class FutuUSTradingController(BaseUSTradingController):
    """
    美股交易控制器 (Futu 专属)
    """
    def __init__(self, us_watchlist_group="美股", discord_bot=None):
        super().__init__(venue="FUTU", us_watchlist_group=us_watchlist_group, discord_bot=discord_bot)
        # 💡 [业务对齐] Futu 通道强制降级为模拟盘
        self.trd_env = TrdEnv.SIMULATE

    async def get_account_assets_async(self) -> Tuple[float, float, list]:
        """异步获取账户资产 - 纯净 Futu 通道"""
        try:
            # 1. 自动探查账户环境
            acc_id = 0
            actual_env = 'SIMULATE' # 强行锁定
            ret_list, account_list = self.trd_ctx.get_acc_list()
            
            if ret_list == RET_OK and not account_list.empty:
                target_env_str = 'SIMULATE'
                matched = account_list[account_list['trd_env'] == target_env_str]
                if not matched.empty:
                    row = matched.iloc[0]
                else:
                    row = account_list.iloc[0]
                acc_id = row['acc_id']

            # 2. 查询账户资金
            ret, data = self.trd_ctx.accinfo_query(acc_id=acc_id, trd_env=actual_env)
            available, total = 0.0, 0.0
            if ret == RET_OK and not data.empty:
                available = float(data.iloc[0]['cash'])
                total = float(data.iloc[0].get('total_assets', data.iloc[0].get('power', 0.0)))
            
            # 3. 查询持仓
            positions = []
            ret_pos, pos_data = self.trd_ctx.position_list_query(acc_id=acc_id, trd_env=actual_env)
            if ret_pos == RET_OK and not pos_data.empty:
                for _, row in pos_data.iterrows():
                    qty = int(row['qty'])
                    if qty == 0: continue
                    symbol = row['code'].split('.')[-1]
                    positions.append({
                        'symbol': symbol,
                        'qty': qty,
                        'mkt_value': float(row['market_val']),
                        'avg_cost': float(row['cost_price']),
                        'mkt_price': float(row['nominal_price'])
                    })
            return available, total, positions
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股-Futu] 资金持仓查询失败: {e}")
        return 0.0, 0.0, []

    async def _execute_trade_async(self, code: str, action: str, price: float, **kwargs):
        """异步下单 - 纯净 Futu 通道"""
        try:
            qty = kwargs.get('qty', 100) # 默认 100
            side = TrdSide.BUY if action.upper() == "BUY" else TrdSide.SELL
            limit_price = round(price * 1.01, 2) if action.upper() == "BUY" else round(price * 0.99, 2)
            
            if not code.startswith("US."):
                code = f"US.{code.split('.')[-1]}"
                
            ret, data = self.trd_ctx.place_order(
                price=limit_price,
                qty=qty,
                code=code,
                trd_side=side,
                order_type=OrderType.NORMAL,
                trd_env=self.trd_env
            )
            if ret == RET_OK:
                order_id = data.iloc[0]['order_id']
                self.log_message.emit(f"🚀 [美股-Futu] 限价单提交成功: {code} {action} {qty} @ ${limit_price:.2f} (ID: {order_id})")
                return True
            else:
                self.log_message.emit(f"❌ [美股-Futu] 下单失败: {data}")
                return False
        except Exception as e:
            self.log_message.emit(f"❌ [美股-Futu] 下单异常: {e}")
            return False
