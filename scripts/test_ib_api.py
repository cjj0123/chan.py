import os
from ib_insync import IB, Stock, util
from dotenv import load_dotenv

def test_ib_connectivity():
    # 1. 加载配置
    load_dotenv()
    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_PORT", "4002"))
    client_id = int(os.getenv("IB_CLIENT_ID", "1"))

    ib = IB()
    print(f"🚀 正在尝试连接 IB Gateway ({host}:{port}, ID: {client_id})...")

    try:
        # 2. 连接
        ib.connect(host, port, clientId=client_id)
        print("✅ 连接成功！")

        # 3. 定义 AAPL 合约
        aapl = Stock('AAPL', 'SMART', 'USD')
        print(f"🔍 检查 AAPL 合约...")
        ib.qualifyContracts(aapl)

        # 4. 测试实时报价 (MktData)
        print("📡 请求 AAPL 实时报价...")
        # 切换到延迟数据请求（如果没有付费订阅，通常模拟账户也需要设置此项）
        ib.reqMarketDataType(3) # 3: Delayed
        
        ticker = ib.reqMktData(aapl, '', False, False)
        ib.sleep(2) # 等待数据到达
        
        if ticker.last:
            print(f"✅ 实时报价获取成功: ${ticker.last}")
        else:
            print(f"⚠️ 未获取到 Last Price，当前报价状态: Bid={ticker.bid}, Ask={ticker.ask}, Close={ticker.close}")

        # 5. 测试历史数据获取 (Historical Data)
        print("📊 正在下载 AAPL 最近 1 天的 1 小时 K 线...")
        bars = ib.reqHistoricalData(
            aapl, 
            endDateTime='', 
            durationStr='1 D',
            barSizeSetting='1 hour', 
            whatToShow='TRADES', 
            useRTH=True, 
            formatDate=1
        )
        
        if bars:
            print(f"✅ 历史数据获取成功，共获取 {len(bars)} 根 K 线。")
            print("最近一根 K 线数据:")
            last_bar = bars[-1]
            print(f"  时间: {last_bar.date}")
            print(f"  开盘: {last_bar.open}")
            print(f"  最高: {last_bar.high}")
            print(f"  最低: {last_bar.low}")
            print(f"  收盘: {last_bar.close}")
            print(f"  成交量: {last_bar.volume}")
        else:
            print("❌ 历史数据获取失败，未收到任何 K 线。")

    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
    finally:
        # 6. 断开连接
        if ib.isConnected():
            ib.disconnect()
            print("🔌 已断开 IB 连接。")

if __name__ == "__main__":
    test_ib_connectivity()
