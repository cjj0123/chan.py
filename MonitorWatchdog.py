#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chanlun Bot 系统异常监控看门狗 (MonitorWatchdog.py)
"""
import os
import socket
import time
import psutil
import asyncio
import aiohttp
from datetime import datetime
from dotenv import load_dotenv

# 加载配置
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

# 监控配置
INTERVAL = 60  # 每分钟检查一次
TARGET_PORTS = {
    4002: "Interactive Brokers Gateway",
    11111: "Futu OpenD"
}
LOG_FILE = "sync_history_restart.log"
DISK_THRESHOLD_GB = 2.0

class DiscordAlert:
    def __init__(self, token, channel_id):
        self.token = token
        self.channel_id = channel_id
        self.api_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"

    async def send_alert(self, message):
        if not self.token or not self.channel_id:
            print(f"⚠️ Discord 配置不全，无法发送告警: {message}")
            return
        
        payload = {
            "content": f"🚨 **Chanlun Bot 异常告警**\n{message}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }
        headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.api_url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    print(f"❌ 发送 Discord 告警失败: {resp.status}")
                else:
                    print(f"✅ 已发送告警到 Discord")

def check_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        return s.connect_ex(('127.0.0.1', port)) == 0

def check_disk(path='/'):
    usage = psutil.disk_usage(path)
    return usage.free / (1024**3)  # Convert to GB

async def watch_logs():
    if not os.path.exists(LOG_FILE):
        return None
    
    # 获取最后几行看是否有 Error
    with open(LOG_FILE, 'r') as f:
        lines = f.readlines()[-20:]
        for line in lines:
            if "ERROR" in line.upper() or "TERMINATED" in line.upper():
                return line.strip()
    return None

async def main():
    alerter = DiscordAlert(DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID)
    print(f"🔍 异常监控正在运行 (间隔: {INTERVAL}s)...")
    
    last_port_states = {p: True for p in TARGET_PORTS}
    
    while True:
        # 1. 检查端口
        for port, name in TARGET_PORTS.items():
            is_open = check_port(port)
            if not is_open and last_port_states[port]:
                await alerter.send_alert(f"❌ **端口掉线**: {name} (Port {port}) 无法连接！请检查 Gateway/OpenD 是否在运行。")
            last_port_states[port] = is_open

        # 2. 检查磁盘
        sys_free = check_disk('/')
        if sys_free < DISK_THRESHOLD_GB:
            await alerter.send_alert(f"💾 **空间危急**: 系统盘剩余空间仅为 {sys_free:.2f} GB！请及时清理。")

        # 3. 检查日志
        log_error = await watch_logs()
        if log_error:
            # 这里可以加个去重逻辑，防止连续报警
            print(f"检测到日志异常: {log_error}")

        await asyncio.sleep(INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("监控已停止。")
