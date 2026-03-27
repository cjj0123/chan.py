import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from BacktestDataLoader import BacktestDataLoader

loader = BacktestDataLoader()
codes = ["HK.00700", "HK.00836"]
for code in codes:
    data = loader.load_kline_data(code, '5M', '2025-01-01', '2025-12-31')
    print(f"{code} 5M Data Count: {len(data)}")
