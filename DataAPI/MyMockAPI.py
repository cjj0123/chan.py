from KLine.KLine_Unit import CKLine_Unit

from Common.CTime import CTime

class MyMockAPI:
    def __init__(self, code, k_type, begin_date, end_date, autype):
        pass

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

    def get_kl_data(self):
        # We read from a global or class variable for simplicity in testing
        if not hasattr(self.__class__, 'df_slice') or self.__class__.df_slice is None:
            return
            
        for _, row in self.__class__.df_slice.iterrows():
            # parse time correctly to CTime
            time_str = str(row['time_key'])
            import datetime
            dt_obj = datetime.datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            
            yield CKLine_Unit({
                "time_key": CTime(dt_obj.year, dt_obj.month, dt_obj.day, dt_obj.hour, dt_obj.minute),
                "open": row['open'],
                "high": row['high'],
                "low": row['low'],
                "close": row['close'],
                "volume": row['volume'],
            })
