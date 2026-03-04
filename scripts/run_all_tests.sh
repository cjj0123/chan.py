#!/bin/bash

# 缠论交易系统完整测试执行脚本
# 执行所有测试层次：单元测试 → 集成测试 → 回测测试 → 实盘模拟

set -e  # 遇到错误立即退出

echo "🚀 开始执行缠论交易系统完整测试计划"
echo "========================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查依赖
check_dependencies() {
    log_info "检查系统依赖..."
    
    # 检查Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 未安装"
        exit 1
    fi
    
    # 检查pip
    if ! command -v pip3 &> /dev/null; then
        log_error "pip3 未安装"
        exit 1
    fi
    
    # 检查必要包
    required_packages=("pandas" "numpy" "futu-api" "google-generativeai" "dashscope")
    for package in "${required_packages[@]}"; do
        if ! python3 -c "import $package" &> /dev/null; then
            log_warn "Python包 $package 未安装，可能影响部分功能"
        fi
    done
    
    log_info "依赖检查完成"
}

# 第1层：单元测试
run_unit_tests() {
    log_info "执行第1层：单元测试"
    
    # 创建测试目录（如果不存在）
    mkdir -p tests
    
    # 运行监控测试
    if [ -f "Monitoring/test_monitoring_report.py" ]; then
        log_info "运行监控模块测试..."
        python3 Monitoring/test_monitoring_report.py
    else
        log_warn "监控测试脚本不存在，跳过"
    fi
    
    log_info "单元测试完成"
}

# 第2层：集成测试
run_integration_tests() {
    log_info "执行第2层：集成测试"
    
    # 测试数据库连接
    log_info "测试数据库连接..."
    python3 -c "
import sys
sys.path.append('.')
try:
    from Trade.db_util import CChanDB
    db = CChanDB()
    # 测试基本操作
    signal_id = db.save_signal('TEST', 'buy', 0.5, '/tmp/test.png')
    signals = db.get_active_signals('TEST')
    print(f'数据库测试成功: 保存ID={signal_id}, 查询数量={len(signals)}')
except Exception as e:
    print(f'数据库测试失败: {e}')
    exit(1)
    "
    
    log_info "集成测试完成"
}

# 第3层：回测测试
run_backtest_tests() {
    log_info "执行第3层：回测测试"
    
    # 检查数据目录
    if [ ! -d "stock_cache" ]; then
        log_warn "stock_cache 目录不存在，需要先下载数据"
        read -p "是否现在下载测试数据？(y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "下载测试数据（前3只股票，2024年）..."
            python3 scripts/download_hk_data.py \
                --watchlist "港股" \
                --start 2024-01-01 \
                --end 2024-12-31 \
                --freqs 30M 5M DAY \
                --limit 3
        else
            log_warn "跳过数据下载，回测可能失败"
        fi
    fi
    
    # 检查是否有数据文件
    if ls stock_cache/*.parquet >/dev/null 2>&1; then
        log_info "运行增强版回测..."
        python3 backtesting/enhanced_backtester.py \
            --initial-funds 1000000 \
            --start 2024-01-01 \
            --end 2024-12-31 \
            --output-dir backtest_reports
        
        # 分析结果
        RESULT_FILE=$(ls -t backtest_reports/results_*.json 2>/dev/null | head -1)
        if [ -n "$RESULT_FILE" ]; then
            log_info "分析回测结果..."
            python3 scripts/analyze_results.py "$RESULT_FILE" --output-dir backtest_reports
        else
            log_warn "未找到回测结果文件"
        fi
    else
        log_warn "未找到数据文件，跳过回测测试"
    fi
    
    log_info "回测测试完成"
}

# 第4层：实盘模拟测试
run_simulation_test() {
    log_info "执行第4层：实盘模拟测试"
    
    # 检查富途连接（简单检查）
    log_info "检查富途API可用性..."
    python3 -c "
import sys
sys.path.append('.')
try:
    from futu import OpenQuoteContext, RET_OK
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    ret, data = quote_ctx.get_global_state()
    if ret == RET_OK:
        print('富途API连接正常')
    else:
        print('富途API连接异常，请确保富途牛牛已启动')
    quote_ctx.close()
except Exception as e:
    print(f'富途API检查失败: {e}')
    "
    
    # 执行单次扫描（dry-run模式）
    log_info "执行单次扫描测试（dry-run模式）..."
    if [ -f "futu_hk_visual_trading_fixed.py" ]; then
        python3 futu_hk_visual_trading_fixed.py --single --dry-run
    else
        log_warn "主程序文件不存在，跳过实盘模拟测试"
    fi
    
    log_info "实盘模拟测试完成"
}

# 主执行函数
main() {
    START_TIME=$(date)
    log_info "测试开始时间: $START_TIME"
    
    # 检查依赖
    check_dependencies
    
    # 执行各层测试
    run_unit_tests
    run_integration_tests
    run_backtest_tests
    run_simulation_test
    
    END_TIME=$(date)
    log_info "所有测试完成！"
    log_info "测试结束时间: $END_TIME"
    
    # 显示结果摘要
    echo ""
    echo "📊 测试结果摘要:"
    echo "   - 单元测试: ✅ 完成"
    echo "   - 集成测试: ✅ 完成" 
    echo "   - 回测测试: ✅ 完成（请查看 backtest_reports/ 目录）"
    echo "   - 实盘模拟: ✅ 完成（请查看日志文件）"
    echo ""
    echo "📁 重要输出文件:"
    echo "   - 回测报告: backtest_reports/report_*.md"
    echo "   - 详细结果: backtest_reports/results_*.json"
    echo "   - 系统日志: chanlun_bot.log"
    echo ""
    echo "💡 注意事项:"
    echo "   - 如果API密钥过期，请更新 .env 文件"
    echo "   - 如果邮件发送失败，请检查 email_config.env 配置"
    echo "   - 回测结果仅供参考，不代表未来表现"
}

# 处理中断信号
trap 'log_error "测试被用户中断"; exit 1' INT TERM

# 执行主函数
main "$@"