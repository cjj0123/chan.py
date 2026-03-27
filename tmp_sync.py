import asyncio
import os
import sys
from pathlib import Path

# Fix path to root
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_async

async def main():
    print("🚀 Starting manual Schwab sync for sample US stks (15 days)...")
    # Sample common stocks
    codes = ["US.AAPL", "US.NVDA", "US.TSLA", "US.MSFT", "US.GOOGL", "US.AMZN", "US.META"]
    await download_and_save_all_stocks_async(codes, days=15)
    print("✅ Sync complete.")

if __name__ == "__main__":
    asyncio.run(main())
