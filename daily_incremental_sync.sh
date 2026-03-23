#!/bin/bash
# 自动每日增量更新 K 线数据 (适配 30m, 5m 等全周期)
# [重要] launchd 在 macOS 下，bash 本身没有 ~/Documents 的磁盘访问权限。
# 解决方案：先用绝对路径切换目录，并在 plist 的 ProgramArguments 里给 Terminal/bash 授权。
# 参考：系统偏好设置 > 隐私与安全 > 完全磁盘访问权限 > 添加 /bin/bash

# 绝对路径避免 PATH 问题
PROJ=/Users/jijunchen/Documents/Projects/Chanlun_Bot
LOG="$PROJ/daily_incremental_sync.log"
PYTHON="$PROJ/.venv/bin/python3"

# 切换到项目根目录
cd "$PROJ" || { echo "[$(date)] ❌ 无法进入项目目录，退出" >> /tmp/chanlun_sync_error.log; exit 1; }

# 0. 杀死可能残留的旧后台同步进程，防并发冲突造成死锁
pkill -f sync_all_history.py 2>/dev/null || true
pkill -f daily_hot_scanner.py 2>/dev/null || true
sleep 1

# 1. 先扫描全球热点股，重写富途自选股 "热点_实盘" 分组
echo "🚀 [$(date)] 启动热点股扫描 (daily_hot_scanner.py)..." >> "$LOG"
PYTHONPATH="$PROJ" "$PYTHON" "$PROJ/scripts/daily_hot_scanner.py" >> "$LOG" 2>&1

# 2. 紧接着拉起同步，吞下新热点补全 K 线
echo "🚀 [$(date)] 启动 K 线数据增量补齐 (sync_all_history.py)..." >> "$LOG"
# 🛡️ 拿掉 1m，只拉 day 30m 5m，大幅减少 Futu 撞频率风险
PYTHONPATH="$PROJ" "$PYTHON" "$PROJ/sync_all_history.py" --markets US HK CN --timeframes day 30m 5m >> "$LOG" 2>&1

echo "✅ [$(date)] 港美A全套热点捕捉 + 增量 K线 同步完成" >> "$LOG"
