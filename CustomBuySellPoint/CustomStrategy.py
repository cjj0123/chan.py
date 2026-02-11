import abc
from typing import Optional, List
from CustomBuySellPoint.Strategy import CStrategy
from CustomBuySellPoint.CustomBSP import CCustomBSP
from ChanConfig import CChanConfig
from Common.CEnum import DATA_SRC

class CCustomStrategy(CStrategy):
    def __init__(self, conf: CChanConfig):
        super(CCustomStrategy, self).__init__(conf=conf)
        # 从配置中读取是否启用区间套
        self.use_qjt = conf.strategy_para.get("use_qjt", True)
        self.strict_open = conf.strategy_para.get("strict_open", True)

    def try_open(self, chan, lv: int) -> Optional[CCustomBSP]:
        #开仓逻辑：每当有一根新K线（last_klu）结束时调用
        data = chan[lv] # 获取当前级别数据
        
        # 必须开启区间套，且当前不是最小级别（最小级别没法再往下找了），且当前级别有笔
        if self.use_qjt and lv != len(chan.lv_list) - 1 and data.bi_list:
            # 尝试计算区间套：传入当前级别数据 和 次级别数据(chan[lv+1])
            qjt_bsp = self.cal_qjt_bsp(data, chan[lv + 1])
            if qjt_bsp:
                return qjt_bsp
        
        return None

    def try_close(self, chan, lv: int) -> None:
        
        #平仓逻辑：用于判断是否需要平掉之前的仓位
        
        # 开源版暂无交易引擎状态同步，此处留空或实现简单的止损逻辑
        pass

    def bsp_signal(self, data) -> List[object]:
        
        #信号模式：用于选股（非必须）
        
        return []

    def cal_qjt_bsp(self, data, sub_lv_data) -> Optional[CCustomBSP]:
        
        #区间套核心计算逻辑：判断 父级别的买卖点 是否与 次级别的买卖点 共振
        
        # 1. 获取当前级别最后一根K线
        if not data.kl_list: return None
        last_klu = data.kl_list[-1]
        
        # 2. 获取当前级别最新的形态学买卖点 (BSP)
        # 注意：这里调用的是底层计算好的标准买卖点
        if hasattr(data, 'bs_point_lst'):
            last_bsp_lst = data.bs_point_lst.lst 
        else:
            return None

        if len(last_bsp_lst) == 0:
            return None
        
        # 取最新的一个买卖点
        last_bsp = last_bsp_lst[-1]

        # 3. 核心校验：当前K线必须就是该买卖点所在的K线
        # 意味着我们只在买卖点刚刚确认的那一刻触发
        if last_bsp.klu.idx != last_klu.idx:
            return None

        # 4. 遍历次级别（小级别）的所有策略买卖点
        # sub_lv_data.cbsp_lst 存储了次级别计算出来的所有信号
        # 如果次级别还没计算 cbsp，则无法区间套
        sub_bsps = getattr(sub_lv_data, 'cbsp_lst', [])
        
        for sub_bsp in sub_bsps:
            # 逻辑：次级别的买点必须属于父级别当前这根K线的时间范围内
            # sub_bsp.klu.sup_kl 指向的就是父级别的K线
            if sub_bsp.klu.sup_kl and sub_bsp.klu.sup_kl.idx == last_klu.idx:
                
                # 只有当次级别是 1类买卖点(背驰) 时，才确认区间套成立
                # 这里检查 type2str 是否包含 "1" (如 "1", "1p" 等)
                if "1" in sub_bsp.type2str():
                    return CCustomBSP(
                        bsp=last_bsp,
                        klu=last_klu,
                        bs_type=f"{last_bsp.type2str()}(QJT)", # 标记类型，如 "1(QJT)"
                        is_buy=last_bsp.is_buy,
                        target_klc=None,
                        price=sub_bsp.price, # 使用次级别的价格作为精确入场价
                    )
        return None