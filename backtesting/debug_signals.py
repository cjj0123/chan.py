#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting.UniversalBacktester import UniversalBacktester

def debug():
    # 使用 3 只标的，打印每个周期发现的所有买卖点
    watchlist = ["HK.00700", "HK.00836", "HK.02688"]
    tester = UniversalBacktester(market='HK', start_date='2025-01-01', end_date='2025-05-30', watchlist=watchlist, use_ml=False)
    
    loader = tester.get_loader_instance() if hasattr(tester, 'get_loader_instance') else None # 容错
    from BacktestDataLoader import BacktestDataLoader
    loader = BacktestDataLoader()
    
    from backtesting.backtester import BacktestDataIterator, BacktestStrategyAdapter
    data_iterator = BacktestDataIterator(
        loader=loader, watchlist=watchlist, freq="30M",
        start_date=tester.start_date, end_date=tester.end_date,
        lot_size_map={c:100 for c in watchlist}, required_freqs=["30M", "1M", "DAY"]
    )
    
    from ChanConfig import CChanConfig
    cfg = CChanConfig()
    cfg.bs_type = '1,1p,2,2s,3a,3b'
    adapter = BacktestStrategyAdapter(None, cfg, freq="30M")
    
    cnt_total = 0
    for t, snap in data_iterator:
        for c in watchlist:
            if c not in snap: continue
            sig = adapter.get_signal(c, snap[c], {c:100})
            if sig and sig['is_buy']:
                print(f"👉 [{t}] {c} -> {sig['bsp_type']} (Buy), Price={sig['signal_price']}")
                cnt_total += 1

    print(f"📊 扫描结束，共发现 {cnt_total} 个信号")

if __name__ == '__main__':
    debug()
