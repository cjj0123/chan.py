#!/usr/bin/env python3
"""
测试美股下载功能
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from DataAPI.AkshareAPI import CAkshare
from Common.CEnum import AUTYPE, KL_TYPE

def test_us_stocks():
    print("正在测试美股下载...")
    try:
        # 测试已知的美股
        test_codes = ['US.AAPL', 'US.INTC', 'US.GOOG']
        
        for code in test_codes:
            print(f"\n测试 {code}...")
            try:
                # 转换为AKShare格式
                if code.startswith("US."):
                    akshare_code = "us." + code.split(".")[1].upper()
                else:
                    akshare_code = code
                    
                print(f"  AKShare代码: {akshare_code}")
                api = CAkshare(akshare_code, k_type=KL_TYPE.K_DAY, begin_date='2024-01-01', end_date='2024-12-31', autype=AUTYPE.QFQ)
                data_count = 0
                for kl_unit in api.get_kl_data():
                    data_count += 1
                    if data_count <= 3:  # 只显示前3条
                        print(f"  {kl_unit.time.year}-{kl_unit.time.month:02d}-{kl_unit.time.day:02d}: O={kl_unit.open:.2f}, H={kl_unit.high:.2f}, L={kl_unit.low:.2f}, C={kl_unit.close:.2f}")
                
                print(f"  总共获取到 {data_count} 条数据")
                
            except Exception as e:
                print(f"  ❌ 下载失败: {e}")
                import traceback
                traceback.print_exc()
                
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_us_stocks()