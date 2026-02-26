from typing import Iterable, List
from datetime import datetime
import os
import json
import pandas as pd
import glob
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD, DATA_SRC
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.CustomParquetAPI import CCustomParquetAPI

def force_load_data(code, kl_type: KL_TYPE):
    kl_type_str = kl_type.name.lower()
    possible_paths = [
        f"stock_cache/{code}_{kl_type_str}.parquet",
        f"stock_cache/{code.replace('.', '')}_{kl_type_str}.parquet",
        f"stock_cache/{code}_K_30M.parquet",
        f"stock_cache/{code}_k_30m.parquet"
    ]
    
    file_path = None
    for p in possible_paths:
        if os.path.exists(p):
            file_path = p
            break
            
    if not file_path:
        print(f"   ❌ [EvoMap-Diag] 找不到文件: {code} {kl_type.name}")
        return None

    print(f"   ✅ [1/4] 正在增强加载: {file_path}")
    return CCustomParquetAPI.robust_load_from_parquet(file_path)

def main():
    stock_code = "HK.00836"
    lv_config = KL_TYPE.K_30M
    history_file = "backtest_history.json"
    
    print(f"\n🚀 [EVOMAP-QUANT] 启动增强型回测: {stock_code}")
    
    kl_units = force_load_data(stock_code, lv_config)
    if not kl_units: return

    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False, 
        "skip_step": 0,
        "bs_type": '1,1p,2,2s,3a,3b',
        "one_bi_zs": False,
        "print_warning": True,
    })

    try:
        print("   ⏳ [3/4] 正在计算缠论结构...")
        # 🛠️ 修复：使用 DATA_SRC.FUTU 并确保 CCustomParquetAPI 已就绪
        # 在 Chan.py 的 GetStockAPI 中，FUTU 被映射到了 CCustomParquetAPI
        chan = CChan(
            code=stock_code,
            begin_time=kl_units[0].time,
            data_src=DATA_SRC.FUTU, # 改回枚举值
            lv_list=[lv_config],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        bsp_list = []
        for bsp in chan.get_bsp():
            bsp_list.append({
                "time": str(bsp.klu.time),
                "type": bsp.type2str(),
                "price": bsp.klu.close
            })
        
        trade_count = len(bsp_list)
        
        result_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stock": stock_code,
            "trade_count": trade_count,
            "signals": bsp_list,
            "config": {"bi_strict": True, "one_bi_zs": False}
        }
        
        with open(history_file, "a") as f:
            f.write(json.dumps(result_entry) + "\n")
            
        print(f"   ✅ [4/4] 回测完成! 识别到买卖点: {trade_count}")
        if trade_count == 0:
            print("   💡 [EvoMap-Advice] 严格模式无信号。建议下一次尝试 'bi_strict=False'。")
        else:
            for s in bsp_list:
                print(f"      📍 信号: {s['type']} | 时间: {s['time']} | 价格: {s['price']}")

    except Exception as e:
        print(f"   ❌ [EVOMAP-RECOVERY] 系统异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
