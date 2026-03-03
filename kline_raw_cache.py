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
        """
        生成缓存键
        
        为了解决5分钟和30分钟K线时间不一致的问题，对时间进行标准化处理：
        - 开始时间只保留日期部分（YYYY-MM-DD）
        - 结束时间根据K线类型进行对齐：
          * 5分钟K线：对齐到最近的5分钟边界
          * 30分钟K线：对齐到最近的30分钟边界
          * 其他类型：对齐到小时边界
        """
        # 标准化开始时间（只保留日期）
        if ' ' in start_time:
            std_start_time = start_time.split(' ')[0]
        else:
            std_start_time = start_time
            
        # 标准化结束时间
        from datetime import datetime
        try:
            # 解析结束时间
            if ' ' in end_time:
                dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.strptime(end_time, "%Y-%m-%d")
                
            # 根据K线类型对齐时间
            if ktype == KL_TYPE.K_5M:
                # 对齐到5分钟边界，但如果是接近下一个5分钟点（<2分钟），则使用下一个边界
                current_minute = dt.minute
                current_second = dt.second
                aligned_minute = (current_minute // 5) * 5
                minutes_to_next = 5 - (current_minute % 5)
                seconds_to_next = minutes_to_next * 60 - current_second
                
                if seconds_to_next < 120:  # 如果距离下一个5分钟点少于2分钟
                    next_aligned_minute = aligned_minute + 5
                    if next_aligned_minute >= 60:
                        # 跨小时处理
                        std_end_time = dt.replace(hour=dt.hour + 1, minute=next_aligned_minute - 60, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        std_end_time = dt.replace(minute=next_aligned_minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    std_end_time = dt.replace(minute=aligned_minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
            elif ktype == KL_TYPE.K_30M:
                # 对齐到30分钟边界
                aligned_minute = (dt.minute // 30) * 30
                std_end_time = dt.replace(minute=aligned_minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
            else:
                # 其他类型对齐到小时边界
                std_end_time = dt.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            # 如果解析失败，使用原始结束时间
            std_end_time = end_time
            
        return f"{code}_{ktype.name}_{std_start_time}_{std_end_time}"
    
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