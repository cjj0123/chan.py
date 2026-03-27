import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
import nest_asyncio

# Setup Path
root_path = str(Path(__file__).resolve().parent)
app_path = os.path.join(root_path, 'App')
sys.path.insert(0, root_path)
sys.path.insert(0, app_path)

from App.IBTradingController import IBTradingController

async def test_ib():
    print(f"Starting IB Test at {datetime.now()}")
    ctrl = IBTradingController(us_watchlist_group="美股")
    
    # Mock log message to print to console
    ctrl.log_message.connect(lambda msg: print(f"[LOG] {msg}"))
    
    print("Initializing loop...")
    # Manual trigger of _async_main part for debugging
    from ib_insync import IB
    ctrl.ib = IB()
    ctrl.client_id = 99 # Use a different ID to avoid conflict
    
    print(f"Connecting to {ctrl.host}:{ctrl.port} with ID {ctrl.client_id}...")
    try:
        # Use a timeout for connection
        await asyncio.wait_for(ctrl.ib.connectAsync(ctrl.host, ctrl.port, clientId=ctrl.client_id), timeout=10)
        print("Connected successfully!")
        
        # Test scan
        print("Triggering manual scan...")
        # Reducewatchlist to a few stocks for speed
        us_watchlist_codes = ['US.AAPL', 'US.TSLA', 'US.NVX']
        print(f"Testing scan for {us_watchlist_codes}...")
        
        # We need to mock _perform_strategy_scan_async slightly or just call it and see if it finds codes
        await ctrl._perform_strategy_scan_async(is_force_scan=True)
        print("Scan finished.")
        
    except asyncio.TimeoutError:
        print(f"Connection timed out at {ctrl.host}:{ctrl.port}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ctrl.ib and ctrl.ib.isConnected():
            ctrl.ib.disconnect()
            print("Disconnected.")

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(test_ib())
