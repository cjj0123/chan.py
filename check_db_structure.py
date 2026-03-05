import sqlite3

conn = sqlite3.connect('chan_trading.db')
cursor = conn.cursor()

# 获取所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print('数据库中的表:', [t[0] for t in tables])

# 检查kline_day表结构
cursor.execute("PRAGMA table_info(kline_day);")
columns = cursor.fetchall()
print('\nkline_day表结构:')
for col in columns:
    print(f'  {col[1]} ({col[2]})')

# 检查是否有其他kline表
other_kline_tables = []
for table_name in [t[0] for t in tables]:
    if table_name.startswith('kline_') and table_name != 'kline_day':
        other_kline_tables.append(table_name)

if other_kline_tables:
    print(f'\n发现其他K线表: {other_kline_tables}')
    for table in other_kline_tables:
        cursor.execute(f"PRAGMA table_info({table});")
        cols = cursor.fetchall()
        print(f'\n{table}表结构:')
        for col in cols:
            print(f'  {col[1]} ({col[2]})')
else:
    print('\n没有发现其他K线表（如kline_30m, kline_5m, kline_1m等）')

conn.close()