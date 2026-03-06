"""
多级缓存管理器
支持内存缓存和磁盘缓存的混合策略
"""

import os
import json
import pickle
import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional, Dict
from pathlib import Path

import threading
from functools import wraps

# 内存缓存（线程安全）
class MemoryCache:
    """内存缓存实现"""
    
    def __init__(self, max_size: int = 1000):
        self._cache: Dict[str, Any] = {}
        self._access_times: Dict[str, datetime] = {}
        self._max_size = max_size
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key in self._cache:
                self._access_times[key] = datetime.now()
                return self._cache[key]
            return None
    
    def set(self, key: str, value: Any) -> None:
        """设置缓存值"""
        with self._lock:
            # 如果缓存已满，移除最久未使用的项
            if len(self._cache) >= self._max_size:
                oldest_key = min(self._access_times.keys(), 
                               key=lambda k: self._access_times[k])
                del self._cache[oldest_key]
                del self._access_times[oldest_key]
            
            self._cache[key] = value
            self._access_times[key] = datetime.now()
    
    def delete(self, key: str) -> None:
        """删除缓存项"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                del self._access_times[key]
    
    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()


# 磁盘缓存
class DiskCache:
    """磁盘缓存实现"""
    
    def __init__(self, cache_dir: str = "cache", expire_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.expire_hours = expire_hours
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        # 使用哈希确保文件名安全
        hash_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{hash_key}.pkl"
    
    def _is_expired(self, cache_path: Path) -> bool:
        """检查缓存是否过期"""
        if not cache_path.exists():
            return True
        
        file_time = datetime.fromtimestamp(cache_path.stat().st_mtime)
        expire_time = file_time + timedelta(hours=self.expire_hours)
        return datetime.now() > expire_time
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        cache_path = self._get_cache_path(key)
        
        if not cache_path.exists() or self._is_expired(cache_path):
            return None
        
        try:
            with open(cache_path, 'rb') as f:
                return pickle.load(f)
        except (pickle.PickleError, EOFError, FileNotFoundError):
            # 缓存文件损坏或不存在，清理它
            if cache_path.exists():
                cache_path.unlink()
            return None
    
    def set(self, key: str, value: Any) -> None:
        """设置缓存值"""
        cache_path = self._get_cache_path(key)
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(value, f)
        except (pickle.PickleError, OSError) as e:
            print(f"⚠️ 磁盘缓存写入失败: {e}")
    
    def delete(self, key: str) -> None:
        """删除缓存项"""
        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            cache_path.unlink()
    
    def clear_expired(self) -> int:
        """清理过期缓存，返回清理的数量"""
        cleaned = 0
        for cache_file in self.cache_dir.glob("*.pkl"):
            if self._is_expired(cache_file):
                cache_file.unlink()
                cleaned += 1
        return cleaned


# 多级缓存装饰器
class MultiLevelCache:
    """多级缓存装饰器类"""
    
    def __init__(self, 
                 memory_cache: MemoryCache = None,
                 disk_cache: DiskCache = None,
                 use_memory: bool = True,
                 use_disk: bool = True):
        self.memory_cache = memory_cache or MemoryCache()
        self.disk_cache = disk_cache or DiskCache()
        self.use_memory = use_memory
        self.use_disk = use_disk
    
    def _generate_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """生成缓存键"""
        # 将参数序列化为字符串
        arg_str = str(args) + str(sorted(kwargs.items()))
        return f"{func_name}:{hashlib.md5(arg_str.encode()).hexdigest()}"
    
    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = self._generate_key(func.__name__, args, kwargs)
            
            # 1. 首先尝试内存缓存
            if self.use_memory:
                result = self.memory_cache.get(cache_key)
                if result is not None:
                    return result
            
            # 2. 然后尝试磁盘缓存
            if self.use_disk:
                result = self.disk_cache.get(cache_key)
                if result is not None:
                    # 将磁盘缓存加载到内存缓存中
                    if self.use_memory:
                        self.memory_cache.set(cache_key, result)
                    return result
            
            # 3. 都没有命中，执行函数
            result = func(*args, **kwargs)
            
            # 4. 保存到缓存
            if self.use_memory:
                self.memory_cache.set(cache_key, result)
            if self.use_disk:
                self.disk_cache.set(cache_key, result)
            
            return result
        
        return wrapper


# 全局缓存实例
_memory_cache = MemoryCache(max_size=1000)
_disk_cache = DiskCache(cache_dir="cache", expire_hours=24)
_multi_level_cache = MultiLevelCache(_memory_cache, _disk_cache)


def multi_level_cache(func):
    """
    多级缓存装饰器
    自动使用内存缓存 + 磁盘缓存
    """
    return _multi_level_cache(func)


def get_memory_cache() -> MemoryCache:
    """获取全局内存缓存实例"""
    return _memory_cache


def get_disk_cache() -> DiskCache:
    """获取全局磁盘缓存实例"""
    return _disk_cache


def clear_all_cache():
    """清空所有缓存"""
    _memory_cache.clear()
    # 清理磁盘缓存目录
    cache_dir = Path("cache")
    if cache_dir.exists():
        for file in cache_dir.glob("*"):
            file.unlink()


# 缓存配置管理
class CacheConfig:
    """缓存配置管理"""
    
    def __init__(self, config_dict: dict = None):
        if config_dict is None:
            config_dict = {}
        
        self.memory_enabled = config_dict.get('enabled', True)
        self.memory_max_size = config_dict.get('memory_limit_mb', 100) * 1000  # 转换为KB
        self.disk_expire_hours = config_dict.get('disk_cache_expire_hours', 24)
        self.cache_dir = config_dict.get('cache_dir', 'cache')
    
    def create_caches(self) -> tuple[MemoryCache, DiskCache]:
        """创建缓存实例"""
        memory_cache = MemoryCache(max_size=self.memory_max_size // 10)  # 估算每个缓存项约10KB
        disk_cache = DiskCache(cache_dir=self.cache_dir, expire_hours=self.disk_expire_hours)
        return memory_cache, disk_cache


# 使用示例：
# @multi_level_cache
# def expensive_function(param1, param2):
#     # 执行耗时操作
#     return result