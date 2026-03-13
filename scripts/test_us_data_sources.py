import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Common.StockUtils import get_default_data_sources, is_us_stock
from Common.CEnum import DATA_SRC

def test_us_priority():
    print("Testing US stock data source priority...")
    
    # Mock environment
    os.environ["IB_HOST"] = "127.0.0.1"
    
    code = "US.AAPL"
    sources = get_default_data_sources(code)
    
    print(f"Code: {code}")
    print(f"Is US: {is_us_stock(code)}")
    print(f"Sources: {sources}")
    
    expected = [DATA_SRC.IB, DATA_SRC.YFINANCE, "custom:SQLiteAPI.SQLiteAPI"]
    
    if sources == expected:
        print("✅ US Priority test PASSED")
    else:
        print(f"❌ US Priority test FAILED. Expected {expected}, got {sources}")

def test_hk_priority():
    print("\nTesting HK stock data source priority...")
    code = "HK.00700"
    sources = get_default_data_sources(code)
    
    print(f"Code: {code}")
    print(f"Is US: {is_us_stock(code)}")
    print(f"Sources: {sources}")
    
    if sources[0] == DATA_SRC.FUTU:
        print("✅ HK Priority test PASSED")
    else:
        print(f"❌ HK Priority test FAILED. Expected first source to be FUTU, got {sources[0]}")

if __name__ == "__main__":
    test_us_priority()
    test_hk_priority()
