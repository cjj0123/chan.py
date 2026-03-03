import sys
import os
import pandas as pd
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE
# 假设您之前的驱动和策略都在正确位置
from DataAPI.CommonStockAPI import CCommonStockApi  # 您的CFutuStockDriver_V6
from CustomBuySellPoint.StrategySecondTheorem import CStrategySecondTheorem

# -----------------------------------------------------------
# 1. 简单的回测账户类
# -----------------------------------------------------------
class BacktestAccount:
    def __init__(self, initial_cash=100000.0):
        self.cash = initial_cash
        self.stock_cnt = 0
        self.trades = [] # 记录交易明细

    def buy(self, price, time, code):
        if self.cash > 0:
            # 全仓买入 (简化逻辑)
            self.stock_cnt = int(self.cash / price)
            cost = self.stock_cnt * price
            self.cash -= cost
            print(f"[{time}] 🔵 买入 {code}: 价格 {price}, 数量 {self.stock_cnt}")
            self.trades.append({"action": "buy", "price": price, "time": time})

    def sell(self, price, time, code):
        if self.stock_cnt > 0:
            # 全仓卖出
            revenue = self.stock_cnt * price
            self.cash += revenue
            print(f"[{time}] 🔴 卖出 {code}: 价格 {price}, 余额 {self.cash:.2f}")
            self.trades.append({"action": "sell", "price": price, "time": time})
            self.stock_cnt = 0

# -----------------------------------------------------------
# 2. 回测主逻辑
# -----------------------------------------------------------
def run_backtest(code):
    # 配置：开启逐步回放 trigger_step
    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": True,  # <--- 关键：开启回放模式
        "skip_step": 0,        # 可以跳过前面一部分K线不回测
        "cbsp_strategy": CStrategySecondTheorem, # 您的策略
        "strategy_para": {"strict_open": True}
    })

    # 初始化数据源 (这里沿用您之前写好的本地驱动注入逻辑)
    # ... (此处省略注入代码，假设已注入 CFutuStockDriver_V6) ...
    # 1. 补充必要的导入 (如果文件头部没有的话)
from DataAPI.CommonStockAPI import CCommonStockApi
from KLine.KLine_Unit import CKLine_Unit
from Common.CEnum import DATA_FIELD
from Common.CTime import CTime
import pandas as pd
from datetime import datetime
import Chan  # 用于注入

class CFutuStockDriver_V6(CCommonStockApi):
    def __init__(self, code, k_type, begin_date, end_date, autype):
        super(CFutuStockDriver_V6, self).__init__(code, k_type, begin_date, end_date, autype)
        self.code = code
        self.k_type = k_type
        self.cache_dir = "stock_cache"  # 确保这个文件夹就在当前目录下

    def get_kl_data(self):
        # 根据级别匹配文件名后缀 (支持 30M 和 日线)
        lv_suffix = "K_30M" if self.k_type == KL_TYPE.K_30M else "K_DAY"
        file_path = os.path.join(self.cache_dir, f"{self.code}_{lv_suffix}.parquet")

        if not os.path.exists(file_path):
            print(f"⚠️ [回测警告] 缺失数据文件: {file_path}")
            return

        try:
            df = pd.read_parquet(file_path)
        except Exception as e:
            print(f"❌ 读取错误: {e}")
            return

        # --- 数据清洗与标准化 ---
        # 1. 统一列名小写
        df.columns = [c.lower() for c in df.columns]
        
        # 2. 映射常用列名
        col_map = {
            'time_key': 'time', 'code': 'code',
            'vol': 'volume', 'amount': 'turnover'
        }
        df.rename(columns=col_map, inplace=True)
        
        # 3. 按时间正序排列
        if 'time' in df.columns:
            df.sort_values("time", inplace=True)
        
        # --- 逐行转换 ---
        for _, row in df.iterrows():
            # A. 时间解析 (兼容字符串和datetime对象)
            raw_time = row['time']
            dt_obj = None
            if isinstance(raw_time, str):
                time_str = raw_time.replace("/", "-")
                if len(time_str) <= 10: time_str += " 00:00:00"
                if len(time_str) == 16: time_str += ":00"
                dt_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            elif isinstance(raw_time, pd.Timestamp):
                dt_obj = raw_time.to_pydatetime()
            elif isinstance(raw_time, datetime):
                dt_obj = raw_time
            else:
                dt_obj = pd.to_datetime(raw_time).to_pydatetime()

            # B. 构造 CTime 对象 (必须)
            final_time = CTime(dt_obj.year, dt_obj.month, dt_obj.day, dt_obj.hour, dt_obj.minute)

            # C. 构造 K线单元
            item_dict = {
                DATA_FIELD.FIELD_TIME: final_time,
                DATA_FIELD.FIELD_OPEN: float(row['open']),
                DATA_FIELD.FIELD_HIGH: float(row['high']),
                DATA_FIELD.FIELD_LOW: float(row['low']),
                DATA_FIELD.FIELD_CLOSE: float(row['close']),
                DATA_FIELD.FIELD_VOLUME: float(row.get('volume', 0.0)),
                DATA_FIELD.FIELD_TURNOVER: float(row.get('turnover', 0.0)),
                DATA_FIELD.FIELD_TURNRATE: 0.0
            }

            yield CKLine_Unit(item_dict)

    def SetBasciInfo(self):
        self.name = self.code

# 💉【关键步骤】强制替换 CChan 的数据获取接口
# 这样无论 data_src 填什么，都会执行上面的 CFutuStockDriver_V6
Chan.CChan.GetStockAPI = lambda self: CFutuStockDriver_V6

    # 初始化 CChan
    # 注意：这里不需要 load_stock_data，初始化时就会建立生成器
chan = CChan(
        code=code,
        begin_time="2023-01-01", # 回测开始时间
        end_time="2023-12-31",
        data_src=DATA_SRC.BAO_STOCK, # 占位符，实际用您注入的驱动
        lv_list=[KL_TYPE.K_30M],
        config=config,
        autype=AUTYPE.QFQ
    )

account = BacktestAccount(100000)

    # --- 逐K线回放循环 ---
    # chan 是一个生成器，每次 yield 都会返回当前的 CChan 对象快照
for snapshot_chan in chan:
        kl_data = snapshot_chan[KL_TYPE.K_30M] # 获取当前级别的快照
        
        # 获取最新的 K 线时间 (用于日志)
        current_klu = kl_data[-1][-1]
        
        # 检查策略是否产生信号
        # cbsp_strategy 是在 ChanConfig 中配置的策略实例
        # 我们可以检查 snapshot_chan.cbsp 列表是否有新信号
        
        # 更好的方法是直接调用策略的 update (框架内部已调用)，
        # 我们只需要检查是否产生了新的 cbsp (自定义买卖点)
        if hasattr(kl_data, 'cbsp_lst') and len(kl_data.cbsp_lst) > 0:
            last_cbsp = kl_data.cbsp_lst[-1]
            
            # 必须判断信号是否是"当前K线"刚刚产生的
            if last_cbsp.klu.idx == current_klu.idx:
                
                if last_cbsp.is_buy and account.stock_cnt == 0:
                    account.buy(current_klu.close, current_klu.time, code)
                    
                elif not last_cbsp.is_buy and account.stock_cnt > 0:
                    account.sell(current_klu.close, current_klu.time, code)

    # 结束汇报
print(f"最终权益: {account.cash:.2f}")

if __name__ == "__main__":
    # 记得在此处注入您的 CFutuStockDriver_V6
    # ...
    run_backtest("HK.00700")