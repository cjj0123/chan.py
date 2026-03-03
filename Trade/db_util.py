"""
数据库操作工具类，用于缠论交易系统的数据持久化。
根据 README.md 的描述，实现 CChanDB 类，封装数据库的增删改查操作。
"""

import os
import sqlite3
import pandas as pd
from typing import List, Dict, Optional, Any
from Config.EnvConfig import env_config


class CChanDB:
    """
    缠论数据库操作类。
    自动从配置文件中读取数据库连接参数，并提供对信号、订单、持仓等数据的操作接口。
    """

    def __init__(self):
        """
        初始化数据库连接。
        会自动从配置文件中读取数据库类型和连接参数。
        """
        # 从配置中获取数据库路径，默认为项目根目录下的 trading_data.db
        self.db_path = env_config.get("database.path", "trading_data.db")
        self._ensure_db_directory()
        self._init_database()

    def _ensure_db_directory(self):
        """确保数据库文件所在的目录存在。"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    def _init_database(self):
        """初始化数据库表结构。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 创建信号表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    score REAL,
                    chart_path TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'active' -- active, executed, expired
                )
            ''')
            
            # 创建订单表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    action TEXT NOT NULL, -- BUY, SELL
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    order_status TEXT DEFAULT 'pending', -- pending, filled, cancelled
                    signal_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(signal_id) REFERENCES signals(id)
                )
            ''')
            
            # 创建持仓表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    quantity INTEGER NOT NULL,
                    avg_cost REAL NOT NULL,
                    last_update DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()

    def execute_query(self, query: str, params: tuple = ()) -> pd.DataFrame:
        """
        执行一个SQL查询并返回pandas DataFrame。

        Args:
            query: SQL查询语句。
            params: 查询参数。

        Returns:
            查询结果的DataFrame。
        """
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(query, conn, params=params)

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
            cursor.execute(
                "INSERT INTO signals (code, signal_type, score, chart_path) VALUES (?, ?, ?, ?)",
                (code, signal_type, score, chart_path)
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
        query = "SELECT * FROM signals WHERE status = 'active'"
        params = ()
        if code:
            query += " AND code = ?"
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