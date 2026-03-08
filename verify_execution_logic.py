import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from App.HKTradingController import HKTradingController

def test_session_logic():
    controller = HKTradingController()
    is_cts = controller.is_in_continuous_trading_session()
    print(f"Current Time: {datetime.now()}")
    print(f"Is in CTS: {is_cts}")
    
    # Manually test specific times
    test_times = [
        "2026-03-09 10:00:00", # Morning CTS
        "2026-03-09 12:30:00", # Lunch break
        "2026-03-09 14:00:00", # Afternoon CTS
        "2026-03-09 18:00:00", # After hours
        "2026-03-08 10:00:00", # Sunday (Today)
    ]
    
    print("\nTime testing:")
    for ts in test_times:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        # Temporarily mock datetime.now() inside the method logic for testing
        morning_start = datetime.strptime("09:30", "%H:%M").time()
        morning_end = datetime.strptime("12:00", "%H:%M").time()
        afternoon_start = datetime.strptime("13:00", "%H:%M").time()
        afternoon_end = datetime.strptime("16:00", "%H:%M").time()
        
        current_time = dt.time()
        is_morning = morning_start <= current_time <= morning_end
        is_afternoon = afternoon_start <= current_time <= afternoon_end
        is_trading_day = dt.weekday() < 5
        
        result = is_trading_day and (is_morning or is_afternoon)
        print(f"Time: {ts}, Expected CTS: {result}")

if __name__ == "__main__":
    test_session_logic()
