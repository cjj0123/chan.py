#!/usr/bin/env python3
"""
BacktestDataLoader - 回测数据加载器
负责从Parquet文件加载历史K线数据，并转换为回测引擎所需的格式
"""

import os
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BacktestKLineUnit:
    """模拟 CChan/KLine 模块所需的 CKLine_Unit 结构。"""
    def __init__(self, timestamp: pd.Timestamp, open_p: float, high_p: float, low_p: float, close_p: float, volume: int, kl_type: str, original_klu: any = None):
        self.timestamp = timestamp
        self.open = open_p
        self.high = high_p
        self.low = low_p
        self.close = close_p
        self.volume = volume
        self.kl_type = kl_type  # e.g., '30M', '5M', 'DAY'
        self.original_klu = original_klu  # 用于存储原始的 CKLine_Unit（如果存在）
        
        # 适配 CTime 结构 (从 Common 导入)
        try:
            from Common.CTime import CTime
            dt = timestamp.to_pydatetime()
            self.time = CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, auto=True)
        except ImportError:
            class MockCTime:
                def __init__(self, ts):
                    self.ts = ts
            self.time = MockCTime(timestamp.timestamp())
            
        self.sup_kl = None
        self.sub_kl_list = []
        self.parent = None
        self.children = []
        self.idx = -1  # K 线索引
        self.pre_klu = None  # 前一根 K 线
        self.pre = None  # 前一根 K 线（CChan 兼容）
        self.next = None  # 后一根 K 线（CChan 兼容）
        self.macd = None  # MACD 指标（CChan 兼容）
        self.boll = None  # BOLL 指标（CChan 兼容）
        self.rsi = None  # RSI 指标（CChan 兼容）
        self.kdj = None  # KDJ 指标（CChan 兼容）
        self.demark = None  # Demark 指标（CChan 兼容）
        self.trend = {}  # 趋势指标（CChan 兼容）
        self.limit_flag = 0  # 涨跌停标志（CChan 兼容）
        self.trade_info = type('MockTradeInfo', (), {'metric': {}})()  # 交易信息（CChan 兼容）
        self._klc = None

    def set_idx(self, idx: int):
        """设置 K 线索引"""
        self.idx = idx
    
    def get_idx(self) -> int:
        """获取 K 线索引"""
        return self.idx
    
    def set_pre_klu(self, klu):
        """设置前一根 K 线（CChan 兼容的双向链接）"""
        self.pre_klu = klu
        self.pre = klu
        if klu is not None:
            klu.next = self
    
    def get_pre_klu(self):
        """获取前一根 K 线"""
        return self.pre_klu
    
    def set_metric(self, metric_model_lst: list) -> None:
        """设置技术指标（CChan 兼容版本）"""
        from Math.MACD import CMACD
        from Math.BOLL import BollModel
        from Math.RSI import RSI
        from Math.KDJ import KDJ
        from Math.Demark import CDemarkEngine
        from Math.TrendModel import CTrendModel
        
        for metric_model in metric_model_lst:
            try:
                if isinstance(metric_model, CMACD):
                    self.macd = metric_model.add(self.close)
                elif isinstance(metric_model, CTrendModel):
                    if metric_model.type not in self.trend:
                        self.trend[metric_model.type] = {}
                    self.trend[metric_model.type][metric_model.T] = metric_model.add(self.close)
                elif isinstance(metric_model, BollModel):
                    self.boll = metric_model.add(self.close)
                elif isinstance(metric_model, CDemarkEngine):
                    self.demark = metric_model.update(idx=self.idx, close=self.close, high=self.high, low=self.low)
                elif isinstance(metric_model, RSI):
                    self.rsi = metric_model.add(self.close)
                elif isinstance(metric_model, KDJ):
                    self.kdj = metric_model.add(self.high, self.low, self.close)
                elif hasattr(metric_model, 'add'):
                    metric_model.add(self.close)
            except Exception:
                pass  # 忽略计算错误
    
    def set_klc(self, klc):
        """设置 K 线组合引用（简化版本，用于回测）"""
        self._klc = klc
    
    @property
    def klc(self):
        """获取 K 线组合引用（CChan 兼容）"""
        return self._klc

    def __repr__(self):
        return f"BacktestKLineUnit({self.timestamp}, {self.kl_type}, O:{self.open}, H:{self.high}, L:{self.low}, C:{self.close}, V:{self.volume}, IDX:{self.idx})"

class BacktestDataLoader:
    """
    回测数据加载器
    负责从 stock_cache/ 目录加载 Parquet 格式的历史K线数据
    """
    
    def __init__(self, cache_dir: str = "stock_cache"):
        self.cache_dir = cache_dir
        self.lot_size_map = self._load_lot_size_map()
        
    def _load_lot_size_map(self) -> Dict[str, int]:
        """加载每手股数配置"""
        lot_size_file = os.path.join(self.cache_dir, "lot_size_config.json")
        if os.path.exists(lot_size_file):
            import json
            with open(lot_size_file, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"Lot size config file not found: {lot_size_file}")
            return {}
    
    def get_lot_size(self, code: str) -> int:
        """获取股票的每手股数"""
        return self.lot_size_map.get(code, 100)  # 默认100股/手
    
    def load_kline_data(self, code: str, freq: str, start_date: str = None, end_date: str = None) -> List[BacktestKLineUnit]:
        """
        加载指定股票和频率的K线数据
        
        Args:
            code: 股票代码 (e.g., 'HK.00700')
            freq: K线频率 ('30M', '5M', 'DAY')
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            
        Returns:
            List[BacktestKLineUnit]: K线数据列表
        """
        # 构建文件路径
        filename = f"{code}_K_{freq}.parquet"
        filepath = os.path.join(self.cache_dir, filename)
        
        if not os.path.exists(filepath):
            logger.info(f"Parquet file not found, attempting to load {code} from SQLite...")
            return self._load_from_sqlite(code, freq, start_date, end_date)
        
        try:
            # 读取Parquet文件
            df = pd.read_parquet(filepath)
            
            # 转换时间列，使用 errors='coerce' 处理超范围日期
            if 'time_key' in df.columns:
                df['timestamp'] = pd.to_datetime(df['time_key'], errors='coerce')
            elif 'time' in df.columns:
                df['timestamp'] = pd.to_datetime(df['time'], errors='coerce')
            else:
                logger.error(f"No time column found in {filepath}")
                return []
            
            # 过滤掉无法转换的日期 (NaT)
            initial_count = len(df)
            df = df.dropna(subset=['timestamp'])
            df = df.sort_values('timestamp')  # 👈 强制按时间升序排序
            if len(df) < initial_count:
                logger.warning(f"在 {filepath} 中过滤掉了 {initial_count - len(df)} 条无效时间数据。")

            # 应用日期过滤
            if start_date:
                start_dt = pd.to_datetime(start_date, errors='coerce')
                if pd.notna(start_dt):
                    df = df[df['timestamp'] >= start_dt]
            
            if end_date:
                end_dt = pd.to_datetime(end_date, errors='coerce')
                if pd.notna(end_dt):
                    df = df[df['timestamp'] <= end_dt]
            
            # 创建BacktestKLineUnit对象列表
            kline_units = []
            for _, row in df.iterrows():
                # 安全转换数值（特别处理从数据库导出的 bytes 类型）
                def safe_float(val):
                    if isinstance(val, bytes):
                        # 尝试将 sqlite storage 转换的 bytes 转为 int 再转 float
                        try:
                            # 假设是小端编码的整型
                            return float(int.from_bytes(val, byteorder='little'))
                        except:
                            return 0.0
                    return float(val) if pd.notna(val) else 0.0
                
                def safe_int(val):
                    if isinstance(val, bytes):
                        try:
                            return int.from_bytes(val, byteorder='little')
                        except:
                            return 0
                    return int(float(val)) if pd.notna(val) else 0

                klu = BacktestKLineUnit(
                    timestamp=row['timestamp'],
                    open_p=safe_float(row['open']),
                    high_p=safe_float(row['high']),
                    low_p=safe_float(row['low']),
                    close_p=safe_float(row['close']),
                    volume=safe_int(row.get('volume', 0)),
                    kl_type=freq
                )
                kline_units.append(klu)
            
            logger.info(f"Loaded {len(kline_units)} {freq} K-lines for {code}")
            return kline_units
            
        except Exception as e:
            logger.error(f"Error loading data from {filepath}: {e}")
            return []
    
    def _load_from_sqlite(self, code: str, freq: str, start_date: str = None, end_date: str = None) -> List[BacktestKLineUnit]:
        """从 SQLite 数据库加载数据"""
        from DataAPI.SQLiteAPI import SQLiteAPI
        from Common.CEnum import KL_TYPE
        
        freq_map = {
            '30M': KL_TYPE.K_30M,
            '5M': KL_TYPE.K_5M,
            '1M': KL_TYPE.K_1M,
            'DAY': KL_TYPE.K_DAY
        }
        
        try:
            k_type = freq_map.get(freq.upper(), KL_TYPE.K_DAY)
            api = SQLiteAPI(code, k_type=k_type, begin_date=start_date, end_date=end_date)
            kline_units = []
            for i, klu in enumerate(api.get_kl_data()):
                backtest_klu = BacktestKLineUnit(
                    timestamp=pd.to_datetime(str(klu.time)),
                    open_p=klu.open,
                    high_p=klu.high,
                    low_p=klu.low,
                    close_p=klu.close,
                    volume=int(klu.volume),
                    kl_type=freq
                )
                kline_units.append(backtest_klu)
            
            # 强制按时间升序排序
            kline_units = sorted(kline_units, key=lambda x: x.timestamp)
            # 重新分配 idx
            for i, backtest_klu in enumerate(kline_units):
                backtest_klu.set_idx(i)
            
            if kline_units:
                logger.info(f"Loaded {len(kline_units)} {freq} K-lines for {code} from SQLite")
            return kline_units
        except Exception as e:
            logger.error(f"Error loading {code} from SQLite: {e}")
            return []

    def get_all_codes(self) -> List[str]:
        """获取所有可用的股票代码 (兼顾 Parquet 缓存与 SQLite 数据源)"""
        codes = set()
        
        # 1. 尝试从 Parquet 缓存加载
        if os.path.exists(self.cache_dir):
            files = os.listdir(self.cache_dir)
            for file in files:
                if file.endswith('_K_30M.parquet'):
                    codes.add(file.replace('_K_30M.parquet', ''))
        
        # 2. 尝试从 SQLite 数据库补偿加载
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(base_dir, "chan_trading.db")
            if os.path.exists(db_path):
                import sqlite3
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT code FROM kline_30m")
                for row in cursor.fetchall():
                    if row[0]:
                        codes.add(row[0])
                conn.close()
        except Exception as e:
            logger.warning(f"从 SQLite 加举股票列表失败: {e}")
            
        return sorted(list(codes))
    
    def get_available_frequencies(self, code: str) -> List[str]:
        """获取指定股票可用的K线频率"""
        frequencies = []
        for freq in ['30M', '5M', 'DAY']:
            filename = f"{code}_K_{freq}.parquet"
            filepath = os.path.join(self.cache_dir, filename)
            if os.path.exists(filepath):
                frequencies.append(freq)
        
        return frequencies

# 兼容性函数（用于旧代码）
def load_kline_data(code: str, freq: str, start_date: str = None, end_date: str = None) -> List[BacktestKLineUnit]:
    """兼容性函数，用于旧版本代码调用"""
    loader = BacktestDataLoader()
    return loader.load_kline_data(code, freq, start_date, end_date)

if __name__ == "__main__":
    # 简单测试
    loader = BacktestDataLoader()
    
    # 测试加载数据
    codes = loader.get_all_codes()
    print(f"Available codes: {codes[:5]}...")  # 只显示前5个
    
    if codes:
        test_code = codes[0]
        print(f"\nTesting {test_code}...")
        
        # 测试30M数据
        klines_30m = loader.load_kline_data(test_code, '30M', '2024-01-01', '2024-01-31')
        print(f"30M K-lines loaded: {len(klines_30m)}")
        
        if klines_30m:
            print(f"First K-line: {klines_30m[0]}")
            print(f"Last K-line: {klines_30m[-1]}")