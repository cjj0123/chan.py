import asyncio
import os
import sys
import logging
from ML.MarketComponentResolver import MarketComponentResolver
from DataAPI.SQLiteAPI import download_and_save_all_stocks_async

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("global_download.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def run_global_download():
    """
    Downloads historical data for all index components to populate SQLite database.
    """
    logger.info("📡 Resolving global index components for download...")
    resolver = MarketComponentResolver()
    targets = resolver.get_all_training_targets()
    
    all_codes = []
    for market, codes in targets.items():
        logger.info(f"Market {market}: Found {len(codes)} stocks.")
        all_codes.extend(codes)
    
    # Remove duplicates
    all_codes = list(set(all_codes))
    logger.info(f"🚀 Total unique stocks to download: {len(all_codes)}")
    
    # Define timeframe and range
    # 3 years of 30M and 5M data is ideal for Phase 10
    timeframes = ['30m', '5m'] # Use lowercase as expected by SQLiteAPI
    days = 1095 # ~3 years
    
    # Execute batch download
    # This uses the optimized async/batch logic for US stocks (IB) 
    # and sync fallback for HK/CN.
    await download_and_save_all_stocks_async(
        all_codes, 
        days=days, 
        timeframes=timeframes, 
        log_callback=logger.info
    )
    
    logger.info("✅ Global Historical Data Download Complete.")

if __name__ == "__main__":
    # Ensure project root is in path
    sys.path.insert(0, os.getcwd())
    
    # Run the download
    asyncio.run(run_global_download())
