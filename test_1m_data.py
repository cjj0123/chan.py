import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from BacktestDataLoader import BacktestDataLoader

loader = BacktestDataLoader()
codes = ["HK.00700", "HK.00836", "HK.02688"]
for code in codes:
    data = loader.load_kline_data(code, '1M', '2025-01-01', '2025-12-31')
    print(f"{code} 1M Data Count: {len(data)}")
