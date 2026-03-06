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
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                signal_id INTEGER,
                order_status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        ''')
        
        # 交易持仓表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                code TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL,
                avg_cost REAL NOT NULL
            )
        ''')
        
        # 风险管理日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS risk_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                signal_score INTEGER NOT NULL,
                pnl REAL DEFAULT 0.0,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        ''')
        
        # K线数据表 - 日线
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kline_day (
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                turnover REAL,
                turnrate REAL,
                PRIMARY KEY (code, date)
            )
        ''')
        
        # K线数据表 - 30分钟线
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kline_30m (
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                turnover REAL,
                turnrate REAL,
                PRIMARY KEY (code, date)
            )
        ''')
        
        # K线数据表 - 5分钟线  
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kline_5m (
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                turnover REAL,
                turnrate REAL,
                PRIMARY KEY (code, date)
            )
        ''')
        
        # K线数据表 - 1分钟线
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kline_1m (
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                turnover REAL,
                turnrate REAL,
                PRIMARY KEY (code, date)
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

    def save_signal(self, code: str, signal_type: str, score: float, chart_path: str) -> int:
        """
        保存一个新的交易信号。

        Args:
            code: 股票代码。
            signal_type: 信号类型 (e.g., 'buy', 'sell')。
            score: 视觉评分。
            chart_path: 图表文件路径。

        Returns:
            新插入信号的ID。
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            from datetime import datetime
            add_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                "INSERT INTO trading_signals (add_date, stock_code, stock_name, lv, bstype, is_buy, model_score_before, open_image_url, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')",
                (add_date, code, 'TEST', '30M', signal_type, 1 if signal_type == 'buy' else 0, score, chart_path)
            )
            conn.commit()
            return cursor.lastrowid

    def get_active_signals(self, code: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取所有活跃的信号。

        Args:
            code: 可选，指定股票代码以过滤信号。

        Returns:
            活跃信号的列表。
        """
        query = "SELECT * FROM trading_signals WHERE status = 'active'"
        params = ()
        if code:
            query += " AND stock_code = ?"
            params = (code,)
        
        df = self.execute_query(query, params)
        return df.to_dict('records')

    def update_signal_status(self, signal_id: int, new_status: str):
        """
        更新信号的状态。

        Args:
            signal_id: 信号ID。
            new_status: 新状态 ('active', 'executed', 'expired')。
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE signals SET status = ? WHERE id = ?",
                (new_status, signal_id)
            )
            conn.commit()

    def save_order(self, code: str, action: str, quantity: int, price: float, signal_id: Optional[int] = None) -> int:
        """
        保存一个订单记录。

        Args:
            code: 股票代码。
            action: 操作类型 ('BUY', 'SELL')。
            quantity: 数量。
            price: 价格。
            signal_id: 关联的信号ID（可选）。

        Returns:
            新插入订单的ID。
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO orders (code, action, quantity, price, signal_id) VALUES (?, ?, ?, ?, ?)",
                (code, action, quantity, price, signal_id)
            )
            conn.commit()
            return cursor.lastrowid

    def get_pending_orders(self, code: str) -> List[Dict[str, Any]]:
        """
        获取指定股票的所有待处理订单。

        Args:
            code: 股票代码。

        Returns:
            待处理订单的列表。
        """
        query = "SELECT * FROM orders WHERE code = ? AND order_status = 'pending'"
        df = self.execute_query(query, (code,))
        return df.to_dict('records')

    def update_order_status(self, order_id: int, new_status: str):
        """
        更新订单状态。

        Args:
            order_id: 订单ID。
            new_status: 新状态 ('pending', 'filled', 'cancelled')。
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE orders SET order_status = ? WHERE id = ?",
                (new_status, order_id)
            )
            conn.commit()

    def save_position(self, code: str, quantity: int, avg_cost: float):
        """
        保存或更新持仓信息。

        Args:
            code: 股票代码。
            quantity: 持仓数量。
            avg_cost: 平均成本。
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 使用 INSERT OR REPLACE 来处理更新
            cursor.execute(
                """INSERT OR REPLACE INTO positions (code, quantity, avg_cost) 
                   VALUES (?, ?, ?)""",
                (code, quantity, avg_cost)
            )
            conn.commit()

    def get_position(self, code: str) -> Optional[Dict[str, Any]]:
        """
        获取指定股票的持仓信息。

        Args:
            code: 股票代码。

        Returns:
            持仓信息字典，如果不存在则返回None。
        """
        query = "SELECT * FROM positions WHERE code = ?"
        df = self.execute_query(query, (code,))
        if df.empty:
            return None
        return df.iloc[0].to_dict()
