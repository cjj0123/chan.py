import matplotlib
matplotlib.use('Agg')
print(f"✅ Matplotlib backend set to: {matplotlib.get_backend()}")

import sys
import os
# [CRITICAL] Force WEB_MODE for signal handling adapter selection
os.environ['WEB_MODE'] = '1'
import logging
from pathlib import Path
# Add project root to path to allow running as a script and importing from WebService
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List
import json
import asyncio
from contextlib import asynccontextmanager
from WebService.terminal_manager import WebTerminalManager
async def lifespan(app: FastAPI):
    # Startup
    global terminal_manager
    loop = asyncio.get_running_loop()
    terminal_manager = WebTerminalManager(manager.broadcast, loop=loop)
    await terminal_manager.start_monitors()
    yield
    # Shutdown
    terminal_manager.stop_monitors()

app = FastAPI(title="Chanlun Trading Terminal API", lifespan=lifespan)

# Mount static directories for charts
charts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "App/charts")
charts_monitor_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "App/charts_monitor")
os.makedirs(charts_dir, exist_ok=True)
os.makedirs(charts_monitor_dir, exist_ok=True)

app.mount("/charts", StaticFiles(directory=charts_dir), name="charts")
app.mount("/charts_monitor", StaticFiles(directory=charts_monitor_dir), name="charts_monitor")

# Enable CORS for Next.js development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connection Manager for WebSockets
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # Handle potentially closed connections
                pass

manager = ConnectionManager()
terminal_manager = None # Initialized in lifespan

@app.get("/")
async def root():
    return {"status": "online", "message": "Chanlun Bot API is running"}

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() # Keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/portfolio")
async def get_portfolio():
    # Fetch real data from the controller if it's available
    if terminal_manager:
        return {
            "hk": terminal_manager.hk_status,
            "cn": terminal_manager.cn_status
        }
    return {"message": "Initializing controllers..."}

@app.get("/api/signals")
async def get_signals():
    # Fetch recent signals from the database
    if terminal_manager:
        signals = terminal_manager.get_recent_signals()
        return {"signals": signals}
    return {"signals": []}

@app.get("/api/logs")
async def get_logs():
    # Fetch recent logs from cache
    if terminal_manager:
        return {"logs": terminal_manager.recent_logs}
    return {"logs": []}

@app.get("/api/analyze/{symbol}")
async def analyze_symbol(symbol: str, lv: str = "30M"):
    if terminal_manager:
        try:
            result = terminal_manager.generate_analysis_chart(symbol, lv)
            return result
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logging.error(f"Failed to generate analysis chart for {symbol}:\n{error_details}")
            return {
                "success": False,
                "error": str(e),
                "traceback": error_details
            }
    return {"success": False, "error": "Terminal manager not initialized"}

@app.post("/api/system/restart")
async def restart_system():
    if terminal_manager:
        async def delayed_restart():
            await asyncio.sleep(0.5)
            # Exit process, wrapper script will handle the restart
            os._exit(0)
        
        asyncio.create_task(delayed_restart())
        return {"success": True, "message": "Backend system is restarting..."}
    return {"success": False, "error": "System not initialized"}

from pydantic import BaseModel

class TradingToggle(BaseModel):
    market: str
    auto_trade: bool = None
    live_mode: bool = None

class ManualOrder(BaseModel):
    market: str
    symbol: str
    action: str
    price: float
    qty: int

@app.get("/api/trading/config")
async def get_trading_config():
    if terminal_manager:
        return terminal_manager.get_trading_config()
    return {}

@app.post("/api/trading/toggle")
async def toggle_trading(config: TradingToggle):
    if terminal_manager:
        return terminal_manager.set_trading_config(
            market=config.market, 
            auto_trade=config.auto_trade, 
            live_mode=config.live_mode
        )
    return {"success": False}

@app.post("/api/trading/order")
async def place_order(order: ManualOrder):
    if terminal_manager:
        return terminal_manager.execute_manual_order(
            market=order.market,
            symbol=order.symbol,
            action=order.action,
            price=order.price,
            qty=order.qty
        )
    return {"success": False}

@app.post("/api/trading/emergency_stop")
async def emergency_stop(market: str):
    if terminal_manager:
        return terminal_manager.emergency_stop(market)
    return {"success": False}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
