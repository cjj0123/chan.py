import asyncio
import logging
import sqlite3
import os
import sys
import time
from datetime import datetime, timedelta

# Project Root
sys.path.append(os.getcwd())

from ML.MarketComponentResolver import MarketComponentResolver
from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe, download_and_save_all_stocks_async
from Common.CEnum import KL_TYPE

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sync_completion.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("CompleteSync")

async def main():
    resolver = MarketComponentResolver()
    targets = resolver.get_all_training_targets()
    
    all_expected = set()
    for codes in targets.values():
        all_expected.update(codes)
    
    logger.info(f"Target count: {len(all_expected)} stocks")
    
    conn = sqlite3.connect('chan_trading.db')
    
    # 1. Identify missing Day/30m/5m data
    missing_tasks = [] # List of (code, timeframes)
    
    for code in sorted(list(all_expected)):
        needed_tfs = []
        for tf_name in ['day', '30m', '5m']:
            table_name = f"kline_{tf_name}"
            cursor = conn.cursor()
            cursor.execute(f"SELECT 1 FROM {table_name} WHERE code = ? LIMIT 1", (code,))
            if not cursor.fetchone():
                needed_tfs.append(tf_name)
        
        if needed_tfs:
            missing_tasks.append((code, needed_tfs))
            
    logger.info(f"Found {len(missing_tasks)} stocks needing completion.")
    
    # 2. Process non-US stocks first (they use different APIs with more lenient limits)
    others = [(c, tfs) for c, tfs in missing_tasks if not c.startswith("US.")]
    if others:
        logger.info(f"Processing {len(others)} non-US stocks...")
        for i, (code, tfs) in enumerate(others):
            logger.info(f"[{i+1}/{len(others)}] Completing {code} for {tfs}")
            download_and_save_all_stocks_multi_timeframe(
                [code], days=1825, timeframes=tfs, log_callback=logger.info
            )
            # Small gap
            time.sleep(1)

    # 3. Process US stocks with EXTREME pacing (IB limits)
    us_stocks = [(c, tfs) for c, tfs in missing_tasks if c.startswith("US.")]
    if us_stocks:
        logger.info(f"Processing {len(us_stocks)} US stocks with enhanced pacing (15s delay)...")
        # Ensure IB env
        if "IB_HOST" not in os.environ: os.environ["IB_HOST"] = "127.0.0.1"
        if "IB_PORT" not in os.environ: os.environ["IB_PORT"] = "4002"
        
        for i, (code, tfs) in enumerate(us_stocks):
            logger.info(f"🚀 [{i+1}/{len(us_stocks)}] IB-Sync: {code} for {tfs}")
            try:
                # Use the async downloader but for single stock to strictly control pacing
                await download_and_save_all_stocks_async(
                    [code], days=1825, timeframes=tfs, log_callback=logger.info
                )
            except Exception as e:
                logger.error(f"❌ Failed {code}: {e}")
            
            # Crucial: IB Pacing Violation (Code 420) is triggered by > 50 hist requests / 10 mins
            # 15 seconds * 50 = 750 seconds (12.5 mins). This is safe.
            logger.info(f"⏳ Waiting 15s to respect IB pacing...")
            await asyncio.sleep(15)

    logger.info("🎉 All completion tasks finished.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
