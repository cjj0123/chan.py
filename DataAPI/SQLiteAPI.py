"""
DataAPI for SQLite
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import sqlite3
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