#!/usr/bin/env python3
"""
数据库维护脚本 - 用于优化数据库性能
"""

import sqlite3
import os
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def optimize_database(db_path="chan_trading.db"):
    """
    优化数据库性能
    """
    print(f"🔧 开始优化数据库: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("  📊 分析数据库...")
        cursor.execute("ANALYZE")
        
        print("  🧹 执行数据库清理...")
        cursor.execute("VACUUM")  # 整理数据库文件，回收空间
        
        print("  🚀 优化查询计划...")
        cursor.execute("ANALYZE")  # 更新统计信息以优化查询计划
        
        # 创建性能索引
        indexes = [
            ("idx_kline_day_code_date", "kline_day", "(code, date)"),
            ("idx_kline_30m_code_date", "kline_30m", "(code, date)"),
            ("idx_kline_5m_code_date", "kline_5m", "(code, date)"),
            ("idx_kline_1m_code_date", "kline_1m", "(code, date)"),
            ("idx_kline_day_date_desc", "kline_day", "(date DESC)"),
            ("idx_kline_30m_date_desc", "kline_30m", "(date DESC)"),
            ("idx_kline_5m_date_desc", "kline_5m", "(date DESC)"),
            ("idx_kline_1m_date_desc", "kline_1m", "(date DESC)"),
            ("idx_trading_signals_code_status", "trading_signals", "(stock_code, status)"),
            ("idx_orders_code_status", "orders", "(code, order_status)"),
            ("idx_positions_code", "positions", "(code)")
        ]
        
        for index_name, table_name, columns in indexes:
            try:
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} {columns}")
                print(f"  ✅ 索引 {index_name} 已创建或已存在")
            except sqlite3.Error as e:
                print(f"  ⚠️  创建索引 {index_name} 时出错: {e}")
        
        conn.commit()
        conn.close()
        
        print(f"✅ 数据库优化完成: {db_path}")
        return True
        
    except sqlite3.Error as e:
        print(f"❌ 数据库优化失败: {e}")
        return False

def get_database_stats(db_path="chan_trading.db"):
    """
    获取数据库统计信息
    """
    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        return None
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 获取数据库大小
        db_size = os.path.getsize(db_path)
        db_size_mb = round(db_size / (1024 * 1024), 2)
        
        # 获取表统计信息
        tables = ['kline_day', 'kline_30m', 'kline_5m', 'kline_1m', 'trading_signals', 'orders', 'positions']
        stats = {}
        
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                stats[table] = count
            except sqlite3.Error:
                # 表可能不存在
                stats[table] = 0
        
        conn.close()
        
        return {
            'size_mb': db_size_mb,
            'tables': stats
        }
        
    except sqlite3.Error as e:
        print(f"❌ 获取数据库统计信息失败: {e}")
        return None

def main():
    """
    主函数
    """
    print("🔍 数据库维护工具")
    print("="*50)
    
    # 获取数据库统计信息
    stats = get_database_stats()
    if stats:
        print(f"📊 数据库大小: {stats['size_mb']} MB")
        print("📈 表统计:")
        for table, count in stats['tables'].items():
            print(f"   {table}: {count} 条记录")
    
    print()
    
    # 优化数据库
    success = optimize_database()
    
    if success:
        print("\n✅ 数据库维护完成！")
        print("优化包括:")
        print("  - 执行 VACUUM 整理数据库")
        print("  - 创建性能索引")
        print("  - 更新查询统计信息")
    else:
        print("\n❌ 数据库维护失败！")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())