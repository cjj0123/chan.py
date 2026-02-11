from CustomBuySellPoint.Strategy import CStrategy
from CustomBuySellPoint.CustomBSP import CCustomBSP
from Common.CEnum import BSP_TYPE

class CStrategySecondTheorem(CStrategy):
    """
    缠中说禅第二利润最大定理策略 (激进换股)
    核心：只做第三类买点 (3rd Buy)，出现卖点立即走人。
    """
    def __init__(self, conf):
        super(CStrategySecondTheorem, self).__init__(conf=conf)
        # 记录持仓状态，模拟盘建议配合 Trade 模块使用，此处为信号生成逻辑
        self.is_holding = False 
        self.last_buy_price = 0.0

    def try_open(self, chan, lv):
        """ 开仓：只寻找第三类买点 """
        # 获取当前级别数据 (如 30分钟)
        data = chan[lv]
        if not data.bs_point_lst.lst:
            return None
            
        # 获取最后一个确定的买卖点
        last_bsp = data.bs_point_lst.lst[-1]
        
        # 1. 必须是买点
        if not last_bsp.is_buy:
            return None
            
        # 2. 必须是当前K线刚刚确认的信号 (当下性)
        # data[-1][-1] 是最后一根原始K线
        last_klu = data[-1][-1]
        if last_bsp.klu.idx != last_klu.idx:
            return None

        # 3. 【核心】必须是第三类买点 (包含 3a, 3b)
        # type2str() 返回如 "1", "2", "3a", "2s" 等
        bsp_type = last_bsp.type2str()
        if "3" in bsp_type:
            self.is_holding = True
            self.last_buy_price = last_klu.close
            
            return CCustomBSP(
                bsp=last_bsp, 
                klu=last_klu, 
                bs_type=f"{bsp_type}(2nd_Theorem)", 
                is_buy=True, 
                target_klc=None, 
                price=last_klu.close
            )
            
        return None

    def try_close(self, chan, lv):
        """ 平仓：出现任何卖点，或趋势背驰，坚决离场 """
        if not self.is_holding:
            return None
            
        data = chan[lv]
        if not data.bs_point_lst.lst: return None
        last_bsp = data.bs_point_lst.lst[-1]
        last_klu = data[-1][-1]

        # 逻辑A: 出现官方定义的卖点 (1卖、2卖、3卖)
        # 只要是卖点，且是最新触发的，就走
        if not last_bsp.is_buy and last_bsp.klu.idx == last_klu.idx:
            self.is_holding = False
            return CCustomBSP(last_bsp, last_klu, f"Sell-{last_bsp.type2str()}", False, None, last_klu.close)

        # 逻辑B: (可选) 止损保护
        # 如果跌破买入价的一定比例 (如 -3%)，强制止损，防止假三买
        if last_klu.close < self.last_buy_price * 0.97:
            self.is_holding = False
            return CCustomBSP(None, last_klu, "StopLoss", False, None, last_klu.close)

        return None

    def bsp_signal(self, data):
        """ 用于选股扫描：返回当前是否是三买 """
        if not data.bs_point_lst.lst: return []
        last_bsp = data.bs_point_lst.lst[-1]
        if last_bsp.is_buy and "3" in last_bsp.type2str():
            # 检查是否是最近几根K线触发的
            if data[-1][-1].idx - last_bsp.klu.idx < 3:
                return [last_bsp]
        return []