import sys, os
from PyQt6.QtWidgets import QApplication

def run():
    app = QApplication(sys.argv)
    from App.IBTradingController import IBTradingController
    
    ctrl = IBTradingController(us_watchlist_group="美股")
    
    def on_log(msg):
        print(f"LOG: {msg}")
        
    ctrl.log_message.connect(on_log)
    print("Starting loop...")
    import threading
    t = threading.Thread(target=ctrl.run_trading_loop, daemon=True)
    t.start()
    
    import time
    time.sleep(5)
    print("Done")

try:
    run()
except Exception as e:
    import traceback
    traceback.print_exc()

