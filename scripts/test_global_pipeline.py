import asyncio
import os
import sys
import logging
from ML.ModelTrainer import ModelTrainer

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_pipeline():
    """
    Tests the collection pipeline for a small subset of global stocks.
    """
    logger.info("🧪 Testing Global Collection Pipeline...")
    
    # Select a few representative stocks from each market
    test_watchlist = ["US.AAPL", "HK.00700", "SH.600000"]
    
    trainer = ModelTrainer(watchlist=test_watchlist)
    
    # Use a narrow date range for the test
    trainer.start_date = "2024-01-01"
    trainer.end_date = "2024-03-01"
    
    # Run collection
    trainer.collect_samples()
    
    # Check output
    if os.path.exists(trainer.train_data_file):
        import pandas as pd
        df = pd.read_csv(trainer.train_data_file)
        logger.info(f"✅ Success! Collected {len(df)} samples.")
        logger.info(f"Sample data columns: {df.columns[:10].tolist()}")
    else:
        logger.error("❌ Failed: Samples file not created.")

if __name__ == "__main__":
    sys.path.insert(0, os.getcwd())
    asyncio.run(test_pipeline())
