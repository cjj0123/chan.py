"""
DataAPI for SQLite
"""
import pandas as pd
import sqlite3
from datetime import datetime
from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.CommonStockAPI import CCommonStockApi
from Trade.db_util import CChanDB


def convert_stock_code_for_akshare(code):
    """
    Convert stock code format from Futu/OpenD to AKShare format
    
    Args:
        code: Stock code in Futu format (e.g., "HK.02649", "SZ.300772", "SH.600000")
    
    Returns:
        str: Stock code in AKShare format (e.g., "hk.02649", "000001")
    """
    if code.startswith("HK."):
        # 港股: HK.02649 -> hk.02649
        return "hk." + code.split(".")[1]
    elif code.startswith("SZ.") or code.startswith("SH."):
        # A股: SZ.300772 -> 300772, SH.600000 -> 600000
        return code.split(".")[1]
    elif code.startswith("US."):
        # 美股: US.AAPL -> us.AAPL
        return "us." + code.split(".")[1].upper()
    else:
        # 如果已经是纯数字格式，直接返回
        return code


def create_item_dict_from_db(row, autype):
    """从数据库行创建 item dict"""
    item = {}
    
    # 处理时间
    date_val = row['date']
    if isinstance(date_val, str):
        dt = datetime.strptime(date_val, "%Y-%m-%d")
    else:
        dt = date_val
    
    item[DATA_FIELD.FIELD_TIME] = CTime(dt.year, dt.month, dt.day, 0, 0)
    
    # 提取价格
    o = str2float(row['open'])
    h = str2float(row['high'])
    l = str2float(row['low'])
    c = str2float(row['close'])
    
    # --- 核心修正逻辑：处理 0.0 价格 ---
    # 首先，确保所有价格至少为一个极小的正数，以防止后续计算出错
    EPSILON = 1e-6
    o = max(o, EPSILON)
    h = max(h, EPSILON)
    l = max(l, EPSILON)
    c = max(c, EPSILON)
    
    # 然后，确保价格之间的逻辑关系：low <= open/close <= high
    low_val = min(o, h, l, c)
    high_val = max(o, h, l, c)
    o = max(min(o, high_val), low_val)
    c = max(min(c, high_val), low_val)
    h = high_val
    l = low_val
    # --------------------------------

    item[DATA_FIELD.FIELD_OPEN] = o
    item[DATA_FIELD.FIELD_HIGH] = h
    item[DATA_FIELD.FIELD_LOW] = l
    item[DATA_FIELD.FIELD_CLOSE] = c
    item[DATA_FIELD.FIELD_VOLUME] = str2float(row['volume'])
    item[DATA_FIELD.FIELD_TURNOVER] = str2float(row.get('turnover', 0))
    item[DATA_FIELD.FIELD_TURNRATE] = str2float(row.get('turnrate', 0))

    return item


class SQLiteAPI(CCommonStockApi):
    """
    SQLite data API
    """

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        self.db = CChanDB()
        super(SQLiteAPI, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self):
        """
        get kline data from sqlite
        """
        if self.k_type != KL_TYPE.K_DAY:
            raise ValueError("Only day kline is supported for SQLiteAPI")
        
        sql = f"SELECT * FROM kline_day WHERE code = '{self.code}'"
        if self.begin_date:
            sql += f" AND date >= '{self.begin_date}'"
        if self.end_date:
            sql += f" AND date <= '{self.end_date}'"
        sql += " ORDER BY date"
            
        df = self.db.execute_query(sql)
        if not df.empty:
            # 遍历生成 K 线单元
            for _, row in df.iterrows():
                yield CKLine_Unit(create_item_dict_from_db(row, self.autype))
        else:
            return

    def SetBasciInfo(self):
        """设置基本信息"""
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass


def download_and_save_all_stocks(stock_codes, days=365):
    """
    Download and save all stock data to SQLite database
    
    Args:
        stock_codes: list of stock codes to download
        days: number of days to download, default 365
    """
    from datetime import datetime, timedelta
    from Trade.db_util import CChanDB
    from DataAPI.AkshareAPI import CAkshare
    from Common.CEnum import AUTYPE, KL_TYPE
    
    db = CChanDB()
    
    begin_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_time = datetime.now().strftime("%Y-%m-%d")
    
    for code in stock_codes:
        try:
            # 转换股票代码格式以适配AKShare
            akshare_code = convert_stock_code_for_akshare(code)
            
            # Get K-line data from AKShare
            ak_api = CAkshare(akshare_code, k_type=KL_TYPE.K_DAY, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
            kl_data = []
            for kl_unit in ak_api.get_kl_data():
                kl_data.append({
                    'code': code,  # 使用原始代码存储到数据库
                    'date': f"{kl_unit.time.year}-{kl_unit.time.month:02d}-{kl_unit.time.day:02d}",
                    'open': kl_unit.open,
                    'high': kl_unit.high,
                    'low': kl_unit.low,
                    'close': kl_unit.close,
                    'volume': kl_unit.volume,
                    'turnover': kl_unit.turnover,
                    'turnrate': getattr(kl_unit, 'turnrate', 0.0)
                })
            
            if kl_data:
                # Save to database
                df = pd.DataFrame(kl_data)
                # Insert or replace data in kline_day table
                with sqlite3.connect(db.db_path) as conn:
                    df.to_sql('kline_day', conn, if_exists='append', index=False)
                    
        except Exception as e:
            print(f"Failed to download {code}: {e}")
            continue