#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
from datetime import datetime
from typing import List, Optional

from DataAPI.CommonStockAPI import CCommonStockApi
from KLine.KLine_Unit import CKLine_Unit
from Common.CEnum import KL_TYPE, AUTYPE
from config import API_CONFIG

class CFinnhubAPI(CCommonStockApi):
    """
    Finnhub API 实现
    官方文档: https://finnhub.io/docs/api/stock-candles
    """
    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CFinnhubAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        self.api_key = API_CONFIG.get('FINNHUB_API_KEY')
        self.base_url = "https://finnhub.io/api/v1"
        self.kl_data: List[CKLine_Unit] = []
        
    def get_kl_data(self) -> List[CKLine_Unit]:
        if self.kl_data:
            return self.kl_data
            
        if not self.api_key:
            print("🔥 [FinnhubAPI] Error: FINNHUB_API_KEY not found in config.")
            return []

        # 1. 转换代码格式 (去除 US. 前缀)
        ticker = self.code.replace("US.", "")
        
        # 2. 转换时间级别
        resolution = self._map_k_type(self.k_type)
        if not resolution:
            print(f"⚠️ [FinnhubAPI] Unsupported k_type: {self.k_type}")
            return []
            
        # 3. 转换日期为 UNIX 时间戳
        from_ts = self._date_to_timestamp(self.begin_date)
        to_ts = self._date_to_timestamp(self.end_date)
        
        # 4. 请求数据
        url = f"{self.base_url}/stock/candle"
        params = {
            "symbol": ticker,
            "resolution": resolution,
            "from": from_ts,
            "to": to_ts,
            "token": self.api_key  # 方式 1: URL 参数
        }
        headers = {
            "X-Finnhub-Token": self.api_key  # 方式 2: Header (文档推荐)
        }
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if data.get('s') == 'ok':
                # 解析数据: o (open), h (high), l (low), c (close), v (volume), t (timestamp)
                for i in range(len(data['t'])):
                    dt = datetime.fromtimestamp(data['t'][i])
                    klu = CKLine_Unit(
                        time=dt,
                        open=float(data['o'][i]),
                        high=float(data['h'][i]),
                        low=float(data['l'][i]),
                        close=float(data['c'][i]),
                        volume=float(data['v'][i]),
                        # Finnhub 不提供成交额和换手率
                    )
                    self.kl_data.append(klu)
                print(f"✅ [FinnhubAPI] Fetched {len(self.kl_data)} bars for {ticker}")
            elif data.get('s') == 'no_data':
                print(f"ℹ️ [FinnhubAPI] No data for {ticker} in range {self.begin_date} to {self.end_date}")
            else:
                print(f"⚠️ [FinnhubAPI] Error response for {ticker}: {data.get('error', 'Unknown error')}")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print(f"🔥 [FinnhubAPI] 429 Too Many Requests: 您已达到 API 频率限制 (免费版 60次/分钟)。")
            elif e.response.status_code == 403:
                print(f"🔥 [FinnhubAPI] 403 Forbidden: API Key 可能无效。")
            else:
                print(f"🔥 [FinnhubAPI] HTTP Error: {e}")
        except Exception as e:
            print(f"🔥 [FinnhubAPI] Error: {e}")
            
        return self.kl_data

    def SetBasciInfo(self):
        # Finnhub 主要用于 K 线数据，基础信息可暂时留空或按需扩展
        pass

    def _map_k_type(self, k_type) -> Optional[str]:
        mapping = {
            KL_TYPE.K_1M: "1",
            KL_TYPE.K_5M: "5",
            KL_TYPE.K_15M: "15",
            KL_TYPE.K_30M: "30",
            KL_TYPE.K_60M: "60",
            KL_TYPE.K_DAY: "D",
            KL_TYPE.K_WEEK: "W",
            KL_TYPE.K_MON: "M",
        }
        return mapping.get(k_type)

    def _date_to_timestamp(self, date_str) -> int:
        if not date_str:
            return int(time.time())
        try:
            if ' ' in date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            return int(dt.timestamp())
        except Exception:
            return int(time.time())
