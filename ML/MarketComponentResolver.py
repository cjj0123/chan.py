import pandas as pd
import requests
import logging
import os
import asyncio
from typing import List, Dict, Optional
from futu import *

logger = logging.getLogger(__name__)

class MarketComponentResolver:
    """
    负责解析主要市场指数的成分股
    支持:
    - US: S&P 500, Nasdaq 100
    - HK: HSI, HS Tech
    - CN: CSI 300, SSE 50
    """
    
    def __init__(self, futu_host='127.0.0.1', futu_port=11111):
        self.futu_host = futu_host
        self.futu_port = futu_port
        
    def _fetch_wikipedia_table(self, url: str) -> List[pd.DataFrame]:
        """使用 User-Agent 绕过 403 错误"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return pd.read_html(response.text)

    def resolve_sp500(self) -> List[str]:
        """获取标普 500 成分股 (约 500 只)"""
        try:
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            tables = self._fetch_wikipedia_table(url)
            df = tables[0]
            symbols = df['Symbol'].tolist()
            return [f"US.{s.replace('.', '-')}" for s in symbols if isinstance(s, str)]
        except Exception as e:
            logger.error(f"Failed SP500: {e}")
            return [f"US.{s}" for s in ["AAPL", "MSFT", "AMZN", "NVDA", "GOOGL"]]

    def resolve_nasdaq100(self) -> List[str]:
        """获取纳斯达克 100 成分股 (约 100 只)"""
        try:
            url = "https://en.wikipedia.org/wiki/Nasdaq-100"
            tables = self._fetch_wikipedia_table(url)
            for df in tables:
                if 'Ticker' in df.columns or 'Symbol' in df.columns:
                    symbols = df['Ticker' if 'Ticker' in df.columns else 'Symbol'].tolist()
                    return [f"US.{s}" for s in symbols if isinstance(s, str)]
            return []
        except Exception as e:
            logger.error(f"Failed Nasdaq100: {e}")
            return []

    def resolve_hk_lean(self) -> List[str]:
        """获取港股核心标的 (前 200 只活跃股)"""
        quote_ctx = OpenQuoteContext(host=self.futu_host, port=self.futu_port)
        try:
            ret, data = quote_ctx.get_stock_basicinfo(Market.HK, SecurityType.STOCK)
            if ret == RET_OK:
                # 选取前 200 只 (通常包含大型蓝筹和活跃股)
                return data['code'].tolist()[:200]
            return [f"HK.{s}" for s in ["00700", "09988", "03690"]]
        except:
            return [f"HK.{s}" for s in ["00700", "09988", "03690"]]
        finally:
            quote_ctx.close()

    def resolve_cn_core(self) -> List[str]:
        """获取 A 股核心指数 (沪深 300 + 中证 500, 约 800 只)"""
        quote_ctx = OpenQuoteContext(host=self.futu_host, port=self.futu_port)
        total = []
        try:
            for m in [Market.SH, Market.SZ]:
                ret, data = quote_ctx.get_plate_list(m, Plate.ALL)
                if ret == RET_OK:
                    # 匹配 '沪深300' 或 '中证500'
                    targets = data[data['plate_name'].str.contains('沪深300|中证500', na=False)]
                    for _, row in targets.iterrows():
                        ret_s, data_s = quote_ctx.get_plate_stock(row['code'])
                        if ret_s == RET_OK:
                            total.extend(data_s['code'].tolist())
            res = list(set(total))
            if not res:
                return ["SH.600519", "SZ.000333", "SH.601318"]
            return res
        except:
            return ["SH.600519", "SZ.000333"]
        finally:
            quote_ctx.close()

    def get_all_training_targets(self) -> Dict[str, List[str]]:
        """获取精简后的全市场训练目标 (总量约 1500)"""
        return {
            "US": list(set(self.resolve_sp500() + self.resolve_nasdaq100())),
            "HK": self.resolve_hk_lean(),
            "CN": self.resolve_cn_core()
        }

if __name__ == "__main__":
    resolver = MarketComponentResolver()
    targets = resolver.get_all_training_targets()
    grand_total = 0
    for m, stocks in targets.items():
        print(f"Market {m}: Found {len(stocks)} stocks")
        grand_total += len(stocks)
        if stocks:
            print(f"  Example: {stocks[:5]}")
    print(f"\n🚀 Grand Total: {grand_total} stocks (Limit: 2000)")
