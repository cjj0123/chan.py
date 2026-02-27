#!/bin/zsh
# ============================================
# A 股缠论视觉交易系统 - 扫描脚本
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
LOG_FILE="$LOG_DIR/cn_stock_$(date +%Y%m%d_%H%M).log"

# 切换到工作目录
cd $WORKSPACE

# 执行扫描
echo "========================================" >> $LOG_FILE
echo "A 股扫描开始：$(date '+%Y-%m-%d %H:%M:%S')" >> $LOG_FILE
echo "========================================" >> $LOG_FILE

$PYTHON -c "
from cn_stock_visual_trading import CNStockVisualTrading
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
    trader = CNStockVisualTrading(
        cn_watchlist_group='A 股',
        min_visual_score=70
    )
    trader.scan_and_trade()
    print('扫描完成')
except Exception as e:
    print(f'扫描异常：{e}')
    import traceback
    traceback.print_exc()
" >> $LOG_FILE 2>&1

echo "" >> $LOG_FILE
echo "扫描结束：$(date '+%Y-%m-%d %H:%M:%S')" >> $LOG_FILE
echo "========================================" >> $LOG_FILE
echo "" >> $LOG_FILE
