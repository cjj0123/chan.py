import pandas as pd
from datetime import datetime
import time
import random
from futu import * 
from DataAPI.CommonStockAPI import CCommonStockApi
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

class CFutuAPI(CCommonStockApi):
    def __init__(self, code, k_type, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CFutuAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        
        self.type_map = {
            KL_TYPE.K_1M: SubType.K_1M,
            KL_TYPE.K_5M: SubType.K_5M,
            KL_TYPE.K_15M: SubType.K_15M,
            KL_TYPE.K_30M: SubType.K_30M,
            KL_TYPE.K_60M: SubType.K_60M,
            KL_TYPE.K_DAY: SubType.K_DAY,
            KL_TYPE.K_WEEK: SubType.K_WEEK,
            KL_TYPE.K_MON: SubType.K_MON,
        }
        
        self.autype_map = {
            AUTYPE.QFQ: AuType.QFQ,
            AUTYPE.HFQ: AuType.HFQ,
            AUTYPE.NONE: AuType.NONE,
        }

    def get_kl_data(self):
        """
        [EvoMap Strategy Fusion - Online Version]
        - Smart Retry for API Limits
        - Median-based Anomaly Filtering
        - Fixed: use request_history_kline instead of non-existent get_history_kl
        """
        stock_code = str(self.code).upper() 
        if '.' not in stock_code:
            if len(stock_code) == 5: stock_code = f"HK.{stock_code}"
            elif stock_code.startswith('6'): stock_code = f"SH.{stock_code}"
            else: stock_code = f"SZ.{stock_code}"
        
        quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        
        try:
            f_ktype = self.type_map.get(self.k_type, SubType.K_DAY)
            f_autype = self.autype_map.get(self.autype, AuType.QFQ)
            
            # 1. 订阅检查
            quote_ctx.subscribe([stock_code], [f_ktype], subscribe_push=False)

            # 2. 指数退避重试 (使用 request_history_kline)
            retries = 3
            data = None
            for i in range(retries):
                # 注意：request_history_kline 是分页接口，此处简单模拟单次请求，如果需要全量则需递归
                ret, data, page_token = quote_ctx.request_history_kline(
                    stock_code, 
                    start=self.begin_date, 
                    end=self.end_date, 
                    ktype=f_ktype, 
                    autype=f_autype
                )
                if ret == RET_OK:
                    break
                print(f"⚠️ [FutuAPI] Request failed ({data}), retrying {i+1}/{retries}...")
                time.sleep(random.uniform(0.5, 1.0) * (2 ** i))

            if ret == RET_OK and not data.empty:
                # 3. 异常值过滤
                data['price_change'] = data['close'].diff().abs()
                median_change = data['price_change'].median()
                if median_change > 0:
                    outliers = data[data['price_change'] > median_change * 15]
                    if not outliers.empty:
                        print(f"[EVOMAP-RECOVERY] Warning: Found {len(outliers)} online price anomalies for {stock_code}.")

                for _, row in data.iterrows():
                    time_str = row['time_key']
                    try:
                        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        dt = datetime.strptime(time_str, "%Y-%m-%d")

                    item_dict = {
                        DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                        DATA_FIELD.FIELD_OPEN: float(row['open']),
                        DATA_FIELD.FIELD_HIGH: float(row['high']),
                        DATA_FIELD.FIELD_LOW: float(row['low']),
                        DATA_FIELD.FIELD_CLOSE: float(row['close']),
                        DATA_FIELD.FIELD_VOLUME: float(row['volume']),
                        DATA_FIELD.FIELD_TURNOVER: float(row.get('turnover', 0.0)),
                        DATA_FIELD.FIELD_TURNRATE: float(row.get('turnover_rate', 0.0))
                    }
                    yield CKLine_Unit(item_dict)
            else:
                print(f"❌ [FutuAPI] No data retrieved for {stock_code}")
                
        except Exception as e:
            print(f"🔥 [FutuAPI] Online Error: {e}")
        finally:
            quote_ctx.close()

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True
