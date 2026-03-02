#!/bin/zsh
# ============================================
# 港股缠论视觉交易系统 - 定时扫描脚本
# 使用方法：配合 cron 或手动执行
# ============================================

# 设置环境变量
export PATH=/usr/local/bin:/usr/bin:/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/opt/homebrew/bin
export PYTHON=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3
export WORKSPACE=/Users/jijunchen/.openclaw/workspace/chan.py
export LOG_DIR=/Users/jijunchen/.openclaw/workspace/logs
export GOOGLE_API_KEY=AIzaSyCyOShkz9hhPPLxYrI6Oc4eHq_I6muZF0Q

# 确保日志目录存在
mkdir -p $LOG_DIR

# 获取当前时间
CURRENT_HOUR=$(date +%H)
CURRENT_MIN=$(date +%M)
CURRENT_TIME="${CURRENT_HOUR}${CURRENT_MIN}"
LOG_FILE="$LOG_DIR/hk_trading_$(date +%Y%m%d)_${CURRENT_TIME}.log"

# 切换到工作目录
cd $WORKSPACE

# 执行扫描
echo "========================================" >> $LOG_FILE
echo "扫描开始: $(date '+%Y-%m-%d %H:%M:%S')" >> $LOG_FILE
echo "========================================" >> $LOG_FILE

$PYTHON -c "
from futu_hk_visual_trading_fixed import FutuHKVisualTrading
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('$LOG_FILE'),
        logging.StreamHandler()
    ]
)

try:
    trader = FutuHKVisualTrading(
        hk_watchlist_group='港股',
        min_visual_score=70,
        max_position_ratio=0.2,
        dry_run=True  # 模拟盘模式 (实盘需改为 False)
    )
    trader.scan_and_trade()
    trader.close_connections()
    print('扫描完成')
except Exception as e:
    print(f'扫描异常: {e}')
    import traceback
    traceback.print_exc()
" >> $LOG_FILE 2>&1

echo "" >> $LOG_FILE
echo "扫描结束: $(date '+%Y-%m-%d %H:%M:%S')" >> $LOG_FILE
echo "========================================" >> $LOG_FILE
echo "" >> $LOG_FILE
