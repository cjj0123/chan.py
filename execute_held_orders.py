
import sys
import os
from futu import *

# Add current directory to path so we can import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from futu_sim_trading_midday import MiddayFutuTradingEngine, LUNCH_HOLD_FILE

def execute_held_orders():
    # Instantiate the engine (default dry_run=True)
    engine = MiddayFutuTradingEngine(dry_run=True)
    
    # Load the orders from file
    if not os.path.exists(LUNCH_HOLD_FILE):
        print(f"❌ File {LUNCH_HOLD_FILE} not found.")
        engine.close()
        return

    print(f"🚀 Loading orders from {LUNCH_HOLD_FILE}...")
    engine.load_lunch_orders()
    
    if not engine.lunch_hold_orders:
        print("✅ No orders to execute.")
        engine.close()
        return

    print(f"⚡️ Executing {len(engine.lunch_hold_orders)} orders via Futu Simulation API...")
    
    # Call the method that processes the list
    # This method calls execute_sim_order for each item
    engine.execute_lunch_orders()
    
    engine.close()
    print("✅ Done.")

if __name__ == "__main__":
    execute_held_orders()
