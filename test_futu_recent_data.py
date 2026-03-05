"""
测试Futu API获取最近的30分钟数据
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.FutuAPI import CFutuAPI
from Common.CEnum import KL_TYPE, AUTYPE
from datetime import datetime, timedelta

def test_futu_recent_30m():
    """测试Futu API获取最近的30分钟数据"""
    # 获取最近7天的数据
    end_time = datetime.now().strftime("%Y-%m-%d")
    begin_time = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    print(f"请求时间范围: {begin_time} 到 {end_time}")
    
    try:
        api = CFutuAPI(
            code="HK.00700",
            k_type=KL_TYPE.K_30M,
            begin_date=begin_time,
            end_date=end_time,
            autype=AUTYPE.QFQ
        )
        
        kl_data = list(api.get_kl_data())
        print(f"获取到 {len(kl_data)} 条30分钟数据")
        
        if kl_data:
            first_date = kl_data[0].time
            last_date = kl_data[-1].time
            print(f"数据日期范围: {first_date} 到 {last_date}")
        else:
            print("没有获取到数据")
            
    except Exception as e:
        print(f"获取数据失败: {e}")

if __name__ == "__main__":
    test_futu_recent_30m()