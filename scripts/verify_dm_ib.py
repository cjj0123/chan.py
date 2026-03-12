from DataAPI.DataManager import get_data_manager
from Common.CEnum import KL_TYPE, AUTYPE
from datetime import datetime

def verify_dm_ib():
    dm = get_data_manager()
    code = "US.AAPL"
    
    print(f"🔍 正在通过 DataManager 测试 {code}...")
    
    # 1. 测试实时价格
    print("\n--- 1. 测试实时价格 ---")
    price = dm.get_current_price(code)
    if price:
        print(f"✅ 获取成功: {code} 当前报价 = ${price}")
    else:
        print("❌ 获取实时价格失败")

    # 2. 测试 K 线获取 (触发 API 补充)
    print("\n--- 2. 测试 K 线数据获取 (15分钟线) ---")
    begin_date = (datetime.now()).strftime("%Y-%m-%d") # 强制从今天开始触发 API
    klines = dm.get_kline_data(code, KL_TYPE.K_15M, begin_date=begin_date)
    
    if klines:
        print(f"✅ 获取成功，共 {len(klines)} 根 K 线")
        last_klu = klines[-1]
        print(f"  最新 K 线时间: {last_klu.time.to_str()}")
        print(f"  最新收盘价: {last_klu.close}")
    else:
        print("❌ 获取 K 线数据失败")

if __name__ == "__main__":
    verify_dm_ib()
