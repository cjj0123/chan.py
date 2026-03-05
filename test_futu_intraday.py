"""
测试富途API获取分钟级别数据
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.FutuAPI import CFutuAPI
from Common.CEnum import KL_TYPE, AUTYPE
from datetime import datetime, timedelta

def test_futu_intraday():
    """测试富途API获取分钟级别数据"""
    # 测试股票代码
    test_code = "HK.00700"  # 腾讯控股
    
    # 计算最近的时间范围
    end_time = datetime.now().strftime("%Y-%m-%d")
    begin_time = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    timeframes = [
        (KL_TYPE.K_30M, "30分钟线"),
        (KL_TYPE.K_5M, "5分钟线"), 
        (KL_TYPE.K_1M, "1分钟线")
    ]
    
    for k_type, name in timeframes:
        try:
            print(f"\n=== 测试 {name} ===")
            api = CFutuAPI(test_code, k_type=k_type, begin_date=begin_time, end_date=end_time, autype=AUTYPE.QFQ)
            data = list(api.get_kl_data())
            print(f"{name}: 获取到 {len(data)} 条数据")
            if data:
                print(f"第一条数据时间: {data[0].time}")
                print(f"最后一条数据时间: {data[-1].time}")
        except Exception as e:
            print(f"{name}: 错误 - {e}")

if __name__ == "__main__":
    test_futu_intraday()