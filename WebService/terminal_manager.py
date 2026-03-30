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
from App.IBTradingController import IBTradingController
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
        self.us_status = {"available": 0.0, "total": 0.0, "today_pl": 0.0, "positions": []}
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
        self.recent_logs = []
        
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

        # Initialize US IB Controller
        print("DEBUG: Setting up US IB Controller...")
        us_group = TRADING_CONFIG.get('us_watchlist_group', '美股')
        self.us_controller = IBTradingController(
            us_watchlist_group=us_group,
            discord_bot=None
        )
        self._setup_us_signals()
        
        # Trading State (Initial Sync)
        self.trading_config = {
            "HK": {
                "auto_trade": not getattr(self.hk_controller, '_is_paused', False),
                "live_mode": not self.hk_controller.dry_run
            },
            "CN": {
                "auto_trade": self.cn_monitor.trading_enabled,
                "live_mode": self.cn_monitor.trd_env == 1 # TrdEnv.REAL is 1
            },
            "US": {
                "auto_trade": not getattr(self.us_controller, '_is_paused', False),
                "live_mode": self.us_controller.is_live_account_mode()
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

    def _setup_us_signals(self):
        def on_funds(avail, total, pos):
            self.us_status = {
                "available": avail,
                "total": total,
                "positions": [self._normalize_us_position(p) for p in pos],
                "today_pl": 0.0
            }
            self.send_status("US_FUNDS", self.us_status)
            self._update_system_summary()

        self.us_controller.log_message.connect(
            lambda msg: self.send_log("US", msg)
        )
        self.us_controller.funds_updated.connect(on_funds)

    def _normalize_us_position(self, pos: Dict[str, Any]) -> Dict[str, Any]:
        symbol = str(pos.get("symbol") or pos.get("code") or "").upper()
        code = symbol if symbol.startswith("US.") else f"US.{symbol}" if symbol else "US.UNKNOWN"
        return {
            "code": code,
            "name": pos.get("name") or symbol or code,
            "market": "US",
            "qty": int(pos.get("qty", 0)),
            "mkt_value": float(pos.get("mkt_value", 0.0) or 0.0),
            "avg_cost": float(pos.get("avg_cost", pos.get("cost_price", 0.0)) or 0.0),
            "mkt_price": float(pos.get("mkt_price", pos.get("last_price", 0.0)) or 0.0),
            "currency": "USD",
        }

    def _update_system_summary(self):
        # Calculate consolidated daily P&L (HKD to CNY conversion)
        hk_pnl_cny = self.hk_status.get("today_pl", 0.0) * self.HKD_TO_CNY
        cn_pnl_cny = self.cn_status.get("today_pl", 0.0)
        total_pnl = hk_pnl_cny + cn_pnl_cny
        
        # Calculate total assets in CNY
        usd_to_cny = 7.2
        total_assets_cny = (
            (self.hk_status.get("total", 0.0) * self.HKD_TO_CNY)
            + self.cn_status.get("total", 0.0)
            + (self.us_status.get("total", 0.0) * usd_to_cny)
        )
        pnl_pct = (total_pnl / total_assets_cny * 100) if total_assets_cny > 0 else 0.0
        
        # Active symbols from HK / CN / US watchlists
        active_count = 0
        try:
            hk_watchlist = self.hk_controller.get_watchlist_data()
            cn_watchlist = {}
            if hasattr(self.cn_monitor, 'get_watchlist_data'):
                cn_watchlist = self.cn_monitor.get_watchlist_data()
            us_watchlist = {}
            if hasattr(self.us_controller, 'get_watchlist_data'):
                us_watchlist = self.us_controller.get_watchlist_data()
            active_count = len(hk_watchlist) + len(cn_watchlist) + len(us_watchlist)
            
            if active_count == 0:
                print(
                    f"DEBUG: Watchlist count is 0. HK Group: {self.hk_controller.hk_watchlist_group}, "
                    f"CN Group: {self.cn_monitor.watchlist_group}, US Group: {self.us_controller.watchlist_group}"
                )
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
        for p in self.us_status.get("positions", []):
            total_mkt_val_cny += p.get("mkt_value", 0.0) * usd_to_cny
            
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
        time_str = datetime.now().strftime('%H:%M:%S')
        payload = {
            "type": "log",
            "source": source,
            "message": message,
            "timestamp": time.time(),
            "time_str": time_str
        }
        self.recent_logs.append(payload)
        if len(self.recent_logs) > 1000:
            self.recent_logs.pop(0)
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

        # 3. Start US IB Controller
        def start_us():
            print("DEBUG: US thread started.")
            self.us_controller.query_account_funds()
            print("DEBUG: US initial fund query scheduled.")
            self.us_controller.run_trading_loop()

        threading.Thread(target=start_us, daemon=True).start()
        print("DEBUG: Monitor threads spawned.")

    def get_recent_signals(self, limit=100):
        """Fetch signals - extended window for weekends/holidays, with robust fallback."""
        from Trade.db_util import CChanDB
        import os
        import json
        
        # 🚀 [Scanner Enhancement] Fetch combined watchlist for name mapping
        code_to_name = {}
        try:
            hk_watchlist = self.hk_controller.get_watchlist_data()
            if hk_watchlist: code_to_name.update(hk_watchlist)
            
            cn_watchlist = {}
            if hasattr(self.cn_monitor, 'get_watchlist_data'):
                cn_watchlist = self.cn_monitor.get_watchlist_data()
            if cn_watchlist: code_to_name.update(cn_watchlist)
            
            us_watchlist = {}
            if hasattr(self.us_controller, 'get_watchlist_data'):
                us_watchlist = self.us_controller.get_watchlist_data()
            if us_watchlist: code_to_name.update(us_watchlist)
            
            # Additional names from HKTradingController watchlist
            if hasattr(self.hk_controller, 'watchlist'):
                for code, info in self.hk_controller.watchlist.items():
                    if code not in code_to_name:
                        code_to_name[code] = info.get('name', 'HK Stock')
        except Exception as e:
            logging.error(f"Failed to fetch watchlist for name mapping: {e}")

        # 🔥 [Phase 12] 动态时间窗口：周末扩大到 72h，平日 12h
        now = datetime.now()
        if now.weekday() >= 5:  # 周末
            hours_back = 72
        else:
            hours_back = 24 # 平日窗口扩大到 24h 保证覆盖

        cutoff_time = (now - timedelta(hours=hours_back)).strftime('%Y-%m-%d %H:%M:%S')
        signal_map = {}

        def signal_rank(sig: dict) -> tuple:
            open_price = sig.get('open_price')
            ml_score = sig.get('ml_score')
            visual_score = sig.get('visual_score')
            return (
                1 if open_price not in (None, 0, 0.0) else 0,
                1 if ml_score not in (None, 0, 0.0) else 0,
                1 if visual_score not in (None, 0, 0.0) else 0,
                1 if sig.get('status') == 'active' else 0,
            )

        # Helper to format signal
        def format_signal(s):
            code = s.get('stock_code')
            if not code: return None
            
            dt = s.get('add_date', 'Unknown Time')
            bstype_raw = str(s.get('bstype', '1'))
            
            # Determine buy/sell prefix
            is_buy = s.get('is_buy')
            if is_buy is None:
                # Fallback based on type: 1, 1p, 2, 2p, 3a, 3b are Buy; 1s, 2s, 3s are Sell
                low_type = bstype_raw.lower()
                is_buy = not any(v in low_type for v in ['s', 'sell'])
            
            prefix = 'b' if is_buy else 's'
            bstype_display = prefix + bstype_raw if not bstype_raw.startswith(('b', 's')) else bstype_raw
            
            # Scoring
            ml_score = s.get('ml_score')
            if isinstance(ml_score, (int, float)) and 0 < ml_score <= 1:
                ml_score = round(ml_score * 100, 2)
            elif ml_score is None:
                ml_score = 0

            visual_score = s.get('visual_score')
            if visual_score is None:
                visual_score = s.get('model_score_before') or 0

            open_price = s.get('open_price')
            if open_price in (0, 0.0, ''):
                open_price = None
            
            # Stock Name
            name = s.get('stock_name')
            if not name or name == 'TEST' or name == 'A股股票' or name == 'HK Stock':
                name = code_to_name.get(code, code)
            
            unique_key = f"{code}_{dt}_{bstype_display}"

            return {
                "unique_key": unique_key,
                "stock_code": code,
                "stock_name": name,
                "add_date": dt,
                "bstype": bstype_display,
                "lv": s.get('lv', '30M'),
                "open_price": open_price,
                "model_score_before": visual_score,
                "ml_score": ml_score,
                "visual_score": visual_score,
                "status": s.get('status', 'active'),
                "chart_url": s.get('open_image_url', '')
            }

        def add_signal(sig):
            if not sig:
                return
            unique_key = sig["unique_key"]
            existing = signal_map.get(unique_key)
            if existing is None or signal_rank(sig) > signal_rank(existing):
                signal_map[unique_key] = sig

        # 1. Load from DB
        try:
            db = CChanDB()
            # Try both tables for maximum coverage
            query_signals = "SELECT * FROM trading_signals WHERE add_date >= ? ORDER BY add_date DESC"
            df_signals = db.execute_query(query_signals, (cutoff_time,))
            if not df_signals.empty:
                for _, row in df_signals.iterrows():
                    add_signal(format_signal(row.to_dict()))

            # Also check live_trades for recent entries (Phase 12 addition)
            query_live = "SELECT code as stock_code, entry_time as add_date, signal_type as bstype, entry_price as open_price, ml_prob as ml_score, visual_score, name as stock_name FROM live_trades WHERE entry_time >= ? ORDER BY entry_time DESC"
            df_live = db.execute_query(query_live, (cutoff_time,))
            if not df_live.empty:
                for _, row in df_live.iterrows():
                    d = row.to_dict()
                    d['ml_score'] = int(d.get('ml_score', 0) * 100) if d.get('ml_score', 0) < 1 else d.get('ml_score', 0)
                    add_signal(format_signal(d))
        except Exception as e:
            logging.error(f"Error fetching signals from DB: {e}")

        # 2. Try JSON Fallback
        try:
            json_path = "discovered_signals.json"
            if os.path.exists(json_path):
                with open(json_path, "r") as f:
                    data = json.load(f)
                for k, dt_str in data.items():
                    if dt_str < cutoff_time: continue
                    if not k.startswith("STRICT_"):
                        continue

                    raw_key = k[len("STRICT_"):]
                    try:
                        code_part, remainder = raw_key.split("_", 1)
                        signal_time, bstype = remainder.rsplit("_", 1)
                    except ValueError:
                        continue

                    sig_dict = {
                        "stock_code": code_part,
                        "add_date": signal_time,
                        "bstype": bstype,
                        "lv": "30M",
                        "status": "pending",
                    }
                    add_signal(format_signal(sig_dict))
        except Exception as j_err:
            logging.error(f"Fallback JSON parsing failed: {j_err}")

        # Final Sort and Limit
        combined_signals = list(signal_map.values())
        combined_signals.sort(key=lambda x: x.get("add_date", ""), reverse=True)
        return combined_signals[:limit]

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
        self.us_controller.stop()

    def get_trading_config(self):
        self.trading_config["HK"]["auto_trade"] = not getattr(self.hk_controller, '_is_paused', False)
        self.trading_config["HK"]["live_mode"] = not self.hk_controller.dry_run
        self.trading_config["CN"]["auto_trade"] = self.cn_monitor.trading_enabled
        self.trading_config["CN"]["live_mode"] = self.cn_monitor.trd_env == 1
        self.trading_config["US"]["auto_trade"] = not getattr(self.us_controller, '_is_paused', False)
        self.trading_config["US"]["live_mode"] = self.us_controller.is_live_account_mode()
        return self.trading_config

    def set_trading_config(self, market: str, auto_trade: bool = None, live_mode: bool = None):
        """Update trading configuration and re-init context if mode changed."""
        from futu import TrdEnv
        if market == "HK":
            if auto_trade is not None:
                self.hk_controller.toggle_pause(not auto_trade)
            
            if live_mode is not None:
                new_env = TrdEnv.REAL if live_mode else TrdEnv.SIMULATE
                if self.hk_controller.trd_env != new_env:
                    print(f"DEBUG: Switching HK environment to {new_env}")
                    self.hk_controller.trd_env = new_env
                    self.hk_controller.dry_run = not live_mode
                    # Reset context to force re-login/re-init
                    self.hk_controller._trd_ctx = None
                    self.hk_controller._quote_ctx = None

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
        elif market == "US":
            if auto_trade is not None:
                self.us_controller.toggle_pause(not auto_trade)
            if live_mode is not None:
                self.us_controller.set_live_account_mode(live_mode)

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
        elif market == "US":
            self.us_controller.execute_manual_order(symbol, action, price, qty)
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
        elif market == "US":
            self.us_controller.close_all_positions()
        return {"success": True, "message": f"Emergency stop initiated for {market}"}
