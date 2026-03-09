import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from Common.CEnum import KL_TYPE, DATA_SRC, AUTYPE
from Chan import CChan
from ChanConfig import CChanConfig

def test_yfinance_intraday():
    print("--- Testing yfinance Intraday (5M) ---")
    try:
        config = CChanConfig()
        # Use more recent date
        chan = CChan(
            code="AAPL",
            begin_time="2026-03-01", 
            data_src=DATA_SRC.YFINANCE,
            lv_list=[KL_TYPE.K_5M],
            config=config,
            autype=AUTYPE.QFQ
        )
        print(f"Result: {len(chan[0])} K-lines fetched.")
        if len(chan[0]) > 0:
            print(f"Last K-line: {chan[0][-1][-1].time} Close: {chan[0][-1][-1].close}")
    except Exception as e:
        print(f"Error: {e}")

def test_polygon_daily():
    print("\n--- Testing Polygon Daily ---")
    # Note: This will only work if POLYGON_API_KEY is set in .env or environment
    from config import API_CONFIG
    if not API_CONFIG.get('POLYGON_API_KEY'):
        print("Skipping Polygon test (No API Key)")
        return

    try:
        config = CChanConfig()
        # Use more recent date (> 2024-03-08 for 2-year limit)
        chan = CChan(
            code="TSLA",
            begin_time="2025-01-01",
            end_time="2025-01-10",
            data_src=DATA_SRC.POLYGON,
            lv_list=[KL_TYPE.K_DAY],
            config=config,
            autype=AUTYPE.QFQ
        )
        print(f"Result: {len(chan[0])} K-lines fetched.")
        for kline in chan[0]:
            print(f"Time: {kline[-1].time} Close: {kline[-1].close}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_yfinance_intraday()
    test_polygon_daily()
