import sys
import os
from datetime import datetime, timedelta
from Common.StockUtils import get_futu_watchlist_stocks
from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
from DataAPI.FutuAPI import CFutuAPI

# 解决 MonitorController 因缺少 5M 数据拦截交易的问题
# 仅下载最近 15 天的 30m 和 5m 数据，这不消耗“历史K线配额”，速度极快

def fast_sync():
    print("正在获取最新自选股列表...")
    try:
        watchlist_df = get_futu_watchlist_stocks()
        if watchlist_df.empty:
            print("⚠️ 自选股列表为空，请检查 Futu 登录状态")
            return
            
        codes = watchlist_df['代码'].tolist()
        print(f"🚀 发现 {len(codes)} 只自选股。开始快速补全共振数据 (15天深度, 30m/5m)...")
        
        # 15天周期通常在 300-500 根 K 线内，Futu 允许免费拉取，不计入 30天/1年 的历史配额限制
        download_and_save_all_stocks_multi_timeframe(
            codes, 
            days=15, 
            timeframes=['30m', '5m', 'day']
        )
        print("✅ 快速同步完成！MonitorController 现在应该可以正常进行 5M 共振验证了。")
    except Exception as e:
        print(f"❌ 同步失败: {e}")
    finally:
        # 🛡️ 显式关闭 Futu 连接，释放配额
        CFutuAPI.close_all()

if __name__ == "__main__":
    fast_sync()
