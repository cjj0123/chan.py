#!/usr/bin/env python3
"""
原始K线数据缓存模块
用于缓存港股原始K线数据（DataFrame格式），避免重复API调用
"""

import time
import pickle
import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from Common.CEnum import KL_TYPE


class KLineRawCache:
    def __init__(self, cache_dir: str = "stock_cache", cache_duration_hours: int = 1):
        """
        初始化K线缓存
        
        Args:
            cache_dir: 缓存目录
            cache_duration_hours: 缓存有效期（小时）
        """
        self.cache_dir = cache_dir
        self.cache_duration = cache_duration_hours * 3600  # 转换为秒
        os.makedirs(cache_dir, exist_ok=True)
        
    def _get_cache_key(self, code: str, ktype: KL_TYPE, start_time: str, end_time: str) -> str:
        """生成缓存键"""
        return f"{code}_{ktype.name}_{start_time}_{end_time}"
    
    def _get_cache_path(self, cache_key: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{cache_key}.pkl")
    
    def _is_cache_valid(self, cache_path: str) -> bool:
        """检查缓存是否有效"""
        if not os.path.exists(cache_path):
            return False
        
        file_mtime = os.path.getmtime(cache_path)
        current_time = time.time()
        return (current_time - file_mtime) < self.cache_duration
    
    def get_cached_data(self, code: str, ktype: KL_TYPE, start_time: str, end_time: str) -> Optional[pd.DataFrame]:
        """
        获取缓存的K线数据
        
        Returns:
            pandas DataFrame或None
        """
        cache_key = self._get_cache_key(code, ktype, start_time, end_time)
        cache_path = self._get_cache_path(cache_key)
        
        if not self._is_cache_valid(cache_path):
            return None
            
        try:
            with open(cache_path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"缓存读取失败 {cache_key}: {e}")
            return None
    
    def save_data_to_cache(self, code: str, ktype: KL_TYPE, start_time: str, end_time: str, df_data: pd.DataFrame):
        """
        保存K线数据到缓存
        """
        cache_key = self._get_cache_key(code, ktype, start_time, end_time)
        cache_path = self._get_cache_path(cache_key)
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(df_data, f)
        except Exception as e:
            print(f"缓存保存失败 {cache_key}: {e}")
    
    def clear_expired_cache(self):
        """清理过期缓存"""
        current_time = time.time()
        for filename in os.listdir(self.cache_dir):
            if filename.endswith('.pkl'):
                file_path = os.path.join(self.cache_dir, filename)
                if current_time - os.path.getmtime(file_path) > self.cache_duration:
                    os.remove(file_path)
                    print(f"清理过期缓存: {filename}")


# 全局缓存实例
kline_raw_cache = KLineRawCache(cache_duration_hours=1)