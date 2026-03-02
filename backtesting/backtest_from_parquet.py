import os
import pandas as pd
from datetime import datetime, timedelta
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from DataAPI.CommonStockAPI import CCommonStockApi
from KLine.KLine_Unit import CKLine_Unit
import Chan

# ==============================================================================
# 1. 增强版调试驱动 (带详细路径打印)
# ==============================================================================
class CFutuStockDriver_V3(CCommonStockApi):
    def __init__(self, code, k_type, begin_date, end_date, autype):
        super(CFutuStockDriver_V3, self).__init__(code, k_type, begin_date, end_date, autype)
        self.code = code
        self.k_type = k_type
        # 使用绝对路径，确保不走丢
        self.cache_dir = os.path.abspath("stock_cache") 

    def get_kl_data(self):
        # 1. 确定文件后缀
        if self.k_type == KL_TYPE.K_30M:
            lv_suffix = "K_30M"
        elif self.k_type == KL_TYPE.K_5M:
            lv_suffix = "K_5M"
        else:
            lv_suffix = "K_DAY" 

        # 2. 构造并检查路径
        file_name = f"{self.code}_{lv_suffix}.parquet"
        file_path = os.path.join(self.cache_dir, file_name)

        print(f"   [驱动] 正在尝试读取: {file_path}")
        if not os.path.exists(file_path):
            print(f"   ❌ [错误] 文件不存在! 请检查 stock_cache 目录下是否有 {file_name}")
            return

        # 3. 读取数据
        try:
            df = pd.read_parquet(file_path)
        except Exception as e:
            print(f"   ❌ [错误] Parquet 读取失败: {e}")
            return

        # 4. 数据预处理
        df.columns = [c.lower() for c in df.columns]
        # 兼容不同的列名格式
        col_map = {'time_key': 'time', 'code': 'code', 'vol': 'volume', 'amount': 'turnover'}
        df.rename(columns=col_map, inplace=True)
        
        if 'time' not in df.columns:
            print(f"   ❌ [错误] 数据缺少 'time' 列，现有列: {df.columns}")
            return

        df.sort_values("time", inplace=True)
        
        # 5. 逐行生成 K 线
        count = 0
        for _, row in df.iterrows():
            raw_time = row['time']
            # 解析时间
            if isinstance(raw_time, str):
                dt_obj = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
            else:
                dt_obj = pd.to_datetime(raw_time).to_pydatetime()

            final_time = CTime(dt_obj.year, dt_obj.month, dt_obj.day, dt_obj.hour, dt_obj.minute)
            
            # 过滤逻辑 (调试模式下尽量不过滤)
            if self.begin_date and final_time < self.begin_date: continue
            if self.end_date and final_time > self.end_date: continue

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
            count += 1
        
        if count == 0:
            print(f"   ⚠️ [警告] 文件读取成功但未生成任何K线 (可能被日期过滤掉了)")
        else:
            print(f"   ✅ [成功] 加载了 {count} 根K线")

    def SetBasciInfo(self):
        self.name = self.code

# 注入驱动
Chan.CChan.GetStockAPI = lambda self: CFutuStockDriver_V3

# ==============================================================================
# 2. 回测核心逻辑
# ==============================================================================
def run_parquet_backtest(parquet_file):
    if not os.path.exists(parquet_file):
        print(f"❌ 找不到扫描结果文件: {parquet_file}")
        return

    df_signals = pd.read_parquet(parquet_file)
    print(f"📂 加载扫描结果，共 {len(df_signals)} 个信号")
    
    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": True, 
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False, 
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs_type": '1,1p,2,2s,3a,3b',
        "print_warning": False,
    })

    results = []

    for index, row in df_signals.iterrows():
        code = row['code']
        signal_time_str = row['time'] # 格式如 2026-02-11 10:15
        signal_type = row['type']
        buy_price = row['price']
        
        print(f"\n⚡ 正在回测: {code} | 目标买点: {signal_time_str}")

        # --- 🛠️ 关键修改：begin_time 设为 None，读取所有数据 ---
        chan = CChan(
            code=code,
            begin_time=None,  # 彻底关闭时间过滤，防止数据没进来
            end_time=None,
            data_src="custom:local", 
            lv_list=[KL_TYPE.K_5M], 
            config=config,
            autype=AUTYPE.QFQ
        )

        is_holding = False
        entry_idx = -1
        kline_count = 0
        
        # 循环回放每一根K线
        for snapshot_chan in chan:
            # 获取主级别K线列表
            kline_list_obj = snapshot_chan 
            
            # --- 🛠️ 关键修改：空列表检查，防止 IndexError ---
            if not kline_list_obj or len(kline_list_obj) == 0:
                continue

            # 获取最新K线
            current_klu = kline_list_obj[-1]
            kline_count += 1
            
            # 构造时间字符串用于对比
            t = current_klu.time
            curr_time_str = f"{t.year}-{t.month:02d}-{t.day:02d} {t.hour:02d}:{t.minute:02d}"
            
            # --- 调试打印：每100根打印一次，证明数据在跑 ---
            if kline_count % 100 == 0:
                print(f"   ... 回放进度: {curr_time_str} | 价格: {current_klu.close}")

            # 1. 寻找买点 (时间匹配)
            if not is_holding:
                if curr_time_str == signal_time_str:
                    is_holding = True
                    entry_idx = current_klu.idx
                    print(f"   🔵 【买入】 时间: {curr_time_str} | 价格: {current_klu.close}")
            
            # 2. 持仓监控 (卖点/止损)
            elif is_holding:
                if current_klu.idx <= entry_idx: continue

                # 检查卖点信号
                bsp_list = kline_list_obj.bs_point_lst.lst
                if len(bsp_list) > 0:
                    last_bsp = bsp_list[-1]
                    # 必须是当前K线刚产生的信号
                    if last_bsp.klu.idx == current_klu.idx and not last_bsp.is_buy:
                        sell_price = current_klu.close
                        profit = (sell_price - buy_price) / buy_price * 100
                        print(f"   🔴 【卖出】 信号: {last_bsp.type2str()} | 价格: {sell_price} | 收益: {profit:.2f}%")
                        results.append({"code": code, "profit": profit, "reason": last_bsp.type2str()})
                        is_holding = False
                        break 
                
                # 止损 (5%)
                if current_klu.close < buy_price * 0.95:
                     print(f"   💀 【止损】 价格: {current_klu.close} | 收益: -5.00%")
                     results.append({"code": code, "profit": -5.0, "reason": "止损"})
                     is_holding = False
                     break

    if results:
        print("\n" + "="*40)
        print(pd.DataFrame(results))
    else:
        print("\n⚠️ 本次回测未产生交易 (请检查上方日志是否有 '✅ [成功] 加载' 字样)")

if __name__ == "__main__":
    # 自动查找最新的扫描结果
    import glob
    files = glob.glob("stock_cache/scan_result_*.parquet")
    if files:
        # 按时间排序取最新
        parquet_path = max(files, key=os.path.getctime)
        print(f"自动选择最新文件: {parquet_path}")
        run_parquet_backtest(parquet_path)
    else:
        print("❌ 没有找到扫描结果文件 (stock_cache/scan_result_*.parquet)")