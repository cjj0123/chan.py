import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ML.ModelTrainer import ModelTrainer

def run_subset():
    print("🚀 Running Quick 7% Label Collection on representative sub-pool...")
    
    # 选取 5 只高流动性标的作为样本缩影
    sub_watchlist = ["HK.00700", "HK.09988", "HK.03690", "US.AAPL", "US.NVDA"]
    
    trainer = ModelTrainer(watchlist=sub_watchlist)
    # 确保保存到独立测试 CSV 中避免污染
    trainer.train_data_file = "stock_cache/ml_data/train_samples_7p_subset.csv"
    trainer.model_prefix = "stock_cache/ml_data/model_test_7p_"
    
    # 彻底清除可能存在的旧数据防串号
    if os.path.exists(trainer.train_data_file):
        os.remove(trainer.train_data_file)
        
    trainer.collect_samples()
    print(f"✅ Subset Collection Complete! Data saved to {trainer.train_data_file}")
    
    # 立即触发这一份小样本的 7% 测试集训练
    print("\n🌲 Running XGBoost / LightGBM Training on subset...")
    trainer.train_all(target_label="label_7p_30d")
    print("🏁 Quick 7% testing scenario complete.")

if __name__ == "__main__":
    run_subset()
