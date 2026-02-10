import pandas as pd
from futu import *
from DataAPI.CommonStockAPI import CCommonStockApi
from Common.CEnum import KL_TYPE, DATA_FIELD, AUTYPE
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

class CFutuAPI(CCommonStockApi):
    def __init__(self, code, k_type, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CFutuAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        
        # 映射 Chan.py 的级别到 Futu 的级别
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
        
        # 映射复权类型
        self.autype_map = {
            AUTYPE.QFQ: AuType.QFQ,
            AUTYPE.HFQ: AuType.HFQ,
            AUTYPE.NONE: AuType.NONE,
        }

    def get_kl_data(self):
        # 建立连接 (假设 OpenD 在本地运行，默认端口 11111)
        quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        
        try:
            futu_type = self.type_map.get(self.k_type)
            if not futu_type:
                raise Exception(f"不支持的级别: {self.k_type}")

            futu_autype = self.autype_map.get(self.autype, AuType.QFQ)
            
            # 处理时间格式，Futu 需要 YYYY-MM-DD
            start_str = self.begin_date if self.begin_date else "2020-01-01"
            end_str = self.end_date if self.end_date else datetime.now().strftime("%Y-%m-%d")

            # 请求历史 K 线
            ret, data, page_req_key = quote_ctx.request_history_kline(
                self.code, 
                start=start_str, 
                end=end_str, 
                ktype=futu_type, 
                autype=futu_autype, 
                fields=[KL_FIELD.ALL], 
                max_count=1000  # 限制请求数量，防止过慢
            )
            
            if ret == RET_OK:
                for _, row in data.iterrows():
                    # 构造 chan.py 需要的 KLine_Unit
                    item_dict = {
                        DATA_FIELD.FIELD_TIME: CTime(row['time_key']),
                        DATA_FIELD.FIELD_OPEN: float(row['open']),
                        DATA_FIELD.FIELD_HIGH: float(row['high']),
                        DATA_FIELD.FIELD_LOW: float(row['low']),
                        DATA_FIELD.FIELD_CLOSE: float(row['close']),
                        DATA_FIELD.FIELD_VOLUME: float(row['volume']),
                        DATA_FIELD.FIELD_TURNOVER: float(row['turnover']),
                        DATA_FIELD.FIELD_TURNRATE: float(row['turnover_rate']) if 'turnover_rate' in row else 0.0
                    }
                    yield CKLine_Unit(item_dict)
            else:
                print('FutuAPI error:', data)
                
        except Exception as e:
            print(f"FutuAPI Exception: {e}")
        finally:
            quote_ctx.close()

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True