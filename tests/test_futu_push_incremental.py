import sys
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from config import CHAN_CONFIG

class MockAPI:
    def __init__(self, code, k_type, begin_date, end_date, autype):
        self.code = code
        self.k_type = k_type
        self.begin_date = begin_date
        self.end_date = end_date
        self.autype = autype

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass

    def get_kl_data(self):
        # Return 10 baseline K-lines
        base_time = datetime(2026, 3, 1, 9, 30)
        for i in range(10):
            dt = base_time + timedelta(minutes=i * 30)
            yield CKLine_Unit({
                DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute),
                DATA_FIELD.FIELD_OPEN: 100.0 + i,
                DATA_FIELD.FIELD_HIGH: 105.0 + i,
                DATA_FIELD.FIELD_LOW: 95.0 + i,
                DATA_FIELD.FIELD_CLOSE: 102.0 + i,
                DATA_FIELD.FIELD_VOLUME: 1000.0,
                DATA_FIELD.FIELD_TURNOVER: 100000.0,
                DATA_FIELD.FIELD_TURNRATE: 0.1
            })

def test_incremental_append_correct():
    print("🚀 Starting Correct Incremental Append Test (MOCK)...")
    
    code = "HK.00700"
    begin_time = "2026-03-01"
    
    # 1. Initialize CChan with trigger_step=False (default) to load history
    conf = CChanConfig(CHAN_CONFIG)
    conf.trigger_step = False 
    
    # 🐒 Monkeypatch CChan.GetStockAPI to support MockAPI
    from Chan import CChan as OriginalCChan
    OriginalCChan.GetStockAPI = lambda self: MockAPI

    print(f"📦 Initializing CChan (Mock) for {code} with trigger_step=False...")
    chan = OriginalCChan(
        code=code,
        begin_time=begin_time,
        data_src="mock", # Now okay because of monkeypatch
        lv_list=[KL_TYPE.K_30M],
        config=conf,
        autype=AUTYPE.QFQ
    )
    
    initial_klu_count = len(list(chan[0].klu_iter()))
    print(f"✅ Initial KLU count: {initial_klu_count}")
    
    if initial_klu_count == 0:
        print("❌ FAILURE: History not loaded!")
        sys.exit(1)
        
    # 2. Enable trigger_step for incremental updates
    print("⚙️ Enabling trigger_step for real-time pushes...")
    chan.conf.trigger_step = True
    for lv in chan.lv_list:
        chan.kl_datas[lv].step_calculation = True
        
    # 3. Simulate a new K-line push
    last_klu = list(chan[0].klu_iter())[-1]
    last_dt = datetime(last_klu.time.year, last_klu.time.month, last_klu.time.day, 
                        last_klu.time.hour, last_klu.time.minute)
    new_time = last_dt + timedelta(minutes=30)
    
    print(f"📥 Simulating push for time: {new_time}")
    
    k_data_dict = {
        DATA_FIELD.FIELD_TIME: CTime(new_time.year, new_time.month, new_time.day, new_time.hour, new_time.minute),
        DATA_FIELD.FIELD_OPEN: last_klu.close,
        DATA_FIELD.FIELD_HIGH: last_klu.close * 1.01,
        DATA_FIELD.FIELD_LOW: last_klu.close * 0.99,
        DATA_FIELD.FIELD_CLOSE: last_klu.close * 1.005,
        DATA_FIELD.FIELD_VOLUME: 100000.0,
        DATA_FIELD.FIELD_TURNOVER: 5000000.0,
        DATA_FIELD.FIELD_TURNRATE: 0.01
    }
    
    # 4. Append KL
    print("🧪 Appending new K-line unit...")
    chan.append_kl(k_data_dict, KL_TYPE.K_30M)
    
    # 5. Verify update
    updated_klu_count = len(list(chan[0].klu_iter()))
    print(f"✅ Updated KLU count: {updated_klu_count}")
    
    if updated_klu_count == initial_klu_count + 1:
        print("🎉 SUCCESS: Incremental update verified!")
    else:
        print(f"❌ FAILURE: Expected count {initial_klu_count + 1}, got {updated_klu_count}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        test_incremental_append_correct()
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
