import sys
import asyncio
from pathlib import Path
from typing import Dict, List, Any
import json
import time

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from App.HKTradingController import HKTradingController
from App.MonitorController import MarketMonitorController

class WebTerminalManager:
    def __init__(self, broadcast_callback, loop=None):
        print("DEBUG: Initializing WebTerminalManager...")
        self.broadcast = broadcast_callback
        self.loop = loop or asyncio.get_event_loop()
        self.hk_status = {"available": 0.0, "total": 0.0, "positions": []}
        self.cn_status = {"available": 0.0, "total": 0.0, "positions": []}
        
        # Initialize HK Controller
        print("DEBUG: Setting up HK Controller...")
        self.hk_controller = HKTradingController(
            hk_watchlist_group="港股", # Default group
            dry_run=True,
            parent=None
        )
        self._setup_hk_signals()
        
        # Initialize A-Share Monitor
        print("DEBUG: Setting up CN Monitor...")
        self.cn_monitor = MarketMonitorController(
            watchlist_group="沪深",
            parent=None
        )
        self._setup_cn_signals()
        print("DEBUG: WebTerminalManager initialized.")

    def _setup_hk_signals(self):
        def on_funds(avail, total, pos):
            # Format positions to match frontend requirements
            self.hk_status = {
                "available": avail, 
                "total": total, 
                "positions": pos
            }
            self.send_status("HK_FUNDS", self.hk_status)

        self.hk_controller.log_message.connect(
            lambda msg: self.send_log("HK", msg)
        )
        self.hk_controller.funds_updated.connect(on_funds)

    def _setup_cn_signals(self):
        def on_funds(avail, total, pos):
            self.cn_status = {
                "available": avail, 
                "total": total, 
                "positions": pos
            }
            self.send_status("CN_FUNDS", self.cn_status)

        self.cn_monitor.log_message.connect(
            lambda msg: self.send_log("CN", msg)
        )
        self.cn_monitor.funds_updated.connect(on_funds)

    def send_log(self, source: str, message: str):
        payload = {
            "type": "log",
            "source": source,
            "message": message,
            "timestamp": time.time()
        }
        try:
            # Use run_coroutine_threadsafe to send from potentially background threads
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.broadcast(json.dumps(payload)), self.loop)
        except Exception:
            # Silent fail if loop is closed (shutdown)
            pass

    def send_status(self, type: str, data: Any):
        payload = {
            "type": "status_update",
            "update_type": type,
            "data": data
        }
        try:
            # Use run_coroutine_threadsafe to send from potentially background threads
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.broadcast(json.dumps(payload)), self.loop)
        except Exception:
            # Silent fail if loop is closed (shutdown)
            pass

    async def start_monitors(self):
        # Start controllers in background threads as they are blocking
        import threading
        print("DEBUG: Starting monitor threads...")
        
        # 1. Start HK Controller
        def start_hk():
            print("DEBUG: HK thread started.")
            # Initial fund sync to populate shadow ledger / positions
            # This is an async method, need to run it in the thread's event loop
            asyncio.run(self.hk_controller._sync_positions_async())
            print("DEBUG: HK initial fund query done.")
            # Start main trading loop
            self.hk_controller.run_scan_and_trade()
            
        threading.Thread(target=start_hk, daemon=True).start()
        
        # 2. Start CN Monitor
        def start_cn():
            print("DEBUG: CN thread started.")
            # Initial fund sync for A-Share
            # CN query_account_funds is a regular method putting in a queue
            self.cn_monitor.query_account_funds()
            print("DEBUG: CN initial fund query scheduled.")
            # Start main monitor loop
            self.cn_monitor.run_monitor_loop()
            
        threading.Thread(target=start_cn, daemon=True).start()
        print("DEBUG: Monitor threads spawned.")
        print("DEBUG: Monitor threads spawned.")

    def stop_monitors(self):
        self.hk_controller.stop()
        self.cn_monitor.stop()
