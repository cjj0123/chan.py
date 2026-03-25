#!/usr/bin/env python3
"""
sync_all_history.py - 自动全量历史数据同步脚本 (用于机器学习训练数据储备)
执行方式: python3 sync_all_history.py --markets US HK CN --days 1825
可以配合 cron 放在夜间执行。
"""

import sys
import os
import argparse
import asyncio
import logging
import traceback
from datetime import datetime

# 配置路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_async
from DataAPI.FutuAPI import CFutuAPI
from ML.MarketComponentResolver import MarketComponentResolver

# 设置默认的 IB 环境变量，确保异步下载逻辑能被触发
if "IB_HOST" not in os.environ:
    os.environ["IB_HOST"] = "127.0.0.1"
if "IB_PORT" not in os.environ:
    os.environ["IB_PORT"] = "4002"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SyncHistory")

def make_log_callback():
    def _log(msg):
        logger.info(msg)
    return _log

async def main():
    parser = argparse.ArgumentParser(description="自动全局历史数据同步工具")
    parser.add_argument("--markets", nargs="+", default=["US", "HK", "CN"], help="指定要同步的市场，例如 US HK CN")
    parser.add_argument("--days", type=int, default=1825, help="同步的天数 (默认 1825 天, 约 5 年)")
    parser.add_argument("--timeframes", nargs="+", default=["day", "30m", "5m"], help="需要同步的周期")
    args = parser.parse_args()

    # ==============================================================
    # 核心逻辑：优先同步 Futu 自选股 (Watchlist)，保障实盘风控不罢工
    # ==============================================================
    logger.info("正在拉取 Futu 实时全量自选股列表...")
    watchlist_codes = []
    try:
        from Common.StockUtils import get_futu_watchlist_stocks
        watchlist_df = get_futu_watchlist_stocks()
        if not watchlist_df.empty:
            watchlist_codes = watchlist_df['代码'].tolist()
            logger.info(f"💡 本地共拉取到 {len(watchlist_codes)} 只 Futu 自选股")
    except Exception as e:
        logger.warning(f"⚠️ 拉取 Futu 自选股失败: {e}")

    # 获取全量训练样本（热点股、成分股等）
    resolver = MarketComponentResolver()
    targets = resolver.get_all_training_targets()
    
    extra_stocks = []
    for m in args.markets:
        m_upper = m.upper()
        if m_upper in targets:
            codes = targets[m_upper]
            logger.info(f"📍 目标市场 {m_upper}: 找到 {len(codes)} 只额外样本股")
            extra_stocks.extend(codes)
        else:
            logger.warning(f"⚠️ 未知市场: {m_upper}")

    # 去重处理，但保留顺序：自选股排在最前面
    seen = set()
    total_stocks = []
    # 1. 优先加入自选股
    for code in watchlist_codes:
        if code not in seen:
            total_stocks.append(code)
            seen.add(code)
    
    # 2. 加入其他样本股
    for code in extra_stocks:
        if code not in seen:
            total_stocks.append(code)
            seen.add(code)

    if not total_stocks:
        logger.error("❌ 未找到任何需要同步的股票，程序退出。")
        return

    logger.info(f"🚀 开始顺序同步，共计 {len(total_stocks)} 只股票 (自选股优先级最高)，深度 {args.days} 天，周期 {args.timeframes}...")
    
    # 修复：stop_check 必须是可调用的 (callable)
    def stop_check_func():
        return False
        
    log_cb = make_log_callback()

    try:
        await download_and_save_all_stocks_async(
            stock_codes=total_stocks,
            days=args.days,
            timeframes=args.timeframes,
            log_callback=log_cb,
            stop_check=stop_check_func,
            ib_client=None  # 将自动连接 IB (美股优先使用)
        )
        logger.info("🎉 恭喜！全市场数据历史同步已完成。")
    except Exception as e:
        logger.error(f"🚨 同步过程中发生崩溃: {e}\n{traceback.format_exc()}")
    finally:
        # 🛡️ 显式释放 Futu 连接资源
        CFutuAPI.close_all()

if __name__ == "__main__":
    if sys.platform != "win32":
        import nest_asyncio
        nest_asyncio.apply()
    
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n🛑 被用户手动中止。")
