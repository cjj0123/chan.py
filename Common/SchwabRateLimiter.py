import time
import threading
from collections import deque

class SchwabRateLimiter:
    """
    针对 Charles Schwab API 的频率限制器 (针对订单指令)
    限制: 120 次请求 / 60 秒 (即平均每秒 2 次)
    """
    def __init__(self, max_requests=120, period=60):
        self.max_requests = max_requests
        self.period = period
        self.requests = deque()
        self.lock = threading.Lock()

    def acquire(self):
        """
        尝试执行一个请求，如果超过频率则阻塞
        """
        with self.lock:
            while True:
                now = time.time()
                # 移除过期的请求记录
                while self.requests and self.requests[0] <= now - self.period:
                    self.requests.popleft()
                
                if len(self.requests) < self.max_requests:
                    self.requests.append(now)
                    return True
                
                # 计算需要等待的时间
                wait_time = self.requests[0] + self.period - now + 0.01
                if wait_time > 0:
                    time.sleep(wait_time)

    def can_request(self) -> bool:
        """
        非阻塞检查是否可以发送请求
        """
        with self.lock:
            now = time.time()
            while self.requests and self.requests[0] <= now - self.period:
                self.requests.popleft()
            return len(self.requests) < self.max_requests

# 全局单例
_limiter_instance = SchwabRateLimiter()

def get_schwab_limiter():
    return _limiter_instance
