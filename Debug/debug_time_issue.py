#!/usr/bin/env python3
"""调试脚本：诊断 K 线时间戳重复问题"""

import sys
import pandas as pd
sys.path.insert(0, '.')

from Common.CTime import CTime
from Common.CEnum import KL_TYPE
from backtester import BacktestKLineUnit

# 加载 30M 数据
df = pd.read_parquet('stock_cache/HK.00700_K_30M.parquet')
df = df.sort_values(by='time_key')

print('🔍 模拟 BacktestKLineUnit 创建过程:')
klines = []
prev_ctime = None
prev_ts = None

for i, row in df.head(20).iterrows():
    ts = pd.to_datetime(row['time_key'])
    
    # 创建 BacktestKLineUnit
    klu = BacktestKLineUnit(
        timestamp=ts,
        open_p=float(row['open']),
        high_p=float(row['high']),
        low_p=float(row['low']),
        close_p=float(row['close']),
        volume=int(row['volume']),
        kl_type=KL_TYPE.K_30M
    )
    
    # 检查 CTime
    ctime = klu.time
    print(f'  [{i}] {ctime} ts={ctime.ts}', end='')
    
    if prev_ctime is not None:
        if ctime.ts <= prev_ts:
            print(f' ⚠️ 时间戳不递增！(prev={prev_ctime} ts={prev_ts})')
        elif ctime.ts == prev_ts:
            print(f' ⚠️ 时间戳重复！(prev={prev_ctime} ts={prev_ts})')
        else:
            print(f' ✓')
    else:
        print()
    
    prev_ctime = ctime
    prev_ts = ctime.ts
    klines.append(klu)

print()
print('🔍 检查 CTime 的 __gt__ 比较:')
for i in range(len(klines)-1):
    curr = klines[i]
    next_k = klines[i+1]
    result = next_k.time > curr.time
    print(f'  [{i}] {curr.time} < [{i+1}] {next_k.time} : {result}')
