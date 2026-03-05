"""
测试美股30分钟数据下载
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import _download_us_stock_data_with_timeframe
from Common.CEnum import KL_TYPE
from datetime import datetime, timedelta

def test_us_stock_30m():
    """测试美股30分钟数据下载"""
    code = "US.AAPL"
    k_type = KL_TYPE.K_30M
    
    # 获取最近30天的数据
    end_time = datetime.now().strftime("%Y-%m-%d")
    begin_time = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    print(f"请求美股 {code} 30分钟数据: {begin_time} 到 {end_time}")
    
    try:
        kl_data, source = _download_us_stock_data_with_timeframe(code, begin_time, end_time, k_type)
        if kl_data:
            print(f"✅ 成功下载 {len(kl_data)} 条数据，来源: {source}")
            if len(kl_data) > 0:
                first_date = kl_data[0].time
                last_date = kl_data[-1].time
                print(f"数据日期范围: {first_date} 到 {last_date}")
        else:
            print("❌ 无数据返回")
    except Exception as e:
        print(f"❌ 下载失败: {e}")

if __name__ == "__main__":
    test_us_stock_30m()