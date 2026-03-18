import sys
import os
import pandas as pd
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DataAPI.DataManager import get_data_manager
from DataAPI.AkshareAPI import CAkshare
from Common.CEnum import KL_TYPE, AUTYPE

def prepare_indexes():
    dm = get_data_manager()
    cache_dir = "stock_cache"
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
        
    # [Proxy Code, Akshare Code, Market Name]
    indexes = [
        ["HK.02800", "hk.02800", "HK"],
        ["US.QQQ", "us.QQQ", "US"],
        ["SH.510300", "sh.510300", "CN"]
    ]
    freqs = [KL_TYPE.K_30M, KL_TYPE.K_5M]
    freq_names = {KL_TYPE.K_30M: "30M", KL_TYPE.K_5M: "5M"}
    
    # 最近 2 年数据 (30M/5M 的历史通常有限，保证最近 1-2 年即可)
    begin_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    for proxy_code, ak_code, market in indexes:
        for freq in freqs:
            f_name = freq_names[freq]
            parquet_path = os.path.join(cache_dir, f"{proxy_code}_K_{f_name}.parquet")
            
            print(f"📡 Processing {proxy_code} ({f_name})...")
            
            # 策略：首选 Akshare (因为其对 A 股和部分指数的历史数据更友好)
            klines = []
            try:
                print(f"  - Trying Akshare for {ak_code}...")
                ak_api = CAkshare(ak_code, freq, begin_date, end_date, AUTYPE.QFQ)
                klines = list(ak_api.get_kl_data())
            except Exception as e:
                print(f"  - Akshare failed: {e}")
            
            # 如果 Akshare 失败或数据太少，尝试 Futu (DataManager)
            if len(klines) < 100:
                print(f"  - Data too sparse ({len(klines)}), trying DataManager (Futu)...")
                try:
                    klines = dm.get_kline_data(proxy_code, freq, begin_date, end_date)
                except Exception as e:
                    print(f"  - DataManager failed: {e}")
            
            if not klines:
                print(f"❌ No data found for {proxy_code} ({f_name}) from any source.")
                continue
                
            # Convert to DataFrame for Parquet saving
            data_list = []
            for k in klines:
                data_list.append({
                    "time_key": k.time.to_str(),
                    "open": k.open,
                    "high": k.high,
                    "low": k.low,
                    "close": k.close,
                    "volume": k.volume
                })
            
            df = pd.DataFrame(data_list)
            # Remove duplicates
            df = df.drop_duplicates(subset=['time_key']).sort_values('time_key')
            
            df.to_parquet(parquet_path)
            print(f"✅ Saved {len(df)} bars to {parquet_path}")

if __name__ == "__main__":
    prepare_indexes()
