from DataAPI.SQLiteAPI import _download_us_stock_data_with_timeframe
from Common.CEnum import KL_TYPE
import os

def test_us_download_priority():
    code = "US.AAPL"
    # 我们只需要测试逻辑分发是否正确到达 IB
    # 由于真实下载需要连接，我们可以观察日志输出
    print(f"🔄 测试 {code} 下载优先级逻辑...")
    
    # 强制设置环境
    os.environ["IB_HOST"] = "127.0.0.1"
    
    begin_time = "2026-03-01"
    end_time = "2026-03-02"
    
    kl_data, source = _download_us_stock_data_with_timeframe(code, begin_time, end_time, KL_TYPE.K_DAY)
    
    print(f"\n📢 最终结果:")
    print(f"使用的源: {source}")
    if kl_data:
        print(f"获取到数据条数: {len(kl_data)}")
    else:
        print("未获取到数据 (可能是因为週末或未连接真实 Gateway，但重点是查看日志中的源尝试顺序)")

if __name__ == "__main__":
    test_us_download_priority()
