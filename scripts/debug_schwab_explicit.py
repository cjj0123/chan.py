import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO)

from scripts.daily_hot_scanner import get_schwab_movers

try:
    print("\n--- Testing Schwab Movers ---")
    codes = get_schwab_movers(25)
    print(f"Resulting Codes ({len(codes)}): {codes}")
except Exception as e:
    print(f"Exception: {e}")
