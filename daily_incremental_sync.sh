#!/bin/bash
# 自动每日增量更新 K 线数据 (适配 30m, 5m 等全周期)

# 1. 切换到项目根目录
cd /Users/jijunchen/Documents/Projects/Chanlun_Bot

# 2. 激活虚拟环境并执行更新命令
# 增量更新会读取各个股票本地的最大 date 向上补齐，速度极快
PYTHONPATH=. .venv/bin/python3 sync_all_history.py --markets US HK CN --timeframes day 30m 5m 1m >> daily_incremental_sync.log 2>&1

echo "✅ [$(date)] 增量 K线 同步完成" >> daily_incremental_sync.log
