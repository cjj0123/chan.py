#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from DataAPI.FinnhubAPI import CFinnhubAPI
from Common.CEnum import KL_TYPE

def test_finnhub_fetch():
    print("🚀 Testing Finnhub API Integration...")
    
    # 测试代码: AAPL
    code = "US.AAPL"
    
    # 1. 测试日线数据 (2025-03-03 to 2025-03-07)
    print("\n[Test 1] Fetching Daily bars (2025-03-03 to 2025-03-07)...")
    api = CFinnhubAPI(code, k_type=KL_TYPE.K_DAY, begin_date="2025-03-03", end_date="2025-03-08")
    kl_data = api.get_kl_data()
    
    if kl_data:
        print(f"✅ Success: Received {len(kl_data)} daily bars.")
        for k in kl_data[:2]:
            print(f"   - {k.time}: O:{k.open} H:{k.high} L:{k.low} C:{k.close} V:{k.volume}")
    else:
        print("❌ Failed: No daily bars received.")

    # 2. 测试 30分钟线数据
    print("\n[Test 2] Fetching 30m bars (Last 2 days)...")
    api_30m = CFinnhubAPI(code, k_type=KL_TYPE.K_30M, begin_date="2025-03-05", end_date="2025-03-07")
    kl_data_30m = api_30m.get_kl_data()
    
    if kl_data_30m:
        print(f"✅ Success: Received {len(kl_data_30m)} 30m bars.")
        for k in kl_data_30m[:2]:
            print(f"   - {k.time}: O:{k.open} H:{k.high} L:{k.low} C:{k.close} V:{k.volume}")
    else:
        print("❌ Failed: No 30m bars received.")

    # 3. 测试空数据 (周末)
    print("\n[Test 3] Testing empty result (Weekend 2026-03-07 to 2026-03-08)...")
    api_empty = CFinnhubAPI(code, k_type=KL_TYPE.K_DAY, begin_date="2026-03-07", end_date="2026-03-08")
    kl_data_empty = api_empty.get_kl_data()
    if not kl_data_empty:
        print("✅ Success: Correctly returned empty for weekend.")
    else:
        print(f"❓ Unexpected: Received {len(kl_data_empty)} bars for weekend.")

if __name__ == "__main__":
    test_finnhub_fetch()
