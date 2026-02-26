from typing import Iterable, List
from datetime import datetime
import os
import json
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD, DATA_SRC
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.FutuAPI import CFutuAPI

def run_online_backtest(stock_code, begin_date, end_date):
    print(f"\n🚀 [EVOMAP-ONLINE] 启动富途在线回测: {stock_code}")
    print(f"   📅 周期: {begin_date} 至 {end_date}")
    
    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False, 
        "skip_step": 0,
        "bs_type": '1,1p,2,2s,3a,3b',
        "one_bi_zs": False,
        "print_warning": False,
    })

    try:
        # 使用 DATA_SRC.FUTU，现在它已经指向了增强版的 CFutuAPI
        chan = CChan(
            code=stock_code,
            begin_time=begin_date,
            end_time=end_date,
            data_src=DATA_SRC.FUTU,
            lv_list=[KL_TYPE.K_30M],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        all_bsps = chan.get_bsp()
        trades = []
        current_buy = None
        
        for bsp in all_bsps:
            if bsp.is_buy:
                if current_buy is None:
                    current_buy = {"price": bsp.klu.close, "time": str(bsp.klu.time), "type": bsp.type2str()}
            else:
                if current_buy is not None:
                    profit = (bsp.klu.close - current_buy['price']) / current_buy['price'] * 100
                    trades.append({
                        "buy_time": current_buy['time'],
                        "sell_time": str(bsp.klu.time),
                        "profit": profit,
                        "buy_type": current_buy['type'],
                        "sell_type": bsp.type2str()
                    })
                    current_buy = None
        
        print(f"   ✅ 完成! 撮合交易对: {len(trades)}")
        if trades:
            total_profit = sum([t['profit'] for t in trades])
            win_rate = len([t for t in trades if t['profit'] > 0]) / len(trades) * 100
            print(f"   📈 累计盈亏: {total_profit:.2f}% | 胜率: {win_rate:.2f}%")
            print("📝 最近 3 笔交易:")
            for t in trades[-3:]:
                print(f"      {t['buy_time']}({t['buy_type']}) -> {t['sell_time']}({t['sell_type']}) | {t['profit']:.2f}%")
        else:
            print("   ℹ️ 未能在该时间段内识别到闭合买卖点。")

    except Exception as e:
        print(f"   ❌ 在线回测失败: {e}")

if __name__ == "__main__":
    # 示例测试：回测腾讯控股 2024 年至今
    run_online_backtest("HK.00700", "2024-01-01", "2025-12-31")
