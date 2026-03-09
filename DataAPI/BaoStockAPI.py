import baostock as bs
import datetime

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import kltype_lt_day, str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


def create_item_dict(data, column_name):
    for i in range(len(data)):
        data[i] = parse_time_column(data[i]) if i == 0 else str2float(data[i])
    return dict(zip(column_name, data))


def parse_time_column(inp):
    # 20210902113000000
    # 2021-09-13
    if len(inp) == 10:
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = minute = 0
    elif len(inp) == 17:
        year = int(inp[:4])
        month = int(inp[4:6])
        day = int(inp[6:8])
        hour = int(inp[8:10])
        minute = int(inp[10:12])
    elif len(inp) == 19:
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = int(inp[11:13])
        minute = int(inp[14:16])
    else:
        raise Exception(f"unknown time column from baostock:{inp}")
    return CTime(year, month, day, hour, minute)


def GetColumnNameFromFieldList(fileds: str):
    _dict = {
        "time": DATA_FIELD.FIELD_TIME,
        "date": DATA_FIELD.FIELD_TIME,
        "open": DATA_FIELD.FIELD_OPEN,
        "high": DATA_FIELD.FIELD_HIGH,
        "low": DATA_FIELD.FIELD_LOW,
        "close": DATA_FIELD.FIELD_CLOSE,
        "volume": DATA_FIELD.FIELD_VOLUME,
        "amount": DATA_FIELD.FIELD_TURNOVER,
        "turn": DATA_FIELD.FIELD_TURNRATE,
    }
    return [_dict[x] for x in fileds.split(",")]


class CBaoStock(CCommonStockApi):
    is_connect = None

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CBaoStock, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self):
        # 天级别以上才有详细交易信息
        if kltype_lt_day(self.k_type):
            if not self.is_stock:
                raise Exception("没有获取到数据，注意指数是没有分钟级别数据的！")
            fields = "time,open,high,low,close"
        else:
            fields = "date,open,high,low,close,volume,amount,turn"
        autype_dict = {AUTYPE.QFQ: "2", AUTYPE.HFQ: "1", AUTYPE.NONE: "3"}
        # BaoStock 仅支持 YYYY-MM-DD 格式的日期字符串
        start_date_str = self.begin_date.split(' ')[0] if self.begin_date else ""
        end_date_str = self.end_date.split(' ')[0] if self.end_date else ""
        
        rs = bs.query_history_k_data_plus(
            code=self.code,
            fields=fields,
            start_date=start_date_str,
            end_date=end_date_str,
            frequency=self.__convert_type(),
            adjustflag=autype_dict[self.autype],
        )
        if rs.error_code != '0':
            raise Exception(rs.error_msg)
        while rs.error_code == '0' and rs.next():
            row_data = rs.get_row_data()
            item_dict = create_item_dict(row_data, GetColumnNameFromFieldList(fields))
            
            # 手动执行精确的时间过滤（BaoStock API 仅支持按天过滤）
            try:
                dt_item = item_dict[DATA_FIELD.FIELD_TIME]
                # CTime 转 datetime 以便比较
                dt_obj = datetime.datetime(dt_item.year, dt_item.month, dt_item.day, dt_item.hour, dt_item.minute)
                
                if self.begin_date:
                    dt_begin = datetime.datetime.strptime(self.begin_date, "%Y-%m-%d %H:%M:%S") if ' ' in self.begin_date else datetime.datetime.strptime(self.begin_date, "%Y-%m-%d")
                    if dt_obj < dt_begin: continue
                if self.end_date:
                    dt_end = datetime.datetime.strptime(self.end_date, "%Y-%m-%d %H:%M:%S") if ' ' in self.end_date else datetime.datetime.strptime(self.end_date, "%Y-%m-%d")
                    if dt_obj > dt_end: continue
            except:
                pass
                
            yield CKLine_Unit(item_dict)

    def SetBasciInfo(self):
        rs = bs.query_stock_basic(code=self.code)
        if rs.error_code != '0':
            raise Exception(rs.error_msg)
        code, code_name, ipoDate, outDate, stock_type, status = rs.get_row_data()
        self.name = code_name
        self.is_stock = (stock_type == '1')

    @classmethod
    def do_init(cls):
        if not cls.is_connect:
            cls.is_connect = bs.login()

    @classmethod
    def do_close(cls):
        if cls.is_connect:
            bs.logout()
            cls.is_connect = None

    def __convert_type(self):
        _dict = {
            KL_TYPE.K_DAY: 'd',
            KL_TYPE.K_WEEK: 'w',
            KL_TYPE.K_MON: 'm',
            KL_TYPE.K_5M: '5',
            KL_TYPE.K_15M: '15',
            KL_TYPE.K_30M: '30',
            KL_TYPE.K_60M: '60',
        }
        return _dict[self.k_type]
