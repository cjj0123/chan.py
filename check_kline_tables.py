import sqlite3

conn = sqlite3.connect('chan_trading.db')
cursor = conn.cursor()

# 检查所有kline表的数据量
kline_tables = ['kline_day', 'kline_30m', 'kline_5m', 'kline_1m']

for table in kline_tables:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"{table}: {count} rows")
    except sqlite3.OperationalError as e:
        print(f"{table}: Table does not exist - {e}")

conn.close()