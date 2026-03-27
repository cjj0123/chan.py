import pytest
from unittest.mock import MagicMock
from datetime import datetime, timedelta

# 模拟 CTime
class MockCTime:
    def __init__(self, ts):
        self.ts = ts

# 模拟 K线单元
class MockKLU:
    def __init__(self, ts):
        self.time = MockCTime(ts)

# 模拟中枢
class MockZS:
    def __init__(self, ts):
        self.begin = MockKLU(ts)

# 模拟 CChan
class MockChan:
    def __init__(self, zs_timestamps):
        self.zs_list = [MockZS(ts) for ts in zs_timestamps]

def verify_structure_barrier(code, structure_barrier, chan):
    """
    模拟 MonitorController._process_signal_sync 对结构锁区的校验逻辑
    """
    if hasattr(structure_barrier, 'get') and code in structure_barrier:
        barrier_ts = structure_barrier[code]['lock_time_ts']
        has_new_pivot = False
        if hasattr(chan, 'zs_list'):
            for zs in chan.zs_list:
                if zs.begin.time.ts > barrier_ts:
                    has_new_pivot = True
                    break
        if not has_new_pivot:
            return "BLOCK", "🛑 拦截重复开仓"
        else:
            return "ALLOW", "🔓 解锁准入"
    return "ALLOW", "无锁区"

def test_structure_barrier_blocks():
    """测试锁区：中枢时间全部在止损之前，应当拦截"""
    barrier_ts = 1710000000.0  # 假设止损时间
    structure_barrier = {
        'HK.00700': {'lock_time_ts': barrier_ts}
    }
    
    # 构建中枢：发生时间都在止损动作之前 (旧中枢)
    chan = MockChan(zs_timestamps=[1709999000.0, 1709999500.0])
    
    status, msg = verify_structure_barrier('HK.00700', structure_barrier, chan)
    assert status == "BLOCK"
    assert "🛑" in msg

def test_structure_barrier_allows_new():
    """测试锁区：中枢时间晚于止损，应当准入"""
    barrier_ts = 1710000000.0
    structure_barrier = {
        'HK.00700': {'lock_time_ts': barrier_ts}
    }
    
    # 构建中枢：存在一个新中枢诞生于止损点之后
    chan = MockChan(zs_timestamps=[1709999000.0, 1710000100.0]) 
    
    status, msg = verify_structure_barrier('HK.00700', structure_barrier, chan)
    assert status == "ALLOW"
    assert "🔓" in msg

def test_structure_barrier_no_lock():
    """测试无锁区情况，通畅放行"""
    structure_barrier = {}
    chan = MockChan(zs_timestamps=[1709999000.0])
    status, msg = verify_structure_barrier('HK.00700', structure_barrier, chan)
    assert status == "ALLOW"
    assert "无锁区" in msg
