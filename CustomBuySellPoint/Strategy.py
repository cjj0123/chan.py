import abc
from typing import Optional, List, Any

class CStrategy(metaclass=abc.ABCMeta):
    """
    策略抽象基类 (Abstract Base Class)
    所有自定义策略（如 CCustomStrategy）都必须继承此类并实现其抽象方法。
    """
    
    def __init__(self, conf):
        """
        初始化策略
        :param conf: CChanConfig 配置对象
        """
        self.conf = conf

    @abc.abstractmethod
    def try_open(self, chan, lv: int):
        """
        【开仓逻辑】
        判断当下最后一根K线出现时，是否是买卖时机。
        
        :param chan: CChan 对象，包含所有级别的K线数据
        :param lv: 当前正在计算的级别索引 (int)
        :return: 如果触发买卖点，返回 CCustomBSP 对象；否则返回 None
        """
        pass

    @abc.abstractmethod
    def try_close(self, chan, lv: int):
        """
        【平仓逻辑】
        判断当下对之前已经开仓且未平仓的买卖点，是否决定平仓。
        
        :param chan: CChan 对象
        :param lv: 当前级别索引
        :return: None
        """
        pass

    @abc.abstractmethod
    def bsp_signal(self, data):
        """
        【信号模式】
        用于选股或非实时信号计算。
        
        :param data: 当前级别的 K线列表 (CKLine_List)
        :return: 返回信号列表 List[CSignal]
        """
        pass