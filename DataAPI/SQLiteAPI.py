"""
DataAPI for SQLite
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from DataAPI.CommonStockAPI import CCommonStockApi
from Trade.db_util import CChanDB

class SQLiteAPI(CCommonStockApi):
    """
    SQLite data API
    """

    def __init__(self):
        self.db = CChanDB()

    def get_kl_data(self, code, start_date=None, end_date=None, k_type='day'):
        """
        get kline data from sqlite
        """
        if k_type != 'day':
            raise ValueError("Only day kline is supported for SQLiteAPI")
        
        sql = f"SELECT * FROM kline_day WHERE code = '{code}'"
        if start_date:
            sql += f" AND date >= '{start_date}'"
        if end_date:
            sql += f" AND date <= '{end_date}'"
            
        df = self.db.execute_query(sql)
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values('date').reset_index(drop=True)