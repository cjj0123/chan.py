import logging
import asyncio
from PyQt6.QtWidgets import QApplication
import sys

# Configure logging
logging.basicConfig(level=logging.INFO)

from App.USTradingController import USTradingController
from App.HKTradingController import HKTradingController

def main():
    app = QApplication(sys.argv)
    print("Testing HKTradingController initialization...")
    try:
        hk_ctrl = HKTradingController(dry_run=True)
        print("HK Controller initialized successfully.")
        
        # Test property access (should not crash, but might fail to connect to Futu if OpenD is off, which is fine to catch)
        print(f"Lazy Quote Context: {hk_ctrl.quote_ctx}")
    except Exception as e:
        print(f"HK Controller test failed: {e}")

    print("Testing USTradingController initialization...")
    try:
        us_ctrl = USTradingController()
        print("US Controller initialized successfully.")
        
        # Check new attributes
        print(f"Chart generation lock: {hasattr(us_ctrl, 'chart_generation_lock')}")
        print(f"Notified signals file: {hasattr(us_ctrl, 'notified_signals_file')}")
    except Exception as e:
        print(f"US Controller test failed: {e}")

if __name__ == '__main__':
    main()
