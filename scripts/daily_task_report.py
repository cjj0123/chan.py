#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Task Report Script
Audits launchd tasks and sends a summary to Discord.
"""

import os
import sys
import subprocess
import logging
import asyncio
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TRADING_CONFIG
from App.DiscordBot import DiscordBot
from scripts.daily_hot_scanner import get_schwab_movers

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def get_launchd_status():
    """Check launchctl list for relevant tasks"""
    tasks = [
        "com.jijunchen.chanlun.hot_scanner",
        "com.chanlun.daily_sync",
        "com.chanlun.ib_watchdog"
    ]
    results = {}
    try:
        output = subprocess.check_output(["launchctl", "list"], stderr=subprocess.STDOUT).decode()
        for task in tasks:
            if task in output:
                lines = [line for line in output.split('\n') if task in line]
                if lines:
                    parts = lines[0].split()
                    pid = parts[0]
                    last_exit = parts[1]
                    status = "Running (PID: " + pid + ")" if pid != "-" else "Idle (Last Exit: " + last_exit + ")"
                    results[task] = status
            else:
                results[task] = "Not Found/Not Loaded"
    except Exception as e:
        logger.error(f"Error checking launchctl: {e}")
    return results

def get_last_log_summary(log_path, lines=5):
    """Get the last few lines of a log file and check for errors"""
    if not os.path.exists(log_path):
        return "Log file not found."
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            if not all_lines:
                return "Empty log file."
            last_lines = all_lines[-lines:]
            summary = "".join(last_lines).strip()
            if "ERROR" in summary or "Exception" in summary:
                return "🚨 Potential issues detected:\n" + summary
            return "Success/Normal:\n" + summary
    except Exception as e:
        return f"Error reading log: {e}"

async def main():
    logger.info("Starting Daily Task Report...")
    
    # 1. Check Launchd Status
    launchd_results = await get_launchd_status()
    
    # 2. Check Logs
    hot_scanner_log = get_last_log_summary("/tmp/daily_hot_scanner.log", 3)
    daily_sync_log = get_last_log_summary("/tmp/daily_incremental_sync.log", 3)
    ib_watchdog_log = get_last_log_summary("/tmp/ib_watchdog_stderr.log", 3)
    
    # 3. Check Schwab Token
    schwab_status = "Unknown"
    try:
        codes = get_schwab_movers(5)
        if codes:
            schwab_status = f"✅ Normal (Fetched {len(codes)} movers)"
        else:
            schwab_status = "⚠️ Normal but returned 0 movers"
    except Exception as e:
        schwab_status = f"❌ Error: {str(e)[:100]}"
    
    # 4. Construct Report
    report = [
        "## 🌅 缠论机器人 - 每日定时任务审计报告",
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        "### 1. Launchd 任务状态",
    ]
    for task, status in launchd_results.items():
        icon = "✅" if "Running" in status or "Exit: 0" in status else "❌"
        report.append(f"{icon} **{task.split('.')[-1]}**: `{status}`")
    
    report.append("\n### 2. 关键任务日志摘要")
    report.append(f"🔥 **热点扫描 (Hot Scanner)**:\n```\n{hot_scanner_log}\n```")
    report.append(f"🔄 **数据同步 (Daily Sync)**:\n```\n{daily_sync_log}\n```")
    report.append(f"🐕 **IB 守护进程 (Watchdog)**:\n```\n{ib_watchdog_log}\n```")
    
    report.append("\n### 3. API 联通性")
    report.append(f"🔗 **Schwab Token**: {schwab_status}")
    
    full_report = "\n".join(report)
    logger.info("Report constructed. Sending to Discord...")
    
    # 5. Send to Discord
    discord_cfg = TRADING_CONFIG.get('discord', {})
    if discord_cfg.get('token') and discord_cfg.get('channel_id'):
        bot = DiscordBot(
            token=discord_cfg['token'],
            channel_id=discord_cfg['channel_id'],
            allowed_user_ids=discord_cfg.get('allowed_user_ids', [])
        )
        # We need to start the bot's internal loop to send message
        # DiscordBot.send_notification handles fetching channel if bot is ready
        # But here we use a simpler one-off send if possible or just run the bot briefly
        
        # Simpler approach: use a standalone message sender for this script
        import aiohttp
        async with aiohttp.ClientSession() as session:
            url = f"https://discord.com/api/v10/channels/{discord_cfg['channel_id']}/messages"
            headers = {"Authorization": f"Bot {discord_cfg['token']}"}
            payload = {"content": full_report}
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    logger.info("Report sent to Discord successfully.")
                else:
                    text = await resp.text()
                    logger.error(f"Failed to send report to Discord: {resp.status} {text}")
    else:
        logger.warning("Discord configuration missing. Report printed to console:\n" + full_report)

if __name__ == "__main__":
    asyncio.run(main())
