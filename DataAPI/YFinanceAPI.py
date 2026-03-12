import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from .CommonStockAPI import CCommonStockApi
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

class CYFinanceAPI(CCommonStockApi):
    def __init__(self, code, k_type, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CYFinanceAPI, self).__init__(code, k_type, begin_date, end_date, autype)
        
        # Mapping KL_TYPE to yfinance interval
        self.type_map = {
            KL_TYPE.K_1M: '1m',
            KL_TYPE.K_5M: '5m',
            KL_TYPE.K_15M: '15m',
            KL_TYPE.K_30M: '30m',
            KL_TYPE.K_60M: '1h',
            KL_TYPE.K_DAY: '1d',
            KL_TYPE.K_WEEK: '1wk',
            KL_TYPE.K_MON: '1mo',
        }

    def get_kl_data(self):
        ticker_str = self.code.upper()
        if ticker_str.startswith("US."):
            ticker_str = ticker_str.split(".")[-1]
        
        interval = self.type_map.get(self.k_type, '1d')
        
        # Format dates
        start_date = self.begin_date.split(' ')[0] if self.begin_date else (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        end_date = self.end_date.split(' ')[0] if self.end_date else datetime.now().strftime("%Y-%m-%d")
        
        # yfinance specific limitations check
        # For 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, it only provides data for limited days back.
        # However, for 1h it's usually 730 days. For 1m it's 7 days.
        
        try:
            ticker = yf.Ticker(ticker_str)
            # Use auto_adjust for QFQ-like behavior in yfinance
            df = ticker.history(start=start_date, end=end_date, interval=interval, auto_adjust=True)
            
            if not df.empty:
                for idx, row in df.iterrows():
                    # idx is a DatetimeIndex
                    dt = idx.to_pydatetime()
                    
                    item_dict = {
                        DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                        DATA_FIELD.FIELD_OPEN: float(row['Open']),
                        DATA_FIELD.FIELD_HIGH: float(row['High']),
                        DATA_FIELD.FIELD_LOW: float(row['Low']),
                        DATA_FIELD.FIELD_CLOSE: float(row['Close']),
                        DATA_FIELD.FIELD_VOLUME: float(row['Volume']),
                        DATA_FIELD.FIELD_TURNOVER: float(row['Close']) * float(row['Volume']), # Approx turnover
                        DATA_FIELD.FIELD_TURNRATE: 0.0
                    }
                    yield CKLine_Unit(item_dict)
            else:
                print(f"⚠️ [YFinanceAPI] No data for {ticker_str} at {interval} from {start_date} to {end_date}")
                
        except Exception as e:
            print(f"🔥 [YFinanceAPI] Error: {e}")
            raise e

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

if __name__ == "__main__":
    # Test block
    from Common.CEnum import KL_TYPE
    api = CYFinanceAPI("AAPL", KL_TYPE.K_DAY, "2023-01-01", "2023-01-10")
    for klu in api.get_kl_data():
        print(klu.time, klu.close)
