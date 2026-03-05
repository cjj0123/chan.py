#!/usr/bin/env python3
import sqlite3
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def check_db_dates():
    """检查数据库中的日期是否存在问题"""
    conn = sqlite3.connect('chan_trading.db')
    cursor = conn.cursor()
    
    # 检查HK股票的最新日期
    cursor.execute('SELECT code, date FROM kline_day WHERE code LIKE "HK.%" ORDER BY date DESC LIMIT 20')
    results = cursor.fetchall()
    print("Latest HK stock data:")
    for row in results:
        print(f"  {row[0]}: {row[1]}")
    
    # 检查是否有未来日期
    cursor.execute('SELECT code, date FROM kline_day WHERE date > "2026-03-05" ORDER BY date DESC')
    future_results = cursor.fetchall()
    if future_results:
        print("\nFuture dates found:")
        for row in future_results:
            print(f"  {row[0]}: {row[1]}")
    else:
        print("\nNo future dates found.")
    
    conn.close()

if __name__ == "__main__":
    check_db_dates()