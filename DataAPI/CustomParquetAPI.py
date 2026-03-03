from typing import Iterable, List
from datetime import datetime
import time
import random
import pandas as pd

from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.CommonStockAPI import CCommonStockApi

class CCustomParquetAPI(CCommonStockApi):
    _cached_kl_units: List[CKLine_Unit] = []

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CCustomParquetAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        
    @classmethod
    def robust_load_from_parquet(cls, file_path):
        """
        [EvoMap Strategy Fusion] 
        - Exponential Backoff for IO retries
        - Median-based anomaly detection for data cleaning
        """
        retries = 3
        df = None
        for i in range(retries):
            try:
                df = pd.read_parquet(file_path)
                break
            except Exception as e:
                if i == retries - 1: raise e
                time.sleep(random.uniform(0.1, 0.5) * (2 ** i))
        
        if df is None or df.empty:
            return []

        # 列名标准化 (针对 KeyError: 'time')
        df.columns = [c.lower() for c in df.columns]
        col_map = {'time_key': 'time', 'vol': 'volume', 'amount': 'turnover'}
        df.rename(columns=col_map, inplace=True)

        # 异常检测：计算价格变动的中位数
        df['price_change'] = df['close'].diff().abs()
        median_change = df['price_change'].median()
        if median_change > 0:
            outliers = df[df['price_change'] > median_change * 15] 
            if not outliers.empty:
                print(f"[EVOMAP-RECOVERY] Warning: Found {len(outliers)} price anomalies. Data cleaning suggested.")

        cls._cached_kl_units = []
        for _, row in df.iterrows():
            ts = pd.to_datetime(row['time'])
            klu = CKLine_Unit({
                DATA_FIELD.FIELD_TIME: CTime(ts.year, ts.month, ts.day, ts.hour, ts.minute),
                DATA_FIELD.FIELD_OPEN: float(row['open']),
                DATA_FIELD.FIELD_HIGH: float(row['high']),
                DATA_FIELD.FIELD_LOW: float(row['low']),
                DATA_FIELD.FIELD_CLOSE: float(row['close']),
                DATA_FIELD.FIELD_VOLUME: float(row.get('volume', 0.0)),
            })
            cls._cached_kl_units.append(klu)
        return cls._cached_kl_units

    def get_kl_data(self) -> Iterable[CKLine_Unit]:
        begin_time_obj = None
        if self.begin_date:
            try:
                dt_begin = datetime.strptime(self.begin_date, "%Y-%m-%d")
                begin_time_obj = CTime(dt_begin.year, dt_begin.month, dt_begin.day, 0, 0)
            except: pass

        end_time_obj = None
        if self.end_date:
            try:
                dt_end = datetime.strptime(self.end_date, "%Y-%m-%d")
                end_time_obj = CTime(dt_end.year, dt_end.month, dt_end.day, 23, 59)
            except: pass

        for klu in self._cached_kl_units:
            if begin_time_obj and klu.time < begin_time_obj: continue
            if end_time_obj and klu.time > end_time_obj: continue
            yield klu

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        cls._cached_kl_units = [] 
