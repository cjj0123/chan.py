from Trade.db_util import CChanDB
import sqlite3

def cleanup_us_data():
    db = CChanDB()
    tables = ['kline_30m', 'kline_5m', 'kline_1m'] # 重点清理分钟级别
    
    print("🧹 Starting US Stock Data Cleanup...")
    
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()
        total_deleted = 0
        for table in tables:
            cursor.execute(f"DELETE FROM {table} WHERE code LIKE 'US.%'")
            deleted_count = cursor.rowcount
            print(f"  ❌ Deleted {deleted_count} rows from {table}")
            total_deleted += deleted_count
        
        conn.commit()
    
    print(f"\n✅ Cleanup finished. Total rows removed: {total_deleted}")

if __name__ == "__main__":
    cleanup_us_data()
