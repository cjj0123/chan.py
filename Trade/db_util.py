"""
交易数据库工具类。
"""

import os
import sqlite3
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime


class CChanDB:
    """
    缠论交易数据库操作类
    """
    
    def __init__(self, db_path: str = "chan_trading.db"):
        """
        初始化数据库连接
        
        Args:
            db_path (str): 数据库文件路径
        """
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 交易信号表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trading_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                add_date TEXT NOT NULL,
                bstype TEXT NOT NULL,
                open_price REAL,
                quota REAL,
                model_score_before REAL,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        # 交易订单表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trading_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL,
                add_time TEXT NOT NULL
            )
        ''')
        
        # 交易持仓表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trading_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL UNIQUE,
                quantity INTEGER NOT NULL,
                avg_cost REAL NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def execute_query(self, query: str, params: tuple = ()) -> pd.DataFrame:
        """
        执行SQL查询并返回DataFrame
        
        Args:
            query (str): SQL查询语句
            params (tuple): 查询参数
            
        Returns:
            pd.DataFrame: 查询结果
        """
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df