from Common.CEnum import KL_TYPE
from KLine.KLine_Unit import CKLine_Unit

class MockAPI:
    def __init__(self, kl_data):
        self.kl_data = kl_data

    def get_kline(self, code, k_type, begin_date, end_date, autype):
        for kl in self.kl_data.get(k_type, []):
            yield kl

