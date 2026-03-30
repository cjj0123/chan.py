import sys
import asyncio
from pathlib import Path
from typing import Dict, List, Any
import json
import time
import logging
from datetime import datetime, timedelta
import os

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from App.HKTradingController import HKTradingController
from App.MonitorController import MarketMonitorController
from Common.CEnum import KL_TYPE, DATA_SRC
from Chan import CChan
from Plot.PlotDriver import CPlotDriver

class WebTerminalManager:
    def __init__(self, broadcast_callback, loop=None):
        print("DEBUG: Initializing WebTerminalManager...")
        self.broadcast = broadcast_callback
        self.loop = loop or asyncio.get_event_loop()
        self.hk_status = {"available": 0.0, "total": 0.0, "today_pl": 0.0, "positions": []}
        self.cn_status = {"available": 0.0, "total": 0.0, "today_pl": 0.0, "positions": []}
        self.system_summary = {
            "daily_pnl": 0.0,
            "daily_pnl_pct": 0.0,
            "active_symbols": 0,
            "compute_load": 0.0,
            "risk_exposure": "LOW"
        }
        self.HKD_TO_CNY = 0.92
        self.MAX_CAPACITY = 300
        self.start_time = time.time()
        
        # Initialize HK Controller
        # Initialize HK Controller
        print("DEBUG: Setting up HK Controller...")
        from config import TRADING_CONFIG
        hk_group = TRADING_CONFIG.get('hk_watchlist_group', '港股')
        self.hk_controller = HKTradingController(
            hk_watchlist_group=hk_group,
            dry_run=True,
            parent=None
        )
        self._setup_hk_signals()
        
        # Initialize A-Share Monitor
        print("DEBUG: Setting up CN Monitor...")
        cn_group = TRADING_CONFIG.get('cn_watchlist_group', '沪深')
        self.cn_monitor = MarketMonitorController(
            watchlist_group=cn_group,
            parent=None
        )
        self._setup_cn_signals()
        
        # Trading State (Initial Sync)
        self.trading_config = {
            "HK": {
                "auto_trade": not self.hk_controller.dry_run, # Inverted logic for simplicity in UI
                "live_mode": not self.hk_controller.dry_run
            },
            "CN": {
                "auto_trade": self.cn_monitor.trading_enabled,
                "live_mode": self.cn_monitor.trd_env == 1 # TrdEnv.REAL is 1
            }
        }
        
        print("DEBUG: WebTerminalManager initialized.")

    def _setup_hk_signals(self):
        def on_funds(avail, total, today_pl, pos):
            self.hk_status = {
                "available": avail, 
                "total": total, 
                "positions": pos,
                "today_pl": today_pl
            }
            self.send_status("HK_FUNDS", self.hk_status)
            self._update_system_summary()

        self.hk_controller.log_message.connect(
            lambda msg: self.send_log("HK", msg)
        )
        self.hk_controller.funds_updated.connect(on_funds)

    def _setup_cn_signals(self):
        def on_funds(avail, total, today_pl, pos):
            self.cn_status = {
                "available": avail, 
                "total": total, 
                "positions": pos,
                "today_pl": today_pl
            }
            self.send_status("CN_FUNDS", self.cn_status)
            self._update_system_summary()

        self.cn_monitor.log_message.connect(
            lambda msg: self.send_log("CN", msg)
        )
        self.cn_monitor.funds_updated.connect(on_funds)

    def _update_system_summary(self):
        # Calculate consolidated daily P&L (HKD to CNY conversion)
        hk_pnl_cny = self.hk_status.get("today_pl", 0.0) * self.HKD_TO_CNY
        cn_pnl_cny = self.cn_status.get("today_pl", 0.0)
        total_pnl = hk_pnl_cny + cn_pnl_cny
        
        # Calculate total assets in CNY
        total_assets_cny = (self.hk_status.get("total", 0.0) * self.HKD_TO_CNY) + self.cn_status.get("total", 0.0)
        pnl_pct = (total_pnl / total_assets_cny * 100) if total_assets_cny > 0 else 0.0
        
        # Active symbols from both HK and CN watchlists
        active_count = 0
        try:
            hk_watchlist = self.hk_controller.get_watchlist_data()
            cn_watchlist = {}
            if hasattr(self.cn_monitor, 'get_watchlist_data'):
                cn_watchlist = self.cn_monitor.get_watchlist_data()
            active_count = len(hk_watchlist) + len(cn_watchlist)
            
            if active_count == 0:
                print(f"DEBUG: Watchlist count is 0. HK Group: {self.hk_controller.hk_watchlist_group}, CN Group: {self.cn_monitor.watchlist_group}")
        except Exception as e:
            print(f"ERROR: Failed to fetch watchlist: {e}")
            active_count = 0

        # Compute Load based on 300 capacity
        load = min(100.0, (active_count / self.MAX_CAPACITY) * 100.0)
        
        # Risk Exposure based on Market Value / Total Assets
        total_mkt_val_cny = 0.0
        for p in self.hk_status.get("positions", []):
            total_mkt_val_cny += p.get("mkt_value", 0.0) * self.HKD_TO_CNY
        for p in self.cn_status.get("positions", []):
            total_mkt_val_cny += p.get("mkt_value", 0.0)
            
        exposure_ratio = (total_mkt_val_cny / total_assets_cny) if total_assets_cny > 0 else 0.0
        if exposure_ratio > 0.8: risk = "HIGH"
        elif exposure_ratio > 0.4: risk = "MED"
        else: risk = "LOW"
        
        self.system_summary = {
            "daily_pnl": round(total_pnl, 2),
            "daily_pnl_pct": round(pnl_pct, 2),
            "active_symbols": active_count,
            "compute_load": round(load, 1),
            "risk_exposure": risk,
            "trading_status": self.trading_config
        }
        self.send_status("SYSTEM_SUMMARY", self.system_summary)


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
        
        # Initial trigger for system summary (don't wait for signals)
        self.loop.call_later(2, self._update_system_summary)
        
        # Periodic update for active symbols count (every 60s)
        async def periodic_status_sync():
            while True:
                await asyncio.sleep(60)
                self._update_system_summary()
        
        asyncio.create_task(periodic_status_sync())

        # 1. Start HK Controller
        def start_hk():
            print("DEBUG: HK thread started.")
            # Initial fund sync to populate shadow ledger / positions
            # This is an async method, need to run it in the thread's event loop
            try:
                asyncio.run(asyncio.wait_for(self.hk_controller._sync_positions_async(), timeout=30.0))
                print("DEBUG: HK initial fund query done.")
            except Exception as e:
                print(f"DEBUG: HK initial fund query failed or timed out: {e}")
                self.hk_controller.log_message.emit(f"⚠️ 港股初始持仓同步未完成，可能是 OpenD 连接问题。后台将继续尝试。({e})")
            
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

    def get_recent_signals(self, limit=50):
        """Fetch signals from the last 12h that occurred during trading hours."""
        from Trade.db_util import CChanDB
        db = CChanDB()
        
        # Use Python to get the local cutoff time to avoid SQLite timezone mismatch
        cutoff_time = (datetime.now() - timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')
        query = "SELECT * FROM trading_signals WHERE add_date >= ? ORDER BY add_date DESC LIMIT ?"
        
        try:
            df = db.execute_query(query, (cutoff_time, limit))
            if df.empty:
                return []
            
            results = []
            for _, row in df.iterrows():
                try:
                    raw_date = row['add_date']
                    # Use pandas aware handling if it's already a Timestamp
                    if hasattr(raw_date, 'to_pydatetime'):
                        dt = raw_date.to_pydatetime()
                    elif isinstance(raw_date, str):
                        dt = datetime.strptime(raw_date, '%Y-%m-%d %H:%M:%S')
                    else:
                        dt = raw_date
                    
                    # Exclude weekends
                    if dt.weekday() >= 5: 
                        continue
                    
                    # Check trading hours
                    time_str = dt.strftime('%H:%M')
                    is_morning = "09:30" <= time_str <= "12:00"
                    is_afternoon = "13:00" <= time_str <= "16:00"
                    
                    if is_morning or is_afternoon:
                        results.append(row.to_dict())
                except Exception as e:
                    logging.error(f"Error processing signal row: {e}")
                    results.append(row.to_dict()) # Fallback
            
            return results
        except Exception as e:
            logging.error(f"Error fetching signals from DB: {e}")
            return []

    def generate_analysis_chart(self, symbol: str, lv_str: str = '30M'):
        """Generate a Chanlun chart with high-precision bottleneck diagnostics."""
        start_total = time.time()
        try:
            # Map string level to KL_TYPE
            lv_map = {
                '1M': KL_TYPE.K_1M,
                '5M': KL_TYPE.K_5M,
                '30M': KL_TYPE.K_30M,
                '60M': KL_TYPE.K_60M,
                'DAY': KL_TYPE.K_DAY,
                'WEEK': KL_TYPE.K_WEEK,
            }
            target_lv = lv_map.get(lv_str.upper(), KL_TYPE.K_30M)
            
            # Market routing - Now Unified via Hybrid API
            symbol = symbol.upper()
            if symbol.startswith("HK.") or symbol.startswith("SH.") or symbol.startswith("SZ.") or symbol.startswith("US."):
                src = "custom:HybridFutuAPI.HybridFutuAPI"
            else:
                # Handle raw digit input by appending prefix and using Hybrid source
                if any(c.isdigit() for c in symbol) and len(symbol) <= 6:
                    if len(symbol) == 5: symbol = f"HK.{symbol}"
                    elif symbol.startswith('6'): symbol = f"SH.{symbol}"
                    else: symbol = f"SZ.{symbol}"
                else: symbol = f"US.{symbol}"
                src = "custom:HybridFutuAPI.HybridFutuAPI"
            
            days_map = {
                KL_TYPE.K_DAY: 365,
                KL_TYPE.K_60M: 120,
                KL_TYPE.K_30M: 90,
                KL_TYPE.K_5M: 30,
                KL_TYPE.K_1M: 7,
            }
            lookback_days = days_map.get(target_lv, 90)
            
            # STEP 1: CChan Initialization (Data Fetching & Calculation)
            t_chan_start = time.time()
            chan = CChan(
                code=symbol,
                begin_time=(datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d"),
                data_src=src,
                lv_list=[target_lv],
                config=None
            )
            t_chan_end = time.time()
            calc_time = t_chan_end - t_chan_start
            
            # STEP 2: Plot Generation
            t_plot_start = time.time()
            plot_config = {
                target_lv: {
                    'plot_kline': True, 'plot_bi': True, 'plot_seg': True,
                    'plot_zs': True, 'plot_bsp': True, 'plot_macd': True,
                }
            }
            # Balanced figure for web (14x8)
            plot_para = {'figure': {'w': 16, 'h': 9, 'macd_h': 0.25}}
            
            driver = CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)
            
            charts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "App/charts")
            os.makedirs(charts_dir, exist_ok=True)
            
            filename = f"analyze_{symbol.replace('.', '_')}_{lv_str}.png"
            filepath = os.path.join(charts_dir, filename)
            
            driver.save2img(filepath)
            t_plot_end = time.time()
            plot_time = t_plot_end - t_plot_start
            
            total_time = time.time() - start_total
            print(f"📊 [PROFILER] {symbol} Analysis: Total={total_time:.2f}s | Calc={calc_time:.2f}s | Plot={plot_time:.2f}s")
            
            return {
                "success": True,
                "url": f"/charts/{filename}",
                "symbol": symbol,
                "lv": lv_str,
                "metrics": {
                    "calculation_s": round(calc_time, 2),
                    "plotting_s": round(plot_time, 2),
                    "total_s": round(total_time, 2)
                },
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logging.error(f"Failed to generate analysis chart for {symbol}: {e}")
            return {"success": False, "error": str(e)}

    def stop_monitors(self):
        self.hk_controller.stop()
        self.cn_monitor.stop()

    def get_trading_config(self):
        return self.trading_config

    def set_trading_config(self, market: str, auto_trade: bool = None, live_mode: bool = None):
        """Update trading configuration and re-init context if mode changed."""
        from futu import TrdEnv
        if market == "HK":
            if auto_trade is not None:
                # For HK, we use dry_run to control both. 
                # If auto_trade is True, we might want live_mode to be configurable.
                # Project's existing logic: dry_run=True means Simulate.
                pass 
            
            if live_mode is not None:
                new_env = TrdEnv.REAL if live_mode else TrdEnv.SIMULATE
                if self.hk_controller.trd_env != new_env:
                    print(f"DEBUG: Switching HK environment to {new_env}")
                    self.hk_controller.trd_env = new_env
                    self.hk_controller.dry_run = not live_mode
                    # Reset context to force re-login/re-init
                    self.hk_controller._trd_ctx = None
                    self.hk_controller._quote_ctx = None
            
            # HK auto_trade mapping
            if auto_trade is not None:
                # We'll use a custom property if needed, but for now align with dry_run
                # If they want "auto" but "sim", it's still dry_run=True in this codebase's current state
                pass

        elif market == "CN":
            if live_mode is not None:
                new_env = TrdEnv.REAL if live_mode else TrdEnv.SIMULATE
                if self.cn_monitor.trd_env != new_env:
                    print(f"DEBUG: Switching CN environment to {new_env}")
                    self.cn_monitor.trd_env = new_env
                    # Reset context
                    self.cn_monitor.trd_ctx = None
                    self.cn_monitor.quote_ctx = None
            
            if auto_trade is not None:
                self.cn_monitor.trading_enabled = auto_trade

        # Update local state
        if auto_trade is not None: self.trading_config[market]["auto_trade"] = auto_trade
        if live_mode is not None: self.trading_config[market]["live_mode"] = live_mode
        
        self._update_system_summary()
        return self.trading_config[market]

    def execute_manual_order(self, market: str, symbol: str, action: str, price: float, qty: int):
        """Forward manual order to the specific market controller."""
        print(f"DEBUG: Executing manual order: {market} {symbol} {action} {qty}@{price}")
        if market == "HK":
            self.hk_controller.execute_manual_order(symbol, action, price, qty)
        elif market == "CN":
            self.cn_monitor.execute_manual_order(symbol, action, price, qty)
        return {"success": True, "message": "Order queued"}

    def emergency_stop(self, market: str):
        """Cancel orders and close positions for the market."""
        if market == "HK":
            # HKTradingController might need a close_all_positions method if not present
            if hasattr(self.hk_controller, 'close_all_positions'):
                self.hk_controller.close_all_positions()
            else:
                self.send_log("HK", "Emergency Stop: close_all_positions not implemented for HK")
        elif market == "CN":
            self.cn_monitor.close_all_positions()
        return {"success": True, "message": f"Emergency stop initiated for {market}"}
