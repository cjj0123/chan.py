import pandas as pd
from datetime import datetime  # 必须导入标准库的 datetime
from futu import * 
from DataAPI.CommonStockAPI import CCommonStockApi
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

class CFutuAPI(CCommonStockApi):
    def __init__(self, code, k_type, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CFutuAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        
        # 1. 类型映射
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
        # 1. 格式化股票代码
        # 将 chan.py 的小写 sh.600000 转换为富途的大写 SH.600000
        stock_code = str(self.code).upper() 
        
        # 自动补全逻辑
        if '.' not in stock_code:
            if len(stock_code) == 5: 
                stock_code = f"HK.{stock_code}"  # 5位 -> 港股
            elif len(stock_code) == 6:
                # 简单推断：6开头是沪市，0/3开头是深市 (仅作简单示例)
                if stock_code.startswith('6'):
                    stock_code = f"SH.{stock_code}"
                else:
                    stock_code = f"SZ.{stock_code}"
        
        # 3. 建立连接
        quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        
        try:
            f_ktype = self.type_map.get(self.k_type, SubType.K_DAY)
            f_autype = self.autype_map.get(self.autype, AuType.QFQ)
            
            # 4. 动态订阅 (必须订阅对应级别)
            ret_sub, err_message = quote_ctx.subscribe([stock_code], [f_ktype], subscribe_push=False)
            if ret_sub != RET_OK:
                print(f"❌ [FutuAPI] 订阅失败: {err_message}")
                return

            # 5. 获取数据 (限制1000根)
            ret, data = quote_ctx.get_cur_kline(stock_code, 1000, f_ktype, f_autype)

            if ret == RET_OK:
                # 时间过滤
                if self.begin_date:
                    start_ts = str(self.begin_date)
                    data = data[data['time_key'] >= start_ts]

                for _, row in data.iterrows():
                    # 【核心修正】解析时间字符串 -> 拆解为 CTime 需要的整数参数
                    # Futu 返回格式通常为 "2023-01-01 09:30:00"
                    time_str = row['time_key']
                    try:
                        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        # 容错：有些日线可能没有时分秒
                        dt = datetime.strptime(time_str, "%Y-%m-%d")

                    item_dict = {
                        # 修正点：分别传入 年, 月, 日, 时, 分
                        DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                        
                        DATA_FIELD.FIELD_OPEN: float(row['open']),
                        DATA_FIELD.FIELD_HIGH: float(row['high']),
                        DATA_FIELD.FIELD_LOW: float(row['low']),
                        DATA_FIELD.FIELD_CLOSE: float(row['close']),
                        DATA_FIELD.FIELD_VOLUME: float(row['volume']),
                        DATA_FIELD.FIELD_TURNOVER: float(row['turnover']),
                        DATA_FIELD.FIELD_TURNRATE: float(row['turnover_rate'])
                    }
                    yield CKLine_Unit(item_dict)
            else:
                print(f"❌ [FutuAPI] 获取数据失败: {data}")
                
        except Exception as e:
            print(f"🔥 [FutuAPI] 运行异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            quote_ctx.close()

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True