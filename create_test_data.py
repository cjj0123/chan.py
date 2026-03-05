#!/usr/bin/env python3
"""
创建测试数据用于GUI扫描测试
"""
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

def create_test_data():
    # 连接数据库
    conn = sqlite3.connect('chan_trading.db')
    
    # 创建kline_day表（如果不存在）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS kline_day (
            code TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            turnover REAL,
            turnrate REAL
        )
    ''')
    
    # 创建测试股票列表
    test_stocks = [
        '000001', '600000', '600519', '000858', '601318',
        '002415', '300750', '600036', '601628', '000333'
    ]
    
    # 为每只股票生成365天的测试数据
    for stock_code in test_stocks:
        data = []
        current_date = datetime.now() - timedelta(days=365)
        
        # 初始价格
        price = 10.0
        
        for i in range(365):
            # 简单的价格模拟（随机波动）
            import random
            change = random.uniform(-0.05, 0.05)
            price = price * (1 + change)
            price = max(price, 0.1)  # 确保价格为正
            
            open_price = price
            high_price = price * (1 + random.uniform(0, 0.03))
            low_price = price * (1 - random.uniform(0, 0.03))
            close_price = price * (1 + random.uniform(-0.01, 0.01))
            
            # 确保价格关系正确
            high_price = max(open_price, high_price, low_price, close_price)
            low_price = min(open_price, high_price, low_price, close_price)
            
            data.append({
                'code': stock_code,
                'date': current_date.strftime('%Y-%m-%d'),
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': random.uniform(1000000, 10000000),
                'turnover': random.uniform(10000000, 100000000),
                'turnrate': random.uniform(0.01, 0.1)
            })
            
            current_date += timedelta(days=1)
        
        # 插入数据
        df = pd.DataFrame(data)
        df.to_sql('kline_day', conn, if_exists='append', index=False)
        print(f"Created test data for {stock_code}")
    
    conn.commit()
    conn.close()
    print("Test data creation completed!")

if __name__ == "__main__":
    create_test_data()