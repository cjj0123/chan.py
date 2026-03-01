"""
MockStockAPI - 用于回测的模拟股票数据 API
"""
from typing import List, Iterator, Any, Dict, Optional
from Common.CEnum import KL_TYPE


# 全局数据注册表，用于存储回测时注入的 K 线数据
# 格式：{ (code, kl_type): [klu_list] }
_data_registry: Dict[tuple, List[Any]] = {}


def register_kline_data(code: str, kl_type: KL_TYPE, klu_list: List[Any]):
    """
    注册 K 线数据到全局注册表
    
    Args:
        code: 股票代码
        kl_type: K 线类型
        klu_list: BacktestKLineUnit 对象列表
    """
    _data_registry[(code, kl_type)] = klu_list


def clear_kline_data():
    """清除所有注册的 K 线数据"""
    _data_registry.clear()


class MockStockAPI:
    """
    模拟股票数据 API，用于回测场景。
    接收预先准备好的 K 线数据，并按 CChan 期望的接口提供数据。
    """
    
    def __init__(self, code: str, k_type: KL_TYPE, begin_date: str, end_date: str, autype: int = 0):
        """
        初始化模拟 API
        
        Args:
            code: 股票代码
            k_type: K 线类型
            begin_date: 开始日期（未使用，数据已预先加载）
            end_date: 结束日期（未使用，数据已预先加载）
            autype: 复权类型
        """
        self.code = code
        self.k_type = k_type
        self.begin_date = begin_date
        self.end_date = end_date
        self.autype = autype
        
        # 从注册表获取数据
        key = (code, k_type)
        if key in _data_registry:
            self.klu_list = _data_registry[key]
        else:
            self.klu_list = []
        
        # 按时间排序
        self.klu_list = sorted(self.klu_list, key=lambda x: x.timestamp)
    
    def get_kl_data(self) -> Iterator[Any]:
        """返回 K 线数据迭代器"""
        return iter(self.klu_list)
    
    @classmethod
    def do_init(cls):
        """初始化钩子方法"""
        pass
    
    @classmethod
    def do_close(cls):
        """关闭钩子方法"""
        pass
