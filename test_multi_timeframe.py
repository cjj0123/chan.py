"""
测试多时间级别数据读取
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import SQLiteAPI
from Common.CEnum import KL_TYPE

def test_timeframe_reading():
    """测试不同时间级别的数据读取"""
    # 测试股票代码（假设数据库中有这些数据）
    test_codes = ['HK.00700', 'SZ.000001', 'SH.600000']
    
    timeframes = [
        (KL_TYPE.K_DAY, "日线"),
        (KL_TYPE.K_30M, "30分钟线"), 
        (KL_TYPE.K_5M, "5分钟线"),
        (KL_TYPE.K_1M, "1分钟线")
    ]
    
    for code in test_codes:
        print(f"\n=== 测试股票: {code} ===")
        for k_type, name in timeframes:
            try:
                api = SQLiteAPI(code, k_type=k_type)
                data = list(api.get_kl_data())
                print(f"{name}: {len(data)} 条数据")
            except Exception as e:
                print(f"{name}: 错误 - {e}")

if __name__ == "__main__":
    test_timeframe_reading()