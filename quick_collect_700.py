import os
import sys
from ML.ModelTrainer import ModelTrainer

# Ensure project root is in path
sys.path.append(os.getcwd())

def main():
    stocks = ["HK.00700"]
    print(f"🚀 Testing collection for {stocks} (5M)...")
    
    trainer = ModelTrainer(watchlist=stocks)
    trainer.collect_samples(freq='5M')
    print("✅ Collection complete.")

if __name__ == "__main__":
    main()
