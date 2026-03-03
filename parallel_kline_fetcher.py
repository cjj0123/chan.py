#!/usr/bin/env python3
"""
并行K线数据获取器
用于并行获取30M和5M K线数据，提高性能
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple
from Chan import CChan, DATA_SRC
from Common.CEnum import KL_TYPE
from ChanConfig import CChanConfig


class ParallelKLineFetcher:
    def __init__(self, chan_config: CChanConfig, max_workers: int = 2):
        """
        初始化并行K线获取器
        
        Args:
            chan_config: CChan配置
            max_workers: 最大工作线程数
        """
        self.chan_config = chan_config
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
    
    async def fetch_30m_data(self, code: str, start_time: str, end_time: str) -> Optional[CChan]:
        """异步获取30M数据"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._fetch_kline_data,
            code, start_time, end_time, KL_TYPE.K_30M
        )
    
    async def fetch_5m_data(self, code: str, start_time: str, end_time: str) -> Optional[CChan]:
        """异步获取5M数据"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._fetch_kline_data,
            code, start_time, end_time, KL_TYPE.K_5M
        )
    
    def _fetch_kline_data(self, code: str, start_time: str, end_time: str, ktype: KL_TYPE) -> Optional[CChan]:
        """同步获取K线数据"""
        try:
            return CChan(
                code=code,
                begin_time=start_time,
                end_time=end_time,
                data_src=DATA_SRC.FUTU,
                lv_list=[ktype],
                config=self.chan_config
            )
        except Exception as e:
            print(f"获取{ktype.name}数据失败 {code}: {e}")
            return None
    
    async def fetch_both_levels(self, code: str, start_time: str, end_time: str) -> Tuple[Optional[CChan], Optional[CChan]]:
        """
        并行获取30M和5M数据
        
        Returns:
            (chan_30m, chan_5m)
        """
        # 并行执行两个任务
        tasks = [
            self.fetch_30m_data(code, start_time, end_time),
            self.fetch_5m_data(code, start_time, end_time)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常
        chan_30m = results[0] if not isinstance(results[0], Exception) else None
        chan_5m = results[1] if not isinstance(results[1], Exception) else None
        
        return chan_30m, chan_5m