import abc
from typing import Optional, List
from CustomBuySellPoint.Strategy import CStrategy
from CustomBuySellPoint.CustomBSP import CCustomBSP
from ChanConfig import CChanConfig

class CCustomStrategy(CStrategy):
    def __init__(self, conf: CChanConfig):
        super(CCustomStrategy, self).__init__(conf=conf)
        self.use_qjt = conf.strategy_para.get("use_qjt", True)
        # 简单模拟持仓状态
        self.is_holding = False
        self.last_buy_price = None
        # 读取止损止盈配置
        self.max_sl_rate = conf.strategy_para.get("max_sl_rate", None)
        self.max_profit_rate = conf.strategy_para.get("max_profit_rate", None)

    def try_open(self, chan, lv: int) -> Optional[CCustomBSP]:
        """ 开仓逻辑 """
        data = chan[lv] # 获取当前级别数据
        
        # 1. 基础校验：必须开启区间套，且不是最小级别，且本级别有笔
        if self.use_qjt and lv != len(chan.lv_list) - 1 and data.bi_list:
            # 2. 调用区间套计算
            qjt_bsp = self.cal_qjt_bsp(data, chan[lv + 1])
            if qjt_bsp:
                self.is_holding = True
                self.last_buy_price = qjt_bsp.price
                return qjt_bsp
        
        return None

    def try_close(self, chan, lv: int) -> Optional[CCustomBSP]:
        """ 平仓逻辑 """
        if not self.is_holding or self.last_buy_price is None:
            return None

        # 【修正点1】获取当前价格 (data[-1][-1] 而不是 data.kl_list[-1])
        data = chan[lv]
        if len(data) == 0: return None
        last_klu = data[-1][-1] 
        current_price = last_klu.close

        # 止损判断
        if self.max_sl_rate:
            stop_loss_price = self.last_buy_price * (1 - self.max_sl_rate)
            if current_price <= stop_loss_price:
                self.is_holding = False
                return CCustomBSP(None, last_klu, "StopLoss", False, None, current_price)

        # 止盈判断
        if self.max_profit_rate:
            take_profit_price = self.last_buy_price * (1 + self.max_profit_rate)
            if current_price >= take_profit_price:
                self.is_holding = False
                return CCustomBSP(None, last_klu, "TakeProfit", False, None, current_price)
        
        return None

    def bsp_signal(self, data) -> List[object]:
        return []

    def cal_qjt_bsp(self, data, sub_lv_data) -> Optional[CCustomBSP]:
        """
        区间套核心计算逻辑
        """
        # ... (前面的代码保持不变: 获取 last_klu, last_bsp 等) ...
        
        # 1. 获取本级别(如30F)最新的形态学买卖点
        if hasattr(data, 'bs_point_lst'):
            last_bsp_lst = data.bs_point_lst.lst 
        else:
            return None
        if len(last_bsp_lst) == 0: return None
        last_bsp = last_bsp_lst[-1]

        # 校验时间对齐
        if last_bsp.klu.idx != last_klu.idx:
            return None

        # =================================================================
        # 【核心修正】: 不再遍历 sub_lv_data.cbsp_lst (策略信号)
        # 而是遍历 sub_lv_data.bs_point_lst.lst (次级别的标准形态学买卖点)
        # =================================================================
        
        # 获取次级别(如5F)的所有标准买卖点
        sub_bsp_lst = []
        if hasattr(sub_lv_data, 'bs_point_lst'):
             sub_bsp_lst = sub_lv_data.bs_point_lst.lst
        
        for sub_bsp in sub_bsp_lst:
            # 逻辑：次级别的买点必须属于父级别当前这根K线的时间范围内
            # sub_bsp.klu.sup_kl 是框架自动计算的父子K线映射
            if sub_bsp.klu.sup_kl and sub_bsp.klu.sup_kl.idx == last_klu.idx:
                
                # 校验方向一致 (大级别买，小级别也必须是买)
                if sub_bsp.is_buy == last_bsp.is_buy:
                    
                    # (可选) 严格模式：只允许次级别是背驰(1类)
                    # if "1" not in sub_bsp.type2str(): continue

                    return CCustomBSP(
                        bsp=last_bsp,
                        klu=last_klu,
                        bs_type=f"{last_bsp.type2str()}(QJT)", # 标记为区间套
                        is_buy=last_bsp.is_buy,
                        target_klc=None,
                        price=sub_bsp.price, # 使用次级别的价格作为精确入场价
                    )
        return None