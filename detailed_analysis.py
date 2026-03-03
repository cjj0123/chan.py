import os
import json
import pandas as pd
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD, DATA_SRC
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.CustomParquetAPI import CCustomParquetAPI

def analyze_stock(stock_code, file_path):
    print(f"\n详细分析报告: {stock_code}")
    kl_units = CCustomParquetAPI.robust_load_from_parquet(file_path)
    
    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False, 
        "skip_step": 0,
        "bs_type": '1,1p,2,2s,3a,3b',
        "one_bi_zs": False,
        "print_warning": False,
    })

    try:
        chan = CChan(
            code=stock_code,
            begin_time=kl_units[0].time,
            data_src=DATA_SRC.FUTU,
            lv_list=[KL_TYPE.K_30M],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        all_bsps = chan.get_bsp()
        current_buy = None
        trades = []
        
        for bsp in all_bsps:
            if bsp.is_buy:
                if current_buy is None:
                    current_buy = {
                        "buy_time": str(bsp.klu.time),
                        "buy_price": bsp.klu.close,
                        "buy_type": bsp.type2str(),
                        "buy_dt": pd.to_datetime(str(bsp.klu.time))
                    }
            else:
                if current_buy is not None:
                    sell_time_str = str(bsp.klu.time)
                    sell_dt = pd.to_datetime(sell_time_str)
                    profit = (bsp.klu.close - current_buy['buy_price']) / current_buy['buy_price'] * 100
                    
                    # T+1 检查: 卖出日期必须在买入日期之后
                    t_plus_1 = sell_dt.date() > current_buy['buy_dt'].date()
                    
                    trades.append({
                        "buy_time": current_buy['buy_time'],
                        "buy_type": current_buy['buy_type'],
                        "sell_time": sell_time_str,
                        "sell_type": bsp.type2str(),
                        "profit": profit,
                        "t_plus_1": t_plus_1
                    })
                    current_buy = None
        
        return trades
    except Exception as e:
        print(f"分析 {stock_code} 出错: {e}")
        return []

def main():
    targets = [
        ("国投电力", "SH.600886", "chan.py/stock_cache/SH.600886_K_30M.parquet"),
        ("川投能源", "SH.600674", "chan.py/stock_cache/SH.600674_K_30M.parquet")
    ]
    
    for name, code, path in targets:
        trades = analyze_stock(code, path)
        print(f"\n--- {name} ({code}) 详细买卖点 (严格模式) ---")
        if not trades:
            print("没有撮合成功的交易。")
            continue
            
        print("{:<20} {:<6} {:<20} {:<6} {:<8} {:<6}".format("买入时间", "类型", "卖出时间", "类型", "盈亏", "T+1"))
        for t in trades:
            t1_str = "✅" if t['t_plus_1'] else "❌"
            loss_str = "⚠️止损" if t['profit'] < 0 else ""
            print("{:<20} {:<6} {:<20} {:<6} {:>7.2f}% {:<6} {}".format(
                t['buy_time'], t['buy_type'], t['sell_time'], t['sell_type'], t['profit'], t1_str, loss_str
            ))

if __name__ == "__main__":
    main()
