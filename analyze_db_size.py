#!/usr/bin/env python3
"""
分析数据库表大小分布的脚本
"""
import sqlite3
import os

def analyze_table_sizes(db_path):
    """分析各表的大小"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 获取所有表名
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"数据库文件总大小: {os.path.getsize(db_path) / (1024*1024):.2f} MB")
    print("\n各表数据量统计:")
    print("-" * 50)
    
    total_rows = 0
    for table in tables:
        if table == 'sqlite_sequence':
            continue
        cursor.execute(f"SELECT COUNT(*) FROM {table};")
        count = cursor.fetchone()[0]
        total_rows += count
        print(f"{table:20} | {count:>8} 行")
    
    print("-" * 50)
    print(f"{'总计':20} | {total_rows:>8} 行")
    
    # 分析时间范围
    print("\n各表时间范围:")
    print("-" * 50)
    time_tables = ['kline_day', 'kline_30m', 'kline_5m', 'kline_1m']
    for table in time_tables:
        cursor.execute(f"SELECT MIN(date), MAX(date) FROM {table};")
        min_date, max_date = cursor.fetchone()
        if min_date and max_date:
            print(f"{table:20} | {min_date} 到 {max_date}")
    
    conn.close()

if __name__ == "__main__":
    analyze_table_sizes("chan_trading.db")