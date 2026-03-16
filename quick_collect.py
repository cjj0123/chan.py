import os
import sys
from ML.ModelTrainer import ModelTrainer

# Ensure project root is in path
sys.path.append(os.getcwd())

def main():
    # Read stocks with data
    with open("stocks_with_data.txt", "r") as f:
        stocks = [line.strip() for line in f if line.strip()]
    
    print(f"🚀 Found {len(stocks)} stocks in DB. Starting collection (5M)...")
    
    trainer = ModelTrainer(watchlist=stocks, end_date="2026-12-31")
    trainer.collect_samples(freq='5M', end_date="2026-12-31")
    print("✅ Collection complete.")

if __name__ == "__main__":
    main()
