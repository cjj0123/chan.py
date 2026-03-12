from Trade.db_util import CChanDB
import sqlite3
import pandas as pd

def audit_us_data():
    db = CChanDB()
    tables = ['kline_30m', 'kline_5m', 'kline_1m', 'kline_day']
    
    print("📊 US Stock Data Audit Report\n" + "="*30)
    
    with sqlite3.connect(db.db_path) as conn:
        for table in tables:
            print(f"\n📁 Table: {table}")
            sql = f"""
            SELECT code, COUNT(*) as count, MIN(date) as first_date, MAX(date) as last_date 
            FROM {table} 
            WHERE code LIKE 'US.%' 
            GROUP BY code
            """
            df = pd.read_sql_query(sql, conn)
            if df.empty:
                print("  (No US stock data found)")
            else:
                for _, row in df.iterrows():
                    print(f"  🔹 {row['code']}: {row['count']} rows | {row['first_date']} to {row['last_date']}")

if __name__ == "__main__":
    audit_us_data()
