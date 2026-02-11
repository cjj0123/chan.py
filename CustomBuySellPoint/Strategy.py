import abc

class CStrategy(metaclass=abc.ABCMeta):
    def __init__(self, conf):
        self.conf = conf

    @abc.abstractmethod
    def try_open(self, chan, lv):
        
        #尝试开仓
        :param chan: #CChan对象，包含所有级别数据
        :param lv: #当前级别索引
        :return: CCustomBSP #对象 或 None
        
        pass

    @abc.abstractmethod
    def try_close(self, chan, lv):
        
        #尝试平仓
        
        pass

    @abc.abstractmethod
    def bsp_signal(self, data):
        
        #计算信号
        
        pass