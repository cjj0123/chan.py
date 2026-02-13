import os
import glob
import pandas as pd
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE
import DataAPI 
from web_app_qjtFUTU import CFutuStockDriver_V3

# --- 劫持逻辑保持不变 ---
class SimpleDriver:
    def __init__(self, df): self.df = df
    def get_full_data(self, *args, **kwargs): return self.df

CURRENT_DF = None
def patched_get_stock_api(*args, **kwargs): return SimpleDriver(CURRENT_DF)
DataAPI.CreateStockAPI = patched_get_stock_api
_original_get_stock_api = patched_get_stock_api

def run_backtest_scanner():
    global CURRENT_DF
    SCAN_LEVEL = KL_TYPE.K_5M
    CACHE_DIR = os.path.join(os.getcwd(), "stock_cache")
    INITIAL_CASH = 100000.0
    COMMISSION = 0.0003
    
    config = CChanConfig()
    config.bs_type = '1,1p,2,2s,3a,3b,1s,2s,3s'
    config.zs_algo = 'normal'
    config.bi_strict = False
    
    print(f"{'='*70}\n🚀 缠论回测系统(终极兼容版) | 初始资金: {INITIAL_CASH}\n{'='*70}")

    cache_files = glob.glob(os.path.join(CACHE_DIR, f"*{SCAN_LEVEL.name}*.parquet"))
    
    for file_path in cache_files:
        code = os.path.basename(file_path).split(f"_{SCAN_LEVEL.name}")[0]
        try:
            # 1. 读取并暴力清洗数据
            raw_df = pd.read_parquet(file_path)
            raw_df.columns = [c.lower() for c in raw_df.columns]
            
            # --- 🌟 关键：强制寻找并转换时间列 ---
            t_col = next((c for c in ['time', 'date', 'item_time', 'timestamp'] if c in raw_df.columns), raw_df.columns[0])
            
            # 构建标准的 OHLCVT 结构
            clean_df = pd.DataFrame()
            # 尝试将时间转换为 datetime 类型，这是大多数回测引擎最喜欢的格式
            clean_df['time'] = pd.to_datetime(raw_df[t_col])
            clean_df['open'] = raw_df['open'].astype(float)
            clean_df['high'] = raw_df['high'].astype(float)
            clean_df['low'] = raw_df['low'].astype(float)
            clean_df['close'] = raw_df['close'].astype(float)
            clean_df['volume'] = raw_df['volume'].astype(float) if 'volume' in raw_df.columns else 0.0
            
            # 排序，确保时间轴正确
            clean_df = clean_df.sort_values('time').reset_index(drop=True)
            
            CURRENT_DF = clean_df

            # 2. 实例化
            chan = CChan(
                code=code,
                begin_time=str(clean_df['time'].iloc[0]),
                data_src=DATA_SRC.FUTU, 
                lv_list=[SCAN_LEVEL],
                config=config,
                autype=AUTYPE.QFQ
            )

            mg_data = chan[SCAN_LEVEL]
            bsp_list = sorted(mg_data.bs_point_lst.lst, key=lambda x: x.klu.idx)
            
            # --- 3. 模拟交易 ---
            cash, hold_share, entry_price = INITIAL_CASH, 0, 0
            trades_count, win_count = 0, 0

            for bsp in bsp_list:
                # 获取信号发生时的价格 (使用 K 线收盘价)
                price = bsp.klu.klu_list[-1].close
                bsp_type = bsp.type2str()
                
                if hold_share == 0 and bsp.is_buy and "3" in bsp_type:
                    hold_share = (cash * (1 - COMMISSION)) / price
                    cash, entry_price = 0, price
                    trades_count += 1
                elif hold_share > 0 and not bsp.is_buy:
                    cash = hold_share * price * (1 - COMMISSION)
                    if price > entry_price: win_count += 1
                    hold_share = 0

            final_val = cash if hold_share == 0 else hold_share * mg_data.lst[-1].close
            ret = (final_val - INITIAL_CASH) / INITIAL_CASH
            wr = (win_count / trades_count) if trades_count > 0 else 0

            print(f"[{code:<10}] 收益: {ret:>7.2%} | 胜率: {wr:>6.1%} | 交易数: {trades_count}")

        except Exception as e:
            print(f"[{code:<10}] ❌ 出错: {e}")

if __name__ == "__main__":
    run_backtest_scanner()