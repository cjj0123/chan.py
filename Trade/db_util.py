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
    
    
    def __init__(self, db_path: str = None):
        """
        初始化数据库连接
        
        Args:
            db_path (str): 可选，手动指定数据库文件路径。默认为项目根目录下的 chan_trading.db
        """
        if db_path is None:
            # 找到项目根目录 (db_util.py 在 Trade 目录下，上一级就是根目录)
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.db_path = os.path.join(base_dir, "chan_trading.db")
        else:
            self.db_path = db_path
        
        # 打印一下实际使用的路径，方便调试
        # print(f"[DB] Using database: {self.db_path}")
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

        # 实盘/模拟交易闭环记录表 (优化F)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS live_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT,
                market TEXT,
                entry_time TEXT,
                entry_price REAL,
                quantity INTEGER,
                signal_type TEXT,
                ml_prob REAL,
                visual_score REAL,
                status TEXT DEFAULT 'open',
                exit_time TEXT,
                exit_price REAL,
                exit_reason TEXT,
                pnl REAL,
                pnl_pct REAL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        ''')

        # 🛡️ 止损状态跟踪持久化表 (防止 A股 T+1 重启丢失 ATR 止损锚点)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stop_loss_trackers (
                code TEXT PRIMARY KEY,
                entry_price REAL,
                highest_price REAL,
                atr REAL,
                trail_active INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
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
        
        # 移除了由于 PRIMARY KEY 存在而不需要的重复及冗余日期索引
        
        # 📰 市场资讯表 (Market Insight - Phase 1)
        cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                market TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                symbols TEXT,
                sectors TEXT,
                sentiment_score REAL DEFAULT 0.0,
                linkage TEXT,
                analysis_type TEXT,
                source TEXT,
                news_hash TEXT UNIQUE,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        ''')
        # Add new columns if table exists without them
        try:
            cursor.execute("ALTER TABLE market_news ADD COLUMN linkage TEXT")
            cursor.execute("ALTER TABLE market_news ADD COLUMN analysis_type TEXT")
        except:
            pass
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_hash ON market_news(news_hash)')

        # 🔥 每日板块热度表 (Sector Linkage - Phase 1)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sector_heat_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                market TEXT NOT NULL,
                sector_name TEXT NOT NULL,
                money_flow REAL,
                top_movers TEXT,
                news_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                UNIQUE(date, market, sector_name)
            )
        ''')

        # 为市场资讯表添加索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_market_news_timestamp ON market_news(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_market_news_market ON market_news(market)')
        
        # 为板块热度表添加索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sector_heat_date ON sector_heat_daily(date)')
        
        conn.commit()
        conn.close()
    
    def execute_query(self, query: str, params: tuple = ()) -> pd.DataFrame:
        """
        执行SQL查询并返回DataFrame (仅限 SELECT)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA cache_size = 10000")
            conn.execute("PRAGMA temp_store = memory")
            df = pd.read_sql_query(query, conn, params=params)
        return df

    def execute_non_query(self, query: str, params: tuple = ()):
        """
        执行非查询SQL语句 (INSERT, UPDATE, DELETE)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()

    def save_signal(
        self,
        code: str,
        signal_type: str,
        score: float,
        chart_path: str,
        name: str = 'Unknown',
        is_buy: bool = True,
        open_price: Optional[float] = None,
        ml_score: Optional[float] = None,
        status: str = 'active',
    ) -> int:
        """
        保存一个新的交易信号。

        Args:
            code: 股票代码。
            signal_type: 信号类型 (e.g., '1', '2s')。
            score: 视觉/模型评分。
            chart_path: 图表文件路径。
            name: 股票中文名称。
            is_buy: 是否为买点。

        Returns:
            新插入信号的ID。
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            from datetime import datetime
            add_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                """
                INSERT INTO trading_signals (
                    stock_code, add_date, bstype, open_price,
                    model_score_before, status, lv, ml_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    add_date,
                    signal_type,
                    open_price,
                    score,
                    status,
                    '30M',
                    ml_score if ml_score is not None else 0.0,
                )
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

    def record_live_trade(self, trade_data: Dict[str, Any]) -> int:
        """
        记录一笔新的开仓交易 (优化F)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            columns = [
                'code', 'name', 'market', 'entry_time', 'entry_price', 
                'quantity', 'signal_type', 'ml_prob', 'visual_score', 'status'
            ]
            placeholders = ', '.join(['?'] * len(columns))
            sql = f"INSERT INTO live_trades ({', '.join(columns)}) VALUES ({placeholders})"
            
            data = [trade_data.get(col) for col in columns]
            cursor.execute(sql, data)
            conn.commit()
            return cursor.lastrowid

    def close_live_trade(self, code: str, exit_price: float, exit_reason: str, exit_time: str = None, market: str = None):
        """
        关闭指定股票的最早一笔开仓交易 (优化F)
        """
        if exit_time is None:
            exit_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 找到该股票最早的 'open' 订单
            cursor.execute(
                "SELECT id, entry_price, quantity, market FROM live_trades WHERE code = ? AND status = 'open' ORDER BY entry_time ASC LIMIT 1",
                (code,)
            )
            row = cursor.fetchone()
            if row:
                trade_id, entry_price, quantity, db_market = row
                pnl = (exit_price - entry_price) * quantity
                pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price != 0 else 0
                
                cursor.execute(
                    """UPDATE live_trades SET 
                       status = 'closed', 
                       exit_time = ?, 
                       exit_price = ?, 
                       exit_reason = ?, 
                       pnl = ?, 
                       pnl_pct = ? 
                       WHERE id = ?""",
                    (exit_time, exit_price, exit_reason, pnl, pnl_pct, trade_id)
                )
            else:
                # 🛡️ [风控加固 Phase 9] 如果找不到 Open 持仓记录 (例如跨周期或补单)
                # 自动推断市场
                if market is None:
                    if code.startswith('HK.'): market = 'HK'
                    elif code.startswith('US.'): market = 'US'
                    elif code.startswith('SH.') or code.startswith('SZ.'): market = 'CN'
                    else: market = 'UNKNOWN'
                
                cursor.execute(
                    """INSERT INTO live_trades 
                       (code, market, exit_time, exit_price, exit_reason, status, entry_price, quantity) 
                       VALUES (?, ?, ?, ?, ?, 'closed', ?, ?)""",
                    (code, market, exit_time, exit_price, exit_reason, 0.0, 0)
                )
            conn.commit()
            
    def record_risk_log(self, code: str, action: str, quantity: int, price: float, score: int, pnl: float = 0.0):
        """记录风险管理日志 (修正了 execute_query 不支持 INSERT 的问题)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO risk_logs (code, action, quantity, price, signal_score, pnl, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (code, action, quantity, price, score, pnl, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()

    def save_stop_loss_tracker(self, code: str, entry_price: float, highest_price: float, atr: float, trail_active: int):
        """
        保存或更新止损追踪器状态
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR REPLACE INTO stop_loss_trackers (code, entry_price, highest_price, atr, trail_active) VALUES (?, ?, ?, ?, ?)",
                    (code, entry_price, highest_price, atr, trail_active)
                )
                conn.commit()
            except Exception as e:
                pass # 防爆

    def get_all_stop_loss_trackers(self) -> Dict[str, Dict]:
        """
        加载所有持久化的止损追踪状态
        """
        try:
            df = self.execute_query("SELECT * FROM stop_loss_trackers")
            result = {}
            for _, row in df.iterrows():
                result[row['code']] = {
                    'entry_price': row['entry_price'],
                    'highest_price': row['highest_price'],
                    'atr': row['atr'],
                    'trail_active': True if row['trail_active'] == 1 else False
                }
            return result
        except:
            return {}

    def record_news(self, item: Dict[str, Any]):
        """
        Record a news item into market_news table.
        """
        import hashlib
        # Generate hash if not provided
        news_hash = item.get('news_hash')
        if not news_hash:
            msg = f"{item.get('title')}_{item.get('timestamp')}"
            news_hash = hashlib.md5(msg.encode('utf-8')).hexdigest()
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            columns = [
                'timestamp', 'market', 'title', 'content', 
                'symbols', 'sectors', 'sentiment_score', 'linkage', 'analysis_type', 'source', 'news_hash'
            ]
            placeholders = ', '.join(['?'] * len(columns))
            sql = f"INSERT OR IGNORE INTO market_news ({', '.join(columns)}) VALUES ({placeholders})"
            
            data = [item.get(col) if col != 'news_hash' else news_hash for col in columns]
            cursor.execute(sql, data)
            conn.commit()

    def record_sector_heat(self, item: Dict[str, Any]):
        """
        Record sector heat data into sector_heat_daily table.
        Uses INSERT OR REPLACE based on (date, market, sector_name).
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            columns = [
                'date', 'market', 'sector_name', 'money_flow', 'top_movers', 'news_count'
            ]
            placeholders = ', '.join(['?'] * len(columns))
            sql = f"INSERT OR REPLACE INTO sector_heat_daily ({', '.join(columns)}) VALUES ({placeholders})"
            
            data = [item.get(col) for col in columns]
            cursor.execute(sql, data)
            conn.commit()

    def delete_stop_loss_tracker(self, code: str):
        """
        清除指定股票的止损追踪状态
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM stop_loss_trackers WHERE code = ?", (code,))
                conn.commit()
            except:
                pass
