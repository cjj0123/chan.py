#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库导出工具：将本地 SQLite 数据库中的 K 线数据导出为 Parquet 格式
供回测引擎使用。
"""

import os
import sys
import argparse
import pandas as pd
import sqlite3
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# KL_TYPE 到名称的映射
KL_TYPE_NAME_MAP = {
    '1M': '1M',
    '5M': '5M',
    '15M': '15M',
    '30M': '30M',
    '60M': '60M',
    'DAY': 'DAY',
    'WEEK': 'WEEK',
    'MON': 'MON',
}

def export_to_parquet(db_path: str, cache_dir: str, start_date: str = None, end_date: str = None):
    """
    从数据库导出数据为 Parquet 文件
    """
    if not os.path.exists(db_path):
        logger.error(f"❌ 数据库文件不存在：{db_path}")
        return

    os.makedirs(cache_dir, exist_ok=True)
    logger.info(f"🚀 连接数据库: {db_path}, 导出目录: {cache_dir}")

    # 获取所有股票和对应的表
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 查找所有的 k 列表, chan_trading.db 的表名是 kline_1m, kline_5m, kline_30m, kline_day
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'kline_%';")
    tables = cursor.fetchall()
    
    if not tables:
         logger.warning("⚠️ 数据库中没有找到任何 kline_ 开头的表")
         return
         
    total_files = 0
    exported_codes = set()
    
    for (table_name,) in tables:
        freq_str = table_name.split('_')[-1].upper()
        logger.info(f"处理表: {table_name} (频率: {freq_str})")
        
        # 先查出该表里有哪些股票
        cursor.execute(f"SELECT DISTINCT code FROM {table_name}")
        codes = [row[0] for row in cursor.fetchall()]
        
        for code in codes:
            exported_codes.add(code)
            logger.info(f"  - 导出股票: {code}")
            
            # 构建查询
            query = f"SELECT * FROM {table_name} WHERE code = ?"
            conditions = []
            params = [code]
            
            if start_date:
                 conditions.append("date >= ?")
                 params.append(start_date)
            if end_date:
                 conditions.append("date <= ?")
                 params.append(end_date)
                 
            if conditions:
                 query += " AND " + " AND ".join(conditions)
                 
            query += " ORDER BY date ASC"
            
            try:
                # 读取数据
                df = pd.read_sql_query(query, conn, params=params)
                
                if df.empty:
                    logger.warning(f"    ⚠️ 没有查询到数据，跳过")
                    continue
                    
                # 将 timestamp 列统一命名为 time_key 以兼容回测系统
                if 'date' in df.columns:
                    df['time_key'] = pd.to_datetime(df['date'])
                
                # 显式转换数据类型，解决 bytes 导致 pyarrow 失败的问题
                def safe_numeric(series, target_type=float):
                    def _convert(x):
                        if x is None:
                            return 0
                        if isinstance(x, bytes):
                            try:
                                # 尝试从 bytes 转换为整数
                                return int.from_bytes(x, 'little')
                            except:
                                return 0
                        try:
                            return float(x)
                        except (ValueError, TypeError):
                            return 0
                    
                    return series.apply(_convert).astype(target_type)

                for col in df.columns:
                    if col in ['code', 'date', 'time_key']:
                        continue
                    
                    target_type = 'int64' if col == 'volume' else float
                    df[col] = safe_numeric(df[col], target_type)

                # 写入 parquet 文件
                filename = f"{code}_K_{freq_str}.parquet"
                filepath = os.path.join(cache_dir, filename)
                df.to_parquet(filepath, index=False, engine='pyarrow')
                
                logger.info(f"    ✅ 成功导出 {len(df)} 条记录 -> {filepath}")
                total_files += 1
                
            except Exception as e:
                logger.error(f"    ❌ 导出 {table_name} 的 {code} 异常: {e}")

    conn.close()
    
    # 生成 lot_size_map 兜底配置
    lot_size_map = {code: 100 for code in exported_codes}
    lot_size_file = os.path.join(cache_dir, 'lot_size_config.json')
    import json
    with open(lot_size_file, 'w', encoding='utf-8') as f:
         json.dump(lot_size_map, f, indent=2, ensure_ascii=False)
         
    logger.info(f"🎉 全部导出完成！共生成 {total_files} 个 parquet 文件，并生成默认 lot_size 配置。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='从 SQLite 导出持仓数据到 Parquet (用于回测)')
    parser.add_argument('--db', type=str, default='chan_trading.db', help='数据库文件路径')
    parser.add_argument('--output', type=str, default='stock_cache', help='输出缓存目录')
    parser.add_argument('--start', type=str, help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='结束日期 (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    export_to_parquet(args.db, args.output, args.start, args.end)
