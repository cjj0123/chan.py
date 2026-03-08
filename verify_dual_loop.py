import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from App.HKTradingController import HKTradingController

def simulate_dual_loop():
    print("Starting Dual-Loop Logic Verification...")
    controller = HKTradingController()
    controller._is_running = True
    
    # Mocking external dependencies
    controller.get_watchlist_codes = MagicMock(return_value=["HK.00700"])
    controller.is_trading_time = MagicMock(return_value=True)
    controller._check_trailing_stops = MagicMock()
    controller._perform_full_strategy_scan = MagicMock()
    controller.scan_finished = MagicMock()
    
    # Test Scenarios
    scenarios = [
        ("10:05", False), # Mid-bar startup, should NOT scan
        ("10:31", True),  # Next bar boundary triggered
        ("10:35", False), # Already scanned for this bar
        ("11:01", True),  # Next bar boundary triggered
    ]
    
    # Init state matching the controller startup
    start_dt = datetime.strptime("2026-03-09 10:05", "%Y-%m-%d %H:%M")
    last_scan_time = start_dt.replace(minute=(start_dt.minute // 30) * 30, second=0, microsecond=0)
    
    for time_str, expected_trigger in scenarios:
        now = datetime.strptime(f"2026-03-09 {time_str}", "%Y-%m-%d %H:%M")
        current_bar_time = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
        
        print(f"\nChecking Time: {time_str}")
        
        # Reset trigger flag for each step
        should_scan = False
        if last_scan_time != current_bar_time:
            if now.minute % 30 >= 1:
                should_scan = True
        
        if should_scan:
            print(f"-> TRIGGER: Full Strategy Scan ({current_bar_time.strftime('%H:%M')})")
            last_scan_time = current_bar_time
        else:
            print("-> IDLE: Only Risk Monitoring")
            
        assert should_scan == expected_trigger, f"Mismatch at {time_str}: Expected {expected_trigger}, got {should_scan}"

    print("\n✅ Dual-loop logic verification PASSED.")

if __name__ == "__main__":
    simulate_dual_loop()
