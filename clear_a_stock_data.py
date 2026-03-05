#!/usr/bin/env python3
"""
安全清理A股本地数据，保留其他市场数据
"""

import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Trade.db_util import CChanDB

def clear_a_stock_tables():
    """只删除A股相关的数据表，保留港股、美股等其他数据"""
    try:
        db = CChanDB()
        
        # 获取所有表名
        tables = db.execute_query("SELECT name FROM sqlite_master WHERE type='table';")
        table_names = tables['name'].tolist()
        
        print(f"📊 数据库中找到 {len(table_names)} 个表:")
        for table in table_names:
            print(f"   - {table}")
        
        # A股代码前缀：SH.6, SZ.0, SZ.3
        # 删除A股相关的K线数据
        a_stock_tables = ['kline_day', 'kline_30m', 'kline_5m', 'kline_1m']
        
        deleted_count = 0
        for table in a_stock_tables:
            if table in table_names:
                # 只删除A股数据（SH.6开头和SZ.开头的）
                delete_query = f"""
                DELETE FROM {table} 
                WHERE code LIKE 'SH.6%' 
                   OR code LIKE 'SZ.0%' 
                   OR code LIKE 'SZ.3%'
                """
                result = db.execute_query(delete_query)
                print(f"✅ 已清理表 {table} 中的A股数据")
                deleted_count += 1
        
        # 也可以选择性地清理特定的股票列表
        print(f"\n🧹 已完成清理，处理了 {deleted_count} 个A股数据表")
        print("💡 现在您可以重新从Futu下载A股数据，而不会影响其他市场数据")
        
    except Exception as e:
        print(f"❌ 清理失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("⚠️  此脚本将只删除A股相关数据，保留港股、美股等其他数据")
    confirm = input("是否继续? (y/N): ")
    if confirm.lower() == 'y':
        clear_a_stock_tables()
    else:
        print("已取消操作")