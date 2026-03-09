import requests
import pandas as pd
from datetime import datetime
import time
from .CommonStockAPI import CCommonStockApi
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from config import API_CONFIG

class CPolygonAPI(CCommonStockApi):
    def __init__(self, code, k_type, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CPolygonAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        self.api_key = API_CONFIG.get('POLYGON_API_KEY', '')
        
        # Mapping KL_TYPE to Polygon multiplier and timespan
        self.type_map = {
            KL_TYPE.K_1M: (1, 'minute'),
            KL_TYPE.K_5M: (5, 'minute'),
            KL_TYPE.K_15M: (15, 'minute'),
            KL_TYPE.K_30M: (30, 'minute'),
            KL_TYPE.K_60M: (60, 'minute'),
            KL_TYPE.K_DAY: (1, 'day'),
            KL_TYPE.K_WEEK: (1, 'week'),
            KL_TYPE.K_MON: (1, 'month'),
        }

    def get_kl_data(self):
        if not self.api_key:
            print("⚠️ [PolygonAPI] Warning: No API Key provided.")
            return

        ticker = self.code.upper()
        if ticker.startswith("US."):
            ticker = ticker.split(".")[-1]
        
        multiplier, timespan = self.type_map.get(self.k_type, (1, 'day'))
        
        # Format dates (Polygon expects YYYY-MM-DD)
        start_date = self.begin_date.split(' ')[0] if self.begin_date else "2020-01-01"
        end_date = self.end_date.split(' ')[0] if self.end_date else datetime.now().strftime("%Y-%m-%d")
        
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start_date}/{end_date}"
        params = {
            "adjusted": "true" if self.autype != AUTYPE.NONE else "false",
            "sort": "asc",
            "limit": 5000,
            "apiKey": self.api_key
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'OK' and 'results' in data:
                for res in data['results']:
                    # Polygon 't' is Unix Msec timestamp (end of period)
                    dt = datetime.fromtimestamp(res['t'] / 1000.0)
                    
                    item_dict = {
                        DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                        DATA_FIELD.FIELD_OPEN: float(res['o']),
                        DATA_FIELD.FIELD_HIGH: float(res['h']),
                        DATA_FIELD.FIELD_LOW: float(res['l']),
                        DATA_FIELD.FIELD_CLOSE: float(res['c']),
                        DATA_FIELD.FIELD_VOLUME: float(res['v']),
                        DATA_FIELD.FIELD_TURNOVER: float(res.get('vw', 0.0)) * float(res['v']), # Volume Weighted Average Price * Volume approx
                        DATA_FIELD.FIELD_TURNRATE: 0.0 # Polygon doesn't directly provide turnrate in aggs
                    }
                    yield CKLine_Unit(item_dict)
            else:
                print(f"⚠️ [PolygonAPI] No data for {ticker}: {data.get('error', 'Unknown error')}")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                print(f"🔥 [PolygonAPI] 403 Forbidden: 可能是 API Key 无效，或者您正在尝试访问超出套餐范围的历史数据 (免费版仅限2年内)。")
            elif e.response.status_code == 429:
                print(f"🔥 [PolygonAPI] 429 Too Many Requests: 您已达到 API 频率限制 (免费版 5次/分钟)。")
            else:
                print(f"🔥 [PolygonAPI] HTTP Error: {e}")
            raise e
        except Exception as e:
            err_msg = str(e)
            if "Connection refused" in err_msg or "Name or service not known" in err_msg or "Failed to establish a new connection" in err_msg:
                print(f"🔥 [PolygonAPI] Error: 网络连接错误。请检查您的网络连接或代理设置。")
            elif "JSONDecodeError" in err_msg or "Expecting value" in err_msg:
                print(f"🔥 [PolygonAPI] Error: API响应数据解析失败。Polygon API可能返回了非预期的内容。")
            else:
                print(f"🔥 [PolygonAPI] Error: {err_msg}")
            raise e

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

if __name__ == "__main__":
    # Test block
    from Common.CEnum import KL_TYPE
    api = CPolygonAPI("AAPL", KL_TYPE.K_DAY, "2023-01-01", "2023-01-10")
    for klu in api.get_kl_data():
        print(klu.time, klu.close)
