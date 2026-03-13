import asyncio
import os
import sys
import logging
from ML.ModelTrainer import ModelTrainer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("global_collection.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def run_global_collection():
    """
    Executes the massive global data collection for AI training.
    Targets US (S&P500/Nasdaq100), HK (HSI/HSTech), and CN (CSI300).
    """
    logger.info("🚀 Starting Global AI Sample Collection (Target: 50,000+ samples)")
    
    # Initialize trainer
    # It will automatically resolve components via MarketComponentResolver in __init__
    trainer = ModelTrainer()
    
    logger.info(f"📋 Watchlist resolved: {len(trainer.watchlist)} symbols total.")
    
    # Define time range (3 years for deep learning)
    start_date = "2021-01-01"
    end_date = "2026-03-13" # Today's date approximation
    
    # Run collection
    # Note: collect_samples handles batching and SQLite bridging
    trainer.collect_samples(start_date=start_date, end_date=end_date)
    
    logger.info("✅ Global Collection Phase Complete.")

if __name__ == "__main__":
    # Ensure project root is in path
    sys.path.insert(0, os.getcwd())
    
    # Run the collection
    # Note: ModelTrainer.collect_samples is synchronous in its current implementation
    # but uses sync SQLite/DataAPI calls.
    asyncio.run(run_global_collection())
