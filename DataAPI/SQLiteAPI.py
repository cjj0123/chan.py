"""
DataAPI for SQLite
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import sqlite3
from datetime import datetime
from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import str2float
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.CommonStockAPI import CCommonStockApi
from Trade.db_util import CChanDB


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
    valid_price = max(o, h, l, c)
    if valid_price <= 0:
        # 如果整根K线都是0，建议跳过或设为一个极小值（由Chan引擎过滤）
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
            # Get K-line data from AKShare
            ak_api = CAkshare(code, k_type=KL_TYPE.K_DAY, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
            kl_data = []
            for kl_unit in ak_api.get_kl_data():
                kl_data.append({
                    'code': code,
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