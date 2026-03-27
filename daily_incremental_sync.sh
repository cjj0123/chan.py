#!/bin/bash
# 自动每日增量更新 K 线数据 (适配 30m, 5m 等全周期)
# [重要] launchd 在 macOS 下，bash 本身没有 ~/Documents 的磁盘访问权限。
# 解决方案：
# 1. 脚本头部 set -e：确保热点扫描失败即终止，不执行错误的同步。
# 2. 系统 Python 绕过：使用 /usr/local/bin/python3 绕过 venv 的 pyvenv.cfg 权限封锁。
# 3. 环境变量注入：手动补全 PYTHONPATH 包含项目路径和 venv 的库。

set -e  # 👈 严格模式：任何一步出错立即停止

# 环境配置
PROJ="/Users/jijunchen/Documents/Projects/Chanlun_Bot"
LOG="/tmp/daily_incremental_sync.log"  # 👈 建议写到 /tmp 下，权限最稳
PYTHON="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11"  # 👈 使用与 venv 匹配的 3.11 系统二进制
VENV_LIB="$PROJ/.venv/lib/python3.11/site-packages"

# 注入 PYTHONPATH
export PYTHONPATH="$PROJ:$VENV_LIB"

# 切换到项目根目录
cd "$PROJ" || { echo "[$(date)] ❌ 无法进入项目目录，退出" >> /tmp/chanlun_sync_error.log; exit 1; }

echo "--------------------------------------------------------" >> "$LOG"
echo "🕒 [$(date)] 启动自动化流水线 (System Python Mode)" >> "$LOG"

# 0. 杀死可能残留的旧后台同步进程，防并发冲突造成死锁
pkill -f sync_all_history.py 2>/dev/null || true
pkill -f daily_hot_scanner.py 2>/dev/null || true
sleep 1

# 1. 扫描全球热点股
echo "🚀 [$(date)] Hot stock scan started" >> "$LOG"
"$PYTHON" "$PROJ/scripts/daily_hot_scanner.py" >> "$LOG" 2>&1

# 2. 增量 K 线补齐
echo "🚀 [$(date)] K-line sync started" >> "$LOG"
# 🛡️ 拿掉 1m，只拉 day 30m 5m，大幅减少 Futu 撞频率风险
"$PYTHON" "$PROJ/sync_all_history.py" --markets US HK CN --timeframes day 30m 5m >> "$LOG" 2>&1

echo "✅ [$(date)] Full sync pipeline completed successfully" >> "$LOG"
