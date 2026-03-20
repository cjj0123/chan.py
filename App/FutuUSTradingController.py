import asyncio
import logging
import threading
from typing import Tuple
from App.BaseUSTradingController import BaseUSTradingController
from futu import OpenSecTradeContext, TrdEnv, TrdSide, OrderType, RET_OK

logger = logging.getLogger(__name__)

class FutuUSTradingController(BaseUSTradingController):
    """
    美股交易控制器 (Futu 专属)
    """
    def __init__(self, us_watchlist_group="美股", discord_bot=None):
        super().__init__(venue="FUTU", us_watchlist_group=us_watchlist_group, discord_bot=discord_bot)
        # 💡 [业务对齐] 强制 Futu 渠道为模拟盘 (与 IB/Schwab 隔离)
        self.trd_env = TrdEnv.SIMULATE
        self.futu_acc_id = 0

    async def get_account_assets_async(self) -> Tuple[float, float, list]:
        """异步获取账户资产 - 纯净 Futu 通道"""
        try:
            # 1. 自动探查账户环境
            if self.futu_acc_id == 0:
                actual_env_str = 'SIMULATE' if self.trd_env == TrdEnv.SIMULATE else 'REAL'
                ret_list, account_list = self.trd_ctx.get_acc_list()
                
                if ret_list == RET_OK and not account_list.empty:
                    # 打印全量账户列表供调试
                    log_entries = []
                    for _, row in account_list.iterrows():
                        log_entries.append(f"🆔 ID:{row['acc_id']} | Env:{row['trd_env']} | SimType:{row.get('sim_acc_type','N/A')}")
                    self.log_message.emit("🔍 [Futu-账户扫描]:\n   " + "\n   ".join(log_entries))

                    matched = account_list[account_list['trd_env'] == actual_env_str]
                    if self.trd_env == TrdEnv.SIMULATE:
                        # 更加鲁棒的市场权限匹配
                        def has_us_auth(val):
                            if isinstance(val, list): return 'US' in val
                            return 'US' in str(val)
                            
                        us_matched = matched[matched['trdmarket_auth'].apply(has_us_auth) & 
                                             (matched['sim_acc_type'] == 'STOCK')]
                        
                        if not us_matched.empty:
                            matched = us_matched
                        else:
                            # 兜底查找 sim_acc_type == 2 (旧版 API) 或名字包含 US
                            us_matched = matched[(matched['sim_acc_type'] == 2) | 
                                                 (matched['card_num'].str.contains('美国|US', case=False, na=False))]
                            if not us_matched.empty:
                                matched = us_matched
                    
                    if not matched.empty:
                        self.futu_acc_id = int(matched.iloc[0]['acc_id'])
                        self.log_message.emit(f"🎯 [Futu-匹配成功] 已锁定美股账户: {self.futu_acc_id} ({actual_env_str})")
                    else:
                        self.futu_acc_id = int(account_list.iloc[0]['acc_id'])
                        self.log_message.emit(f"⚠️ [Futu-兜底选择] 未找到精准匹配，使用列表首位账户: {self.futu_acc_id}")

            # 2. 查询账户资金
            # 💡 [策略调整] 尝试同时使用两种方式查询，彻底避开 "Nonexisting acc_id" 暗坑
            ret, data = self.trd_ctx.accinfo_query(acc_id=self.futu_acc_id, trd_env=self.trd_env)
            if ret != RET_OK:
                # 尝试不带 acc_id 的缺省查询 (OpenD 会自动路由到当前 Context 的默认账户)
                ret, data = self.trd_ctx.accinfo_query(trd_env=self.trd_env)
                
            available, total = 0.0, 0.0
            if ret == RET_OK and not data.empty:
                row = data.iloc[0]
                available = float(row.get('cash', row.get('usd_cash', 0.0)))
                total = float(row.get('total_assets', row.get('usd_assets', row.get('power', 0.0))))
            else:
                self.log_message.emit(f"⚠️ [Futu] 资金查询失败 (ID:{self.futu_acc_id}): {data if isinstance(data, str) else 'Empty'}")
            
            # 3. 查询持仓
            positions = []
            ret_pos, pos_data = self.trd_ctx.position_list_query(acc_id=self.futu_acc_id, trd_env=self.trd_env)
            if ret_pos != RET_OK:
                ret_pos, pos_data = self.trd_ctx.position_list_query(trd_env=self.trd_env)
                
            if ret_pos == RET_OK and not pos_data.empty:
                for _, row in pos_data.iterrows():
                    qty = int(row['qty'])
                    if qty == 0: continue
                    symbol = row['code'].split('.')[-1]
                    positions.append({
                        'symbol': symbol,
                        'qty': qty,
                        'can_sell_qty': int(row.get('can_sell_qty', qty)),
                        'mkt_value': float(row['market_val']),
                        'avg_cost': float(row['cost_price']),
                        'mkt_price': float(row['nominal_price'])
                    })
            
            return available, total, positions
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股-Futu] 资金持仓查询代码异常: {e}")
            import traceback
            print(traceback.format_exc())
        return 0.0, 0.0, []

    async def _execute_trade_async(self, code: str, action: str, price: float, **kwargs):
        """异步下单 - 纯净 Futu 通道"""
        try:
            qty = kwargs.get('qty', 0) 
            if qty == 0:
                # 💡 [业务对齐] 默认每笔交易约 10,000 USD (与 IB 逻辑对齐)
                qty = max(1, int(10000 / price))

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
                trd_env=self.trd_env,
                acc_id=self.futu_acc_id
            )
            if ret != RET_OK:
                # 再次尝试无 acc_id 模式
                ret_retry, data_retry = self.trd_ctx.place_order(
                    price=limit_price,
                    qty=qty,
                    code=code,
                    trd_side=side,
                    order_type=OrderType.NORMAL,
                    trd_env=self.trd_env
                )
                if ret_retry == RET_OK:
                    ret, data = ret_retry, data_retry

            if ret == RET_OK:
                order_id = data.iloc[0]['order_id']
                self.log_message.emit(f"🚀 [美股-Futu] 限价单提交成功: {code} {action} {qty} @ ${limit_price:.2f} (ID: {order_id})")
                
                # 记录交易
                self._record_trade_to_db(code, action, qty, price, **kwargs)
                # 启动订单跟踪
                asyncio.create_task(
                    self._track_order_status_async(order_id, code, action, qty, limit_price, "FUTU")
                )
                return True
            else:
                self.log_message.emit(f"❌ [美股-Futu] 下单失败: {data}")
                return False
        except Exception as e:
            self.log_message.emit(f"❌ [美股-Futu] 下单异常: {e}")
            return False
