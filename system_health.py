#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chanlun Bot 系统健康检查看板
"""
import os
import sys
import time
import psutil
import sqlite3
from datetime import datetime
from pathlib import Path

def get_dir_size(path):
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_dir_size(entry.path)
    except Exception:
        pass
    return total

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

def check_sync_progress():
    db_path = "/Volumes/存储/Chanlun_Bot_Data/chan_trading.db"
    if not os.path.exists(db_path):
        return "数据库未找到"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 统计美股数量
        cursor.execute("SELECT count(DISTINCT code) FROM kline_day WHERE code LIKE 'US.%'")
        us_count = cursor.fetchone()[0]
        
        # 统计总K线数量
        cursor.execute("SELECT count(*) FROM kline_day")
        total_klines = cursor.fetchone()[0]
        
        # 获取最新同步的股票
        cursor.execute("SELECT code, MAX(date) FROM kline_day GROUP BY code ORDER BY MAX(date) DESC LIMIT 1")
        last_sync = cursor.fetchone()
        
        conn.close()
        return f"已同步美股: {us_count}/517 ({us_count/517*100:.1f}%) | 总K线: {total_klines} | 最后同步: {last_sync[0] if last_sync else 'N/A'}"
    except Exception as e:
        return f"同步检查失败: {e}"

def main():
    print("="*60)
    print(f"🚀 Chanlun Bot 系统健康看板 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # 1. 磁盘空间
    print("\n[💾 磁盘空间]")
    root_usage = psutil.disk_usage('/')
    external_usage = psutil.disk_usage('/Volumes/存储') if os.path.exists('/Volumes/存储') else None
    
    print(f"系统盘 (/): {format_size(root_usage.free)} 可用 / {root_usage.percent}% 已用")
    if external_usage:
        print(f"存储盘 (/Volumes/存储): {format_size(external_usage.free)} 可用 / {external_usage.percent}% 已用")
    
    # 2. 核心数据统计
    print("\n[📊 数据记录]")
    db_size = os.path.getsize("/Volumes/存储/Chanlun_Bot_Data/chan_trading.db") if os.path.exists("/Volumes/存储/Chanlun_Bot_Data/chan_trading.db") else 0
    print(f"数据库大小: {format_size(db_size)}")
    print(f"同步进度: {check_sync_progress()}")
    
    # 3. 运行中进程
    print("\n[⚙️ 运行状态]")
    bot_procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
        try:
            cmd = " ".join(proc.info['cmdline']) if proc.info['cmdline'] else ""
            if "TraderGUI.py" in cmd:
                bot_procs.append(f"✅ GUI (PID: {proc.info['pid']}, 已运行: {int((time.time()-proc.info['create_time'])/60)} 分钟)")
            elif "sync_all_history.py" in cmd:
                bot_procs.append(f"⏳ 同步脚本 (PID: {proc.info['pid']}, 已运行: {int((time.time()-proc.info['create_time'])/60)} 分钟)")
        except:
            pass
    
    if not bot_procs:
        print("❌ 未检测到正在运行的核心进程")
    for p in bot_procs:
        print(p)
        
    print("\n" + "="*60)
    print("💡 建议: 如果同步进度达到 100%，您可以启动机器学习训练流程。")
    print("="*60)

if __name__ == "__main__":
    main()
