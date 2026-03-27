import pandas as pd
from datetime import datetime, timedelta
from DataAPI.CommonStockAPI import CCommonStockApi
from DataAPI.SQLiteAPI import SQLiteAPI
from DataAPI.FutuAPI import CFutuAPI
from Common.CEnum import KL_TYPE, AUTYPE
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

class HybridFutuAPI(CCommonStockApi):
    """
    [混合动力数据源]
    - 历史端: 从本地 SQLite 读取 (数据截止到昨日)
    - 实时端: 从 FutuAPI 仅拉取今日增量
    - 容错垫: 若本地历史缺失或严重断档，自动全量回退至 FutuAPI 保障 CChan 推演绝对准确
    """
    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(HybridFutuAPI, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self):
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        # 🟢 [动态路由] 根据代码前缀分配在线增量接口 (美股优先使用 Schwab)
        online_api_cls = CFutuAPI
        if self.code.startswith('US.'):
            # 引入 SchwabAPI 避免循环依赖
            try:
                from DataAPI.SchwabAPI import CSchwabAPI
                online_api_cls = CSchwabAPI
            except ImportError:
                 print("⚠️ [HybridFutuAPI] CSchwabAPI 导入失败，降级回 CFutuAPI")
        
        # 1. 计算理论上的 SQLite 截止时间 (昨天)
        yesterday = now - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        
        history_units = []
        sqlite_valid = False
        
        # 如果 begin_date 已经是今天或未来，直接不需要 SQLite
        if self.begin_date and self.begin_date >= today_str:
            pass
        else:
            try:
                # 定义 SQLite 数据的提取区间 [begin_date, yesterday_str]
                sqlite_api = SQLiteAPI(
                    code=self.code,
                    k_type=self.k_type,
                    begin_date=self.begin_date,
                    end_date=yesterday_str,
                    autype=self.autype
                )
                history_units = list(sqlite_api.get_kl_data())
                
                # 🛡️ 容错校验：检查本地历史数据是否断档
                if history_units:
                    last_hist = history_units[-1]
                    last_dt = datetime(last_hist.time.year, last_hist.time.month, last_hist.time.day)
                    
                    # 如果本地最后一条数据距离今天超过 4 天 (考虑节假日)，视为同步断档
                    if (now - last_dt).days <= 4:
                        sqlite_valid = True
                    else:
                        print(f"⚠️ [HybridFutuAPI] {self.code} 本地历史断档 (最后一条: {last_hist.time})，将全量回退至在线。")
                else:
                    print(f"⚠️ [HybridFutuAPI] {self.code} 本地无历史缓存，将全量回退。")
            except Exception as e:
                print(f"⚠️ [HybridFutuAPI] {self.code} SQLite 载入异常: {e}")

        # 2. 核心分流水闸
        if sqlite_valid:
            # ✅ 本地数据健康，走混合拼接模式
            print(f"📊 [HybridFutuAPI] {self.code} 走混合模式 (历史 [{len(history_units)} 根] + 今日增量)")
            live_units = []
            try:
                # 仅拉取今天的数据 [today_str, end_date]
                futu_api = online_api_cls(
                    code=self.code,
                    k_type=self.k_type,
                    begin_date=today_str,
                    end_date=self.end_date,
                    autype=self.autype
                )
                live_units = list(futu_api.get_kl_data())
            except Exception as e:
                print(f"⚠️ [HybridFutuAPI] {self.code} 在线增量拉取异常: {e}")

            # 拼接与流式去重输出
            all_units = history_units + live_units
            all_units.sort(key=lambda x: x.time.ts)  # 👈 防止 time err 倒流
            seen_times = set()
            for klu in all_units:
                t_str = str(klu.time)
                if t_str not in seen_times:
                    seen_times.add(t_str)
                    yield klu
        else:
            # 🚨 本地数据不可靠，尝试全量在线拉取模式
            print(f"📡 [HybridFutuAPI] {self.code} 尝试全量在线拉取模式 [范围: {self.begin_date} 到 {self.end_date}]")
            try:
                f_api = online_api_cls(self.code, self.k_type, self.begin_date, self.end_date, self.autype)
                for klu in f_api.get_kl_data():
                    yield klu
            except Exception as e_online:
                if history_units:
                    print(f"🆘 [HybridFutuAPI] {self.code} 在线获取失败 ({e_online})，被迫启用【最终回退】：使用不完整的本地历史数据避演！")
                    for klu in history_units:
                        yield klu
                else:
                    print(f"❌ [HybridFutuAPI] {self.code} 本地与在线数据均失效: {e_online}")

    def SetBasciInfo(self):
        self.name = self.code
        self.is_stock = True

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass
