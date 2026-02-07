import akshare as ak
import pandas as pd
import datetime

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit
from .CommonStockAPI import CCommonStockApi

def create_item_dict(row, autype):
    """增加异常价格修正逻辑"""
    item = {}
    date_val = row.get('日期', row.get('时间'))
    
    if isinstance(date_val, (pd.Timestamp, datetime.datetime, datetime.date)):
        dt = date_val
    else:
        dt = pd.to_datetime(str(date_val))

    item[DATA_FIELD.FIELD_TIME] = CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
    
    # 提取价格
    o = str2float(row['开盘'])
    h = str2float(row['最高'])
    l = str2float(row['最低'])
    c = str2float(row['收盘'])
    
    # --- 核心修正逻辑：处理 0.0 价格 ---
    # 找出这四个价格中的最大值，如果最大值都为0，说明这根K线完全无效
    valid_price = max(o, h, l, c)
    if valid_price <= 0:
        # 如果整根K线都是0，建议跳过或设为一个极小值（由Chan引擎过滤）
        # 这里我们赋予一个默认值，防止计算崩溃
        o = h = l = c = 0.001 
    else:
        # 如果只有部分字段为0（比如开盘价），用收盘价或有效价格填充它
        if o <= 0: o = c if c > 0 else valid_price
        if h <= 0: h = valid_price
        if l <= 0: l = min(p for p in [o, h, c] if p > 0)
        if c <= 0: c = o
    # --------------------------------

    item[DATA_FIELD.FIELD_OPEN] = o
    item[DATA_FIELD.FIELD_HIGH] = h
    item[DATA_FIELD.FIELD_LOW] = l
    item[DATA_FIELD.FIELD_CLOSE] = c
    item[DATA_FIELD.FIELD_VOLUME] = str2float(row['成交量'])
    item[DATA_FIELD.FIELD_TURNOVER] = str2float(row.get('成交额', 0))

    if '换手率' in row:
        item[DATA_FIELD.FIELD_TURNRATE] = str2float(row['换手率'])

    return item

class CAkshare(CCommonStockApi):
    """使用 akshare 获取多市场、多级别数据"""

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CAkshare, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self):
        """获取K线数据核心逻辑"""
        adjust_dict = {AUTYPE.QFQ: "qfq", AUTYPE.HFQ: "hfq", AUTYPE.NONE: ""}
        adjust = adjust_dict.get(self.autype, "qfq")
        period = self.__convert_type()

        # 格式化日期
        start_date = self.begin_date.replace("-", "") if self.begin_date else "19900101"
        end_date = self.end_date.replace("-", "") if self.end_date else "20991231"

        df = pd.DataFrame()

        try:
            # 1. 港股逻辑
            if self.code.startswith("hk."):
                symbol = self.code.split(".")[-1]
                df = ak.stock_hk_hist(symbol=symbol, period=period, start_date=start_date, end_date=end_date, adjust=adjust)
            
            # 2. 美股逻辑
            elif self.code.startswith("us."):
                symbol = self.code.split(".")[-1].upper()
                # 优先使用新浪接口获取历史长数据
                df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
                df['日期'] = pd.to_datetime(df['date'])
                df = df.rename(columns={'open': '开盘', 'high': '最高', 'low': '最低', 'close': '收盘', 'volume': '成交量'})
                df = df[(df['日期'] >= pd.to_datetime(self.begin_date)) & (df['日期'] <= pd.to_datetime(self.end_date))]

            # 3. A股逻辑
            else:
                # 清洗代码，只保留数字
                symbol = "".join(filter(str.isdigit, self.code))
                
                if period in ['daily', 'weekly', 'monthly']:
                    # A股 日线/周线/月线
                    df = ak.stock_zh_a_hist(symbol=symbol, period=period, start_date=start_date, end_date=end_date, adjust=adjust)
                else:
                    # A股 分钟线 (1, 5, 15, 30, 60)
                    # 注意：分钟线接口通常只返回最近一段时间的数据
                    df = ak.stock_zh_a_hist_min_em(symbol=symbol, period=period, adjust=adjust)
                    df['时间'] = pd.to_datetime(df['时间'])
                    # 过滤用户指定的时间起点
                    if self.begin_date:
                        df = df[df['时间'] >= pd.to_datetime(self.begin_date)]

        except Exception as e:
            print(f"[ERROR] 从 AKShare 获取数据失败: {e}")
            df = pd.DataFrame()

        if df.empty:
            print(f"[WARNING] {self.code} 返回数据为空，请检查代码或时间段。")
            return

        # 遍历生成 K 线单元
        for _, row in df.iterrows():
            yield CKLine_Unit(create_item_dict(row, self.autype))

    def SetBasciInfo(self):
        """设置基本信息"""
        self.name = self.code
        self.is_stock = True # 默认设为 True，AKShare 历史接口通常个股与指数通用

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

    def __convert_type(self):
        """将缠论 KL_TYPE 转换为 AKShare 所需的 period 参数"""
        _dict = {
            KL_TYPE.K_DAY: 'daily',
            KL_TYPE.K_WEEK: 'weekly',
            KL_TYPE.K_MON: 'monthly',
            KL_TYPE.K_1M: '1',
            KL_TYPE.K_5M: '5',
            KL_TYPE.K_15M: '15',
            KL_TYPE.K_30M: '30',
            KL_TYPE.K_60M: '60',
        }
        if self.k_type not in _dict:
            raise Exception(f"AKShare 接口不支持级别: {self.k_type}")
        return _dict[self.k_type]