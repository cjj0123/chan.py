#!/usr/bin/env python3
import sqlite3
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def check_hk_00100_data():
    """检查HK.00100的具体数据"""
    conn = sqlite3.connect('chan_trading.db')
    cursor = conn.cursor()
    
    # 检查HK.00100的数据
    cursor.execute('SELECT date, open, high, low, close FROM kline_day WHERE code = "HK.00100" ORDER BY date DESC LIMIT 5')
    results = cursor.fetchall()
    print("HK.00100 data:")
    for row in results:
        print(f"  {row[0]}: O={row[1]}, H={row[2]}, L={row[3]}, C={row[4]}")
    
    conn.close()

if __name__ == "__main__":
    check_hk_00100_data()