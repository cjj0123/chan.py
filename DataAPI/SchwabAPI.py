import os
import json
import base64
import requests
import datetime
import pandas as pd
from typing import Iterator

from DataAPI.CommonStockAPI import CCommonStockApi
from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from dotenv import load_dotenv

class CSchwabAPI(CCommonStockApi):
    """
    Charles Schwab 嘉信理财 API 数据源
    支持自动刷新 Token
    """
    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CSchwabAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        self.token_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'schwab_token.json')
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
        self.client_id = os.getenv('SCHWAB_APP_KEY')
        self.client_secret = os.getenv('SCHWAB_APP_SECRET')

        # 映射 Chanlun K 线周期到 Schwab 的 frequencyType 和 frequency
        self.type_map = {
            KL_TYPE.K_1M: ('minute', 1, 'day'),
            KL_TYPE.K_5M: ('minute', 5, 'day'),
            KL_TYPE.K_15M: ('minute', 15, 'day'),
            KL_TYPE.K_30M: ('minute', 30, 'day'),
            KL_TYPE.K_DAY: ('daily', 1, 'year'),
            KL_TYPE.K_WEEK: ('weekly', 1, 'year'),
            KL_TYPE.K_MON: ('monthly', 1, 'year'),
        }

    def _get_access_token(self):
        if not os.path.exists(self.token_file):
            raise Exception("schwab_token.json 未找到，请先运行 schwab_auth.py")
        with open(self.token_file, 'r') as f:
            self.token_data = json.load(f)
        return self.token_data.get('access_token')

    def _refresh_access_token(self):
        refresh_token = self.token_data.get('refresh_token')
        if not refresh_token:
            raise Exception("schwab_token.json 中没有 refresh_token")

        token_url = "https://api.schwabapi.com/v1/oauth/token"
        headers = {
            "Authorization": "Basic " + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        resp = requests.post(token_url, headers=headers, data=data)
        if resp.status_code == 200:
            new_tokens = resp.json()
            # 更新 token，保持 refresh_token (如果接口没有返回新的)
            self.token_data['access_token'] = new_tokens.get('access_token', self.token_data.get('access_token'))
            if 'refresh_token' in new_tokens:
                self.token_data['refresh_token'] = new_tokens['refresh_token']
            with open(self.token_file, 'w') as f:
                json.dump(self.token_data, f, indent=4)
            return self.token_data['access_token']
        else:
            raise Exception(f"刷新 Schwab Token 失败: {resp.status_code} {resp.text}")

    def get_kl_data(self) -> Iterator[CKLine_Unit]:
        symbol = self.code.split(".")[-1].upper() if self.code.startswith("US.") else self.code.upper()
        
        # 💡 嘉信官方不支持 60M (1小时), 我们用 30M 抓取并在内存中两两合并合成 60M
        is_60m = (self.k_type == KL_TYPE.K_60M)
        request_k_type = KL_TYPE.K_30M if is_60m else self.k_type
        
        freq_type, freq, period_type = self.type_map.get(request_k_type, ('daily', 1, 'year'))
        url = "https://api.schwabapi.com/marketdata/v1/pricehistory"
        
        if self.begin_date:
            start_dt = pd.to_datetime(self.begin_date)
        else:
            start_dt = pd.to_datetime(datetime.datetime.now() - datetime.timedelta(days=365))
            
        if self.end_date:
            end_dt = pd.to_datetime(self.end_date)
        else:
            end_dt = pd.to_datetime(datetime.datetime.now())
            
        start_epoch = int(start_dt.timestamp() * 1000)
        end_epoch = int(end_dt.timestamp() * 1000)

        params = {
            'symbol': symbol,
            'frequencyType': freq_type,
            'frequency': freq,
            'periodType': period_type,
            'startDate': start_epoch,
            'endDate': end_epoch,
            'needExtendedHoursData': 'false'
        }
        
        print(f"\n[CSchwabAPI DEBUG] code={self.code} k_type={self.k_type} params={params}")
        access_token = self._get_access_token()
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 401:
            access_token = self._refresh_access_token()
            headers['Authorization'] = f'Bearer {access_token}'
            response = requests.get(url, headers=headers, params=params)
            
        if response.status_code != 200:
            print(f"❌ Schwab API 请求错误 {self.code}: {response.status_code} {response.text}")
            return
            
        data = response.json()
        if 'candles' not in data or not data['candles']:
            print(f"⚠️ Schwab API 返回无 K 线数据 {self.code} ({self.k_type})")
            return
            
        candles = data['candles']
        
        # 💡 支持 60M 合成 (两两合成)
        if is_60m:
             buffer = []
             for row in candles:
                  buffer.append(row)
                  if len(buffer) == 2:
                       dt = datetime.datetime.fromtimestamp(buffer[0]['datetime']/1000)
                       item_dict = {
                           DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, auto=False),
                           DATA_FIELD.FIELD_OPEN: float(buffer[0]['open']),
                           DATA_FIELD.FIELD_HIGH: max(float(buffer[0]['high']), float(buffer[1]['high'])),
                           DATA_FIELD.FIELD_LOW: min(float(buffer[0]['low']), float(buffer[1]['low'])),
                           DATA_FIELD.FIELD_CLOSE: float(buffer[1]['close']),
                           DATA_FIELD.FIELD_VOLUME: float(buffer[0]['volume']) + float(buffer[1]['volume']),
                           DATA_FIELD.FIELD_TURNOVER: float(buffer[0]['close']) * (float(buffer[0]['volume']) + float(buffer[1]['volume'])),
                           DATA_FIELD.FIELD_TURNRATE: 0.0
                       }
                       yield CKLine_Unit(item_dict)
                       buffer = []
        else:
             for row in candles:
                 dt = datetime.datetime.fromtimestamp(row['datetime']/1000)
                 item_dict = {
                     DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, auto=(self.k_type in [KL_TYPE.K_DAY, KL_TYPE.K_WEEK, KL_TYPE.K_MON])),
                     DATA_FIELD.FIELD_OPEN: float(row['open']),
                     DATA_FIELD.FIELD_HIGH: float(row['high']),
                     DATA_FIELD.FIELD_LOW: float(row['low']),
                     DATA_FIELD.FIELD_CLOSE: float(row['close']),
                     DATA_FIELD.FIELD_VOLUME: float(row['volume']),
                     DATA_FIELD.FIELD_TURNOVER: float(row['close']) * float(row['volume']),
                     DATA_FIELD.FIELD_TURNRATE: 0.0
                 }
                 yield CKLine_Unit(item_dict)

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass
