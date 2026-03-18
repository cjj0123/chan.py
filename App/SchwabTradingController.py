import asyncio
import logging
import requests
from typing import Tuple
from App.BaseUSTradingController import BaseUSTradingController
from config import TRADING_CONFIG

logger = logging.getLogger(__name__)

class SchwabTradingController(BaseUSTradingController):
    """
    美股交易控制器 (Schwab 专属)
    """
    def __init__(self, us_watchlist_group="美股", discord_bot=None):
        super().__init__(venue="SCHWAB", us_watchlist_group=us_watchlist_group, discord_bot=discord_bot)
        # Schwab 专属初始化 (如果有的话)

    async def get_account_assets_async(self) -> Tuple[float, float, list]:
        """异步获取账户资产 - 纯净 Schwab 通道"""
        if not self.schwab_account_hash:
            await self._init_schwab_account_async()
            if not self.schwab_account_hash: return 0.0, 0.0, []

        try:
            url = f"https://api.schwabapi.com/trader/v1/accounts/{self.schwab_account_hash}"
            token = self.schwab_api._get_access_token()
            resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, params={'fields': 'positions'})
            if resp.status_code == 401:
                token = self.schwab_api._refresh_access_token()
                resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, params={'fields': 'positions'})
            
            if resp.status_code == 200:
                data = resp.json().get('securitiesAccount', {})
                available = float(data.get('currentBalances', {}).get('buyingPower', 0.0))
                total = float(data.get('currentBalances', {}).get('liquidationValue', 0.0))
                positions = []
                for p in data.get('positions', []):
                    positions.append({
                        'symbol': p['instrument']['symbol'],
                        'qty': int(p['longQuantity'] - p['shortQuantity']),
                        'mkt_value': float(p['marketValue']),
                        'avg_cost': float(p['averagePrice'])
                    })
                return available, total, positions
        except Exception as e:
             self.log_message.emit(f"⚠️ Schwab 账户查询失败: {e}")
        return 0.0, 0.0, []

    async def _execute_trade_async(self, code: str, action: str, price: float, **kwargs):
        """异步下单 - 纯净 Schwab 通道"""
        if not self.schwab_account_hash:
             self.log_message.emit("❌ [美股-Schwab] 账户未初始化，无法下单")
             return False

        symbol = code.split('.')[-1]
        qty = kwargs.get('qty', 100) # 默认 100 股或根据你的逻辑

        # 频率限制
        if not self.schwab_limiter.can_request():
            self.log_message.emit(f"⏳ [美股-Schwab] 达到频率上限，正在等待令牌...")
            self.schwab_limiter.acquire()
            
        try:
            url = f"https://api.schwabapi.com/trader/v1/accounts/{self.schwab_account_hash}/orders"
            token = self.schwab_api._get_access_token()
            limit_price = round(price * 1.01, 2) if action.upper() == "BUY" else round(price * 0.99, 2)
            
            order_payload = {
                "orderType": "LIMIT",
                "session": "NORMAL",
                "duration": "DAY",
                "orderStrategyType": "SINGLE",
                "price": str(limit_price),
                "orderLegCollection": [{
                    "instruction": action.upper(),
                    "quantity": int(qty),
                    "instrument": {
                        "symbol": symbol,
                        "assetType": "EQUITY"
                    }
                }]
            }
            
            resp = requests.post(url, headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }, json=order_payload)
            
            if resp.status_code == 401:
                token = self.schwab_api._refresh_access_token()
                resp = requests.post(url, headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }, json=order_payload)

            if resp.status_code in (200, 201):
                self.log_message.emit(f"🚀 [美股-Schwab] 限价单提交成功: {symbol} {action} {qty} @ ${limit_price:.2f}")
                # 记录交易
                self._record_trade_to_db(code, action, qty, price, **kwargs)
                return True
            else:
                self.log_message.emit(f"❌ [美股-Schwab] 下单失败: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            self.log_message.emit(f"❌ [美股-Schwab] 下单异常: {e}")
            return False

    async def _init_schwab_account_async(self):
        """初始化 Schwab 账户信息 (获取 AccountHash)"""
        try:
            url = "https://api.schwabapi.com/trader/v1/accounts/accountNumbers"
            token = self.schwab_api._get_access_token()
            # 💡 原逻辑是 requests.get，这里保持一致
            resp = requests.get(url, headers={'Authorization': f'Bearer {token}'})
            if resp.status_code == 401:
                token = self.schwab_api._refresh_access_token()
                resp = requests.get(url, headers={'Authorization': f'Bearer {token}'})
            
            if resp.status_code == 200:
                accounts = resp.json()
                if accounts:
                    self.schwab_account_hash = accounts[0]['hashValue']
                    self.log_message.emit(f"✅ [美股-Schwab] 账户初始化成功 (Hash: {self.schwab_account_hash[:8]}...)")
                else:
                    self.log_message.emit("⚠️ [美股-Schwab] 未找到可用账户")
            else:
                self.log_message.emit(f"❌ [美股-Schwab] 账户初始化失败: {resp.status_code}")
        except Exception as e:
            self.log_message.emit(f"⚠️ [美股-Schwab] 初始化异常: {e}")
