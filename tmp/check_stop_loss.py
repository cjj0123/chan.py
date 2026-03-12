
import sys
from pathlib import Path
import os

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from futu import OpenHKTradeContext, OpenQuoteContext, RET_OK, TrdEnv
except ImportError:
    print("Futu API not installed")
    sys.exit(1)

from config import TRADING_CONFIG, CHAN_CONFIG
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC, AUTYPE
from datetime import datetime, timedelta

def calculate_atr(kline_list, period=14):
    if not kline_list or len(kline_list) < period + 1:
        return 0.0
    import numpy as np
    tr_list = []
    klines_for_atr = kline_list[-(period+1):]
    for i in range(1, len(klines_for_atr)):
        current = klines_for_atr[i]
        previous = klines_for_atr[i-1]
        tr = max(current.high - current.low, 
                 abs(current.high - previous.close), 
                 abs(current.low - previous.close))
        tr_list.append(tr)
    return float(np.mean(tr_list)) if tr_list else 0.0

def main():
    dry_run = TRADING_CONFIG.get('dry_run', True)
    trd_env = TrdEnv.SIMULATE if dry_run else TrdEnv.REAL
    
    print(f"Connecting to Futu (Env: {trd_env})...")
    trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    
    try:
        ret, data = trd_ctx.position_list_query(trd_env=trd_env)
        if ret != RET_OK:
            print(f"Failed to query positions: {data}")
            return
            
        if data.empty:
            print("No current positions found.")
            return
            
        print(f"\n{'Code':<10} {'Qty':<10} {'Cost':<10} {'Current':<10} {'ATR':<10} {'Stop Price':<10}")
        print("-" * 70)
        
        for _, row in data.iterrows():
            code = row['code']
            qty = float(row['qty'])
            if qty <= 0: continue
            
            cost_price = float(row['cost_price'])
            
            # Get current quote
            ret_q, data_q = quote_ctx.get_market_snapshot([code])
            current_price = 0.0
            if ret_q == RET_OK:
                current_price = float(data_q.iloc[0]['last_price'])
            
            # Calculate ATR
            begin_time = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
            chan = CChan(
                code=code,
                begin_time=begin_time,
                data_src=DATA_SRC.FUTU,
                lv_list=[KL_TYPE.K_30M],
                config=CChanConfig(CHAN_CONFIG),
                autype=AUTYPE.QFQ
            )
            
            atr_value = 0.0
            if chan.lv_list and len(chan[chan.lv_list[0]]) > 0:
                kl_list = list(chan[chan.lv_list[0]].klu_iter())
                atr_value = calculate_atr(kl_list)
            
            # Bot's logic: stop_price = highest - (atr * 2)
            # Since we don't have the tracked highest, we use current_price as a baseline
            # or cost_price if current is lower.
            highest = max(cost_price, current_price)
            stop_price = highest - (atr_value * 2.0)
            
            print(f"{code:<10} {qty:<10.0f} {cost_price:<10.3f} {current_price:<10.3f} {atr_value:<10.3f} {stop_price:<10.3f}")
            
    finally:
        trd_ctx.close()
        quote_ctx.close()

if __name__ == "__main__":
    main()
