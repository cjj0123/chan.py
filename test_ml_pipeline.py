import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ML.ModelTrainer import ModelTrainer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def test_training_pipeline():
    # 使用极小集合进行验证
    test_watchlist = ["HK.00700", "US.AAPL", "SH.600519"]
    trainer = ModelTrainer(watchlist=test_watchlist, start_date="2024-01-01", end_date="2024-03-31")
    
    print("🚀 [TEST] Starting sample collection with small watchlist...")
    trainer.collect_samples(freq='30M')
    
    if os.path.exists(trainer.train_data_file):
        import pandas as pd
        df = pd.read_csv(trainer.train_data_file)
        print(f"✅ Samples collected: {len(df)}")
        print(f"Columns: {df.columns.tolist()[:15]}...")
        
        # Verify MAE-aware labels and market features
        if "label_3p_15d" in df.columns:
            pos_ratio = df["label_3p_15d"].mean()
            print(f"📈 Positive label ratio: {pos_ratio:.2%}")
            
        mkt_cols = [c for c in df.columns if c.startswith("mkt_index_")]
        if mkt_cols:
            print(f"🌐 Market context features found: {mkt_cols}")
        else:
            print("❌ Warning: No market context features found!")
    else:
        print("❌ Error: Samples were not saved to CSV!")

if __name__ == "__main__":
    test_training_pipeline()
