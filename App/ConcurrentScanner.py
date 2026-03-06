"""
并发扫描管理器
用于提高股票分析速度，支持多线程/多进程并发处理
"""

import asyncio
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
import threading
import time

from Chan import CChan
from ChanConfig import CChanConfig
from DataAPI.DataManager import get_data_manager
from Common.CEnum import KL_TYPE


class ConcurrentScanner:
    """
    并发扫描管理器
    
    支持多种并发模式：
    1. 线程池模式（默认）- 适合I/O密集型任务
    2. 进程池模式 - 适合CPU密集型任务
    3. 异步模式 - 适合网络请求密集型任务
    """
    
    def __init__(self, max_workers: int = None, mode: str = "thread"):
        """
        初始化并发扫描器
        
        Args:
            max_workers: 最大工作线程/进程数，默认为CPU核心数
            mode: 并发模式 ("thread", "process", "async")
        """
        self.max_workers = max_workers or min(32, (threading.cpu_count() or 1) + 4)
        self.mode = mode
        self.data_manager = get_data_manager()
        
    def scan_stocks_concurrent(self, 
                             stock_codes: List[str], 
                             config: CChanConfig,
                             kl_type: KL_TYPE = KL_TYPE.K_DAY,
                             days: int = 365) -> Dict[str, Any]:
        """
        并发扫描股票列表
        
        Args:
            stock_codes: 股票代码列表
            config: 缠论配置
            kl_type: K线类型
            days: 分析天数
            
        Returns:
            Dict[str, Any]: 扫描结果，包含成功和失败的股票
        """
        if self.mode == "thread":
            return self._scan_with_thread_pool(stock_codes, config, kl_type, days)
        elif self.mode == "process":
            return self._scan_with_process_pool(stock_codes, config, kl_type, days)
        elif self.mode == "async":
            return asyncio.run(self._scan_with_async(stock_codes, config, kl_type, days))
        else:
            raise ValueError(f"不支持的并发模式: {self.mode}")
    
    def _scan_with_thread_pool(self, 
                              stock_codes: List[str], 
                              config: CChanConfig,
                              kl_type: KL_TYPE,
                              days: int) -> Dict[str, Any]:
        """使用线程池进行并发扫描"""
        results = {"success": {}, "failed": {}, "total": len(stock_codes)}
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_stock = {
                executor.submit(self._analyze_single_stock, code, config, kl_type, days): code
                for code in stock_codes
            }
            
            # 收集结果
            for future in as_completed(future_to_stock):
                stock_code = future_to_stock[future]
                try:
                    result = future.result(timeout=300)  # 5分钟超时
                    if result is not None:
                        results["success"][stock_code] = result
                    else:
                        results["failed"][stock_code] = "分析结果为空"
                except Exception as e:
                    results["failed"][stock_code] = str(e)
        
        end_time = time.time()
        results["scan_time"] = end_time - start_time
        results["success_count"] = len(results["success"])
        results["failed_count"] = len(results["failed"])
        
        return results
    
    def _scan_with_process_pool(self, 
                               stock_codes: List[str], 
                               config: CChanConfig,
                               kl_type: KL_TYPE,
                               days: int) -> Dict[str, Any]:
        """使用进程池进行并发扫描"""
        results = {"success": {}, "failed": {}, "total": len(stock_codes)}
        start_time = time.time()
        
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_stock = {
                executor.submit(self._analyze_single_stock_process, code, config, kl_type, days): code
                for code in stock_codes
            }
            
            # 收集结果
            for future in as_completed(future_to_stock):
                stock_code = future_to_stock[future]
                try:
                    result = future.result(timeout=300)
                    if result is not None:
                        results["success"][stock_code] = result
                    else:
                        results["failed"][stock_code] = "分析结果为空"
                except Exception as e:
                    results["failed"][stock_code] = str(e)
        
        end_time = time.time()
        results["scan_time"] = end_time - start_time
        results["success_count"] = len(results["success"])
        results["failed_count"] = len(results["failed"])
        
        return results
    
    async def _scan_with_async(self, 
                              stock_codes: List[str], 
                              config: CChanConfig,
                              kl_type: KL_TYPE,
                              days: int) -> Dict[str, Any]:
        """使用异步方式进行并发扫描"""
        results = {"success": {}, "failed": {}, "total": len(stock_codes)}
        start_time = time.time()
        
        # 创建异步任务
        tasks = [
            self._analyze_single_stock_async(code, config, kl_type, days)
            for code in stock_codes
        ]
        
        # 等待所有任务完成
        completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        for i, result in enumerate(completed_tasks):
            stock_code = stock_codes[i]
            if isinstance(result, Exception):
                results["failed"][stock_code] = str(result)
            elif result is not None:
                results["success"][stock_code] = result
            else:
                results["failed"][stock_code] = "分析结果为空"
        
        end_time = time.time()
        results["scan_time"] = end_time - start_time
        results["success_count"] = len(results["success"])
        results["failed_count"] = len(results["failed"])
        
        return results
    
    def _analyze_single_stock(self, 
                            code: str, 
                            config: CChanConfig,
                            kl_type: KL_TYPE,
                            days: int) -> Optional[Dict[str, Any]]:
        """分析单个股票（线程安全版本）"""
        try:
            # 获取K线数据
            end_date = datetime.now().strftime("%Y-%m-%d")
            begin_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            kline_data = self.data_manager.get_kline_data(
                code, kl_type, begin_date, end_date
            )
            
            if not kline_data:
                return None
            
            # 执行缠论分析
            chan = CChan(
                stock_code=code,
                lv_list=[kl_type],
                conf=config
            )
            
            # 添加K线数据
            for klu in kline_data:
                chan.add_kl(klu)
            
            # 检查是否有有效的买卖点
            buy_points = []
            sell_points = []
            
            if hasattr(chan, 'bsp_list') and chan.bsp_list:
                for bsp in chan.bsp_list:
                    if bsp.is_buy:
                        buy_points.append({
                            'price': bsp.klu.close,
                            'time': bsp.klu.time.to_str(),
                            'type': bsp.type,
                            'is_sure': bsp.is_sure
                        })
                    else:
                        sell_points.append({
                            'price': bsp.klu.close,
                            'time': bsp.klu.time.to_str(),
                            'type': bsp.type,
                            'is_sure': bsp.is_sure
                        })
            
            return {
                'chan': chan,
                'buy_points': buy_points,
                'sell_points': sell_points,
                'kline_count': len(kline_data)
            }
            
        except Exception as e:
            print(f"❌ 股票 {code} 分析失败: {e}")
            return None
    
    def _analyze_single_stock_process(self, 
                                    code: str, 
                                    config: CChanConfig,
                                    kl_type: KL_TYPE,
                                    days: int) -> Optional[Dict[str, Any]]:
        """分析单个股票（进程安全版本）"""
        # 进程池中不能共享复杂对象，需要重新初始化
        return self._analyze_single_stock(code, config, kl_type, days)
    
    async def _analyze_single_stock_async(self, 
                                        code: str, 
                                        config: CChanConfig,
                                        kl_type: KL_TYPE,
                                        days: int) -> Optional[Dict[str, Any]]:
        """分析单个股票（异步版本）"""
        # 异步版本可以复用线程版本的逻辑
        return self._analyze_single_stock(code, config, kl_type, days)
    
    def get_performance_stats(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """获取性能统计信息"""
        total_time = results.get("scan_time", 0)
        success_count = results.get("success_count", 0)
        total_count = results.get("total", 0)
        
        if total_time == 0:
            return {"stocks_per_second": 0, "avg_time_per_stock": 0}
        
        stocks_per_second = total_count / total_time
        avg_time_per_stock = total_time / total_count
        
        return {
            "stocks_per_second": round(stocks_per_second, 2),
            "avg_time_per_stock": round(avg_time_per_stock, 2),
            "total_scan_time": round(total_time, 2),
            "success_rate": round(success_count / total_count * 100, 2) if total_count > 0 else 0
        }


# 全局并发扫描器实例
_concurrent_scanner_instance = None

def get_concurrent_scanner(max_workers: int = None, mode: str = "thread") -> ConcurrentScanner:
    """获取全局并发扫描器实例"""
    global _concurrent_scanner_instance
    if _concurrent_scanner_instance is None:
        _concurrent_scanner_instance = ConcurrentScanner(max_workers, mode)
    return _concurrent_scanner_instance


# 使用示例：
# scanner = get_concurrent_scanner(max_workers=8, mode="thread")
# results = scanner.scan_stocks_concurrent(stock_codes, config, KL_TYPE.K_DAY, 365)
# stats = scanner.get_performance_stats(results)