import os
os.environ['WEB_MODE'] = '1'

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
