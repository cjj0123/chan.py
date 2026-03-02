from typing import Iterable, List
from datetime import datetime
import os
import json
import pandas as pd
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
        print(f"   ❌ 找不到文件: {code} {kl_type.name}")
        return None
    return CCustomParquetAPI.robust_load_from_parquet(file_path)

def main():
    stock_code = "HK.00836"
    lv_config = KL_TYPE.K_30M
    history_file = "backtest_history_v4.json"
    
    print(f"\n🚀 [EVOMAP-QUANT] 启动卖点闭合型回测: {stock_code}")
    
    kl_units = force_load_data(stock_code, lv_config)
    if not kl_units: return

    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False, 
        "skip_step": 0,
        "bs_type": '1,1p,2,2s,3a,3b',
        "one_bi_zs": False,
        "print_warning": False,
    })

    try:
        print("   ⏳ [1/2] 正在计算缠论结构并匹配买卖点...")
        chan = CChan(
            code=stock_code,
            begin_time=kl_units[0].time,
            data_src=DATA_SRC.FUTU, # 内部已路由至 CCustomParquetAPI
            lv_list=[lv_config],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        # 获取所有 BSP 并按时间排序
        all_bsps = chan.get_bsp()
        
        trades = []
        current_buy = None
        
        for bsp in all_bsps:
            # is_buy 逻辑：缠论中买点 is_buy=True，卖点 is_buy=False
            # 某些版本可能通过 type 字符串中是否含撇号判断，这里使用内置属性
            is_buy_signal = bsp.is_buy
            
            if is_buy_signal:
                if current_buy is None: # 建立头寸
                    current_buy = {
                        "buy_time": str(bsp.klu.time),
                        "buy_price": bsp.klu.close,
                        "type": bsp.type2str()
                    }
            else:
                if current_buy is not None: # 遇到卖点平仓
                    profit = (bsp.klu.close - current_buy['buy_price']) / current_buy['buy_price'] * 100
                    trades.append({
                        "buy_time": current_buy['buy_time'],
                        "sell_time": str(bsp.klu.time),
                        "buy_price": current_buy['buy_price'],
                        "sell_price": bsp.klu.close,
                        "profit": profit,
                        "buy_type": current_buy['type'],
                        "sell_type": bsp.type2str()
                    })
                    current_buy = None # 重置，等待下一个买点
        
        # 结果保存
        result_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stock": stock_code,
            "trade_count": len(trades),
            "trades": trades,
            "summary": {
                "total_profit": sum([t['profit'] for t in trades]),
                "win_rate": len([t for t in trades if t['profit'] > 0]) / len(trades) * 100 if trades else 0
            }
        }
        
        with open(history_file, "w") as f:
            json.dump(result_entry, f, indent=2)
            
        print(f"   ✅ [2/2] 回测完成! 撮合交易对: {len(trades)}")
        print(f"   📈 累计盈亏: {result_entry['summary']['total_profit']:.2f}%")
        print(f"   🏆 胜率: {result_entry['summary']['win_rate']:.2f}%")
        
        if trades:
            print("\n📝 前 5 笔闭合交易详情:")
            for t in trades[:5]:
                print(f"      买: {t['buy_time']}({t['buy_type']}) -> 卖: {t['sell_time']}({t['sell_type']}) | 盈亏: {t['profit']:.2f}%")

    except Exception as e:
        print(f"   ❌ [EVOMAP-RECOVERY] 系统异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
