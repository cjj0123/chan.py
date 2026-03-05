#!/usr/bin/env python3
import sqlite3
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def check_duplicate_dates():
    """检查是否有重复的日期"""
    conn = sqlite3.connect('chan_trading.db')
    cursor = conn.cursor()
    
    # 检查HK.00100的重复日期
    cursor.execute('SELECT date, COUNT(*) as cnt FROM kline_day WHERE code = "HK.00100" GROUP BY date HAVING cnt > 1')
    results = cursor.fetchall()
    print("Duplicate dates for HK.00100:")
    if results:
        for row in results:
            print(f"  {row[0]}: {row[1]} times")
    else:
        print("  No duplicate dates found.")
    
    # 检查HK.00288的重复日期
    cursor.execute('SELECT date, COUNT(*) as cnt FROM kline_day WHERE code = "HK.00288" GROUP BY date HAVING cnt > 1')
    results = cursor.fetchall()
    print("\nDuplicate dates for HK.00288:")
    if results:
        for row in results:
            print(f"  {row[0]}: {row[1]} times")
    else:
        print("  No duplicate dates found.")
    
    conn.close()

if __name__ == "__main__":
    check_duplicate_dates()