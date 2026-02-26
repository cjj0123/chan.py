import os
import json
import pandas as pd
import glob
from datetime import datetime
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD, DATA_SRC
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.CustomParquetAPI import CCustomParquetAPI

def get_30m_stocks():
    files = glob.glob("stock_cache/*_K_30M.parquet")
    stocks = []
    for f in files:
        # 提取股票代码，例如 stock_cache/HK.00836_K_30M.parquet -> HK.00836
        basename = os.path.basename(f)
        code = basename.split('_K_30M')[0]
        stocks.append((code, f))
    return stocks

def run_backtest(stock_code, file_path):
    print(f"\n🔍 正在回测: {stock_code} ...")
    
    # 加载数据
    kl_units = CCustomParquetAPI.robust_load_from_parquet(file_path)
    if not kl_units:
        print(f"   ⚠️ 数据为空，跳过")
        return None

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
        trades = []
        current_buy = None
        
        for bsp in all_bsps:
            if bsp.is_buy:
                if current_buy is None:
                    current_buy = {"price": bsp.klu.close, "time": str(bsp.klu.time)}
            else:
                if current_buy is not None:
                    profit = (bsp.klu.close - current_buy['price']) / current_buy['price'] * 100
                    trades.append(profit)
                    current_buy = None
        
        if not trades:
            return {"code": stock_code, "trades": 0, "profit": 0, "win_rate": 0}
            
        win_rate = len([p for p in trades if p > 0]) / len(trades) * 100
        return {
            "code": stock_code,
            "trades": len(trades),
            "profit": sum(trades),
            "win_rate": win_rate
        }
    except Exception as e:
        print(f"   ❌ 出错: {e}")
        return None

def main():
    stocks = get_30m_stocks()
    print(f"🚀 发现 {len(stocks)} 个待回测标的 (30M 级别)")
    
    results = []
    for code, path in stocks:
        res = run_backtest(code, path)
        if res:
            results.append(res)
            print(f"   ✅ 完成: 交易 {res['trades']} 次 | 累计盈亏 {res['profit']:.2f}% | 胜率 {res['win_rate']:.2f}%")

    if not results:
        print("\n❌ 未能生成任何回测结果。")
        return

    print("\n" + "="*50)
    print("📊 汇总统计报表 (严格笔 + 卖点平仓)")
    print("="*50)
    df = pd.DataFrame(results)
    df = df.sort_values(by="profit", ascending=False)
    print(df.to_string(index=False))
    
    print("\n🏆 整体平均胜率: {:.2f}%".format(df['win_rate'].mean()))
    print("💰 整体平均收益: {:.2f}%".format(df['profit'].mean()))

if __name__ == "__main__":
    main()
