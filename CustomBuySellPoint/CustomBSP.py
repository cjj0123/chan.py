class CCustomBSP:
    def __init__(self, bsp, klu, bs_type, is_buy, target_klc, price):
        self.bsp = bsp             # 关联的基础买卖点(形态学)
        self.klu = klu             # 信号发生的K线
        self.bs_type = bs_type     # 类型字符串 (如 "1(QJT)")
        self.is_buy = is_buy       # True为买，False为卖
        self.target_klc = target_klc 
        self.price = price         # 建议交易价格
        self.features = {}         # 特征字典

    def type2str(self):
        return self.bs_type