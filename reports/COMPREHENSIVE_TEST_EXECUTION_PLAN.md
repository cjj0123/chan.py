# 缠论交易系统全面测试执行计划

## 📋 执行摘要

本计划提供了一个完整的、分层次的测试执行方案，覆盖从单元测试到实盘模拟的所有测试阶段。基于项目现有的测试框架和文档，本计划整合了所有必要的命令、参数配置和预期结果。

**关键发现：**
- 项目已建立完整的测试层次结构（单元测试 → 集成测试 → 回测 → 实盘模拟）
- 增强版回测引擎支持精确的港股交易成本计算
- 存在已知问题需要修复（K_1M订阅问题、买入信号缺失等）
- 最近的回测报告显示策略在历史数据上表现良好（23.27%回报率）

## 🧪 测试层次结构

### 第1层：单元测试 - 验证独立模块正确性

#### 1.1 数据库工具测试
```bash
# 执行数据库单元测试
python3 -m pytest tests/test_db_util.py -v

# 或直接运行监控测试脚本
python3 Monitoring/test_monitoring_report.py
```

**预期结果：**
- ✅ 数据库增删改查操作正常
- ✅ 信号记录和订单管理功能正常
- ✅ 持仓查询功能正常

#### 1.2 配置管理测试
```bash
# 测试配置加载
python3 -c "
from Config.EnvConfig import EnvConfig
config = EnvConfig()
print('API密钥:', '已配置' if config.get('GEMINI_API_KEY') else '未配置')
print('邮件配置:', '已配置' if config.get('SMTP_SERVER') else '未配置')
"
```

**预期结果：**
- ✅ 配置文件正确加载
- ✅ 环境变量回退机制正常
- ⚠️ 如果API密钥过期，需要更新 `.env` 文件

#### 1.3 监控指标测试
```bash
# 运行监控指标测试
python3 Monitoring/test_monitoring_report.py
```

**预期结果：**
- ✅ P&L、夏普比率、最大回撤等指标计算正确
- ✅ 报告生成功能正常

### 第2层：集成测试 - 验证模块间协同工作

#### 2.1 策略与数据集成测试
```bash
# 测试缠论分析与数据库集成
python3 -c "
import sys
sys.path.append('.')
from futu_hk_visual_trading_fixed import FutuHKVisualTrading
from Trade.db_util import CChanDB

# 初始化组件
trader = FutuHKVisualTrading(dry_run=True)
db = CChanDB()

# 测试信号保存
signal_id = db.save_signal('HK.00700', 'sell', 0.85, '/tmp/chart.png')
print(f'信号保存ID: {signal_id}')

# 测试信号查询
signals = db.get_active_signals('HK.00700')
print(f'活跃信号数量: {len(signals)}')
"
```

**预期结果：**
- ✅ 策略能正确调用数据库保存信号
- ✅ 信号查询功能正常

#### 2.2 主程序与监控集成测试
```bash
# 测试报告生成集成
python3 -c "
import sys
sys.path.append('.')
from Monitoring.reporter import CReporter

reporter = CReporter()
success = reporter.send_daily_report(days=1, dry_run=True)
print(f'报告生成测试: {'成功' if success else '失败'}')
"
```

**预期结果：**
- ✅ HTML报告生成正常
- ✅ 邮件发送功能正常（dry_run模式）

### 第3层：端到端回测测试 - 评估策略历史表现

#### 3.1 数据准备阶段

**步骤1：下载历史数据**
```bash
# 下载测试数据（前10只股票，2024年全年）
python3 scripts/download_hk_data.py \
    --watchlist "港股" \
    --start 2024-01-01 \
    --end 2024-12-31 \
    --freqs 30M 5M DAY \
    --limit 10

# 验证数据下载
ls -la stock_cache/HK.*_K_30M.parquet | head -5
```

**预期结果：**
- ✅ 成功下载30M、5M、DAY级别K线数据
- ✅ 生成 `lot_size_config.json` 文件
- ✅ 数据文件大小合理（每只股票约几MB）

#### 3.2 基础回测执行

**步骤2：运行基础回测**
```bash
# 使用增强版回测引擎
python3 backtesting/enhanced_backtester.py \
    --initial-funds 1000000 \
    --start 2024-01-01 \
    --end 2024-12-31 \
    --watchlist HK.00700 HK.00836 HK.02688 \
    --output-dir backtest_reports

# 查看最新回测报告
ls -lt backtest_reports/report_*.md | head -1
```

**预期结果：**
- ✅ 回测成功完成
- ✅ 生成Markdown报告和JSON结果文件
- ✅ 报告包含完整的绩效指标

#### 3.3 参数优化回测

**步骤3：运行参数优化**
```bash
# 创建参数优化脚本
cat > optimize_params.py << 'EOF'
#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backtesting.enhanced_backtester import ParameterOptimizer, run_backtest

# 基础配置
base_config = {
    'initial_funds': 100000,
    'start_date': '2024-01-01',
    'end_date': '2024-12-31',
    'stocks': ['HK.00700', 'HK.00836'],
    'use_hk_costs': True
}

# 参数网格
param_grid = {
    'macd_fast': [8, 12],
    'macd_slow': [20, 26],
    'max_position_ratio': [0.2, 0.3]
}

# 运行优化
optimizer = ParameterOptimizer(base_config)
results_df = optimizer.grid_search(param_grid, run_backtest)

# 保存结果
results_df.to_csv('backtest_reports/optimization_results.csv', index=False)
print("参数优化完成，结果保存到 optimization_results.csv")
print(results_df.head(10))
EOF

# 执行参数优化
python3 optimize_params.py
```

**预期结果：**
- ✅ 完成参数网格搜索
- ✅ 生成优化结果CSV文件
- ✅ 找到最优参数组合

#### 3.4 结果分析

**步骤4：分析回测结果**
```bash
# 获取最新结果文件
RESULT_FILE=$(ls -t backtest_reports/results_*.json | head -1)

# 分析结果
python3 scripts/analyze_results.py $RESULT_FILE \
    --output-dir backtest_reports

# 查看分析报告
cat backtest_reports/analysis_report.md
```

**预期结果：**
- ✅ 生成资金曲线图 (`equity_curve.png`)
- ✅ 生成交易分布图 (`trade_distribution.png`)
- ✅ 生成详细分析报告

### 第4层：实盘模拟测试 - 验证完整交易流程

#### 4.1 单次扫描测试

**步骤1：执行单次扫描（模拟模式）**
```bash
# 确保富途牛牛已启动并连接
# 执行单次扫描测试
python3 futu_hk_visual_trading_fixed.py --single --dry-run

# 检查日志输出
tail -20 chanlun_bot.log
```

**预期结果：**
- ✅ 成功获取自选股列表
- ✅ 成功获取K线数据（使用K_30M周期）
- ✅ 成功进行缠论分析
- ✅ 生成图表文件
- ✅ 视觉评分正常（如果API密钥有效）
- ✅ 记录交易决策（模拟模式不实际下单）

#### 4.2 已知问题验证与修复

**问题1：K_1M订阅问题**
```bash
# 验证问题存在
python3 -c "
import sys
sys.path.append('.')
from futu_hk_visual_trading_fixed import FutuHKVisualTrading

trader = FutuHKVisualTrading(dry_run=True)
# 尝试获取K_1M数据（应该失败）
try:
    data = trader.fetch_kline_data('HK.00700', 'K_1M', 20)
    print('K_1M数据获取: 成功')
except Exception as e:
    print(f'K_1M数据获取: 失败 - {e}')
"

# 修复方案：统一使用K_30M
# 在 should_sell 方法中修改为：
# kline_data = self.fetch_kline_data(symbol, 'K_30M', 100)
```

**问题2：买入信号缺失**
```bash
# 验证买入信号功能缺失
grep -n "TODO: Add buy signal detection" futu_hk_visual_trading_fixed.py

# 修复方案：实现 should_buy() 方法
# 参考 reports/TEST_REPORT_AND_IMPROVEMENTS.md 中的改进方案
```

#### 4.3 完整实盘模拟

**步骤2：完整实盘模拟（需要有效API密钥）**
```bash
# 更新API密钥（如果过期）
# 编辑 .env 文件，更新 GEMINI_API_KEY 和 DASHSCOPE_API_KEY

# 执行完整实盘模拟
python3 futu_hk_visual_trading_fixed.py --single --dry-run

# 验证完整流程：
# 1. 数据获取 → 2. 缠论分析 → 3. 图表生成 → 4. 视觉评分 → 5. 交易决策 → 6. 报告生成
```

**预期结果：**
- ✅ 完整交易流程正常执行
- ✅ 视觉评分使用真实API调用
- ✅ 生成完整的HTML报告
- ✅ 邮件通知正常发送（如果配置正确）

### 第5层：性能与压力测试

#### 5.1 并发处理测试

**步骤1：高并发测试**
```bash
# 创建大股票列表进行测试
cat > large_watchlist.txt << EOF
HK.00700
HK.00836
HK.02688
HK.00288
HK.09885
HK.06682
HK.02259
HK.06603
HK.02357
HK.01109
# ... 添加更多股票
EOF

# 修改自选股组包含大量股票
# 然后执行扫描测试
python3 futu_hk_visual_trading_fixed.py --single --dry-run --timeout 300
```

**预期结果：**
- ✅ 系统能够处理大量股票
- ✅ 内存使用稳定
- ✅ 处理时间在可接受范围内（< 5分钟）

#### 5.2 长时间运行测试

**步骤2：长时间运行测试**
```bash
# 创建长时间运行脚本
cat > long_running_test.sh << 'EOF'
#!/bin/bash
echo "开始长时间运行测试..."
START_TIME=$(date)
for i in {1..24}; do
    echo "第 $i 小时测试: $(date)"
    python3 futu_hk_visual_trading_fixed.py --single --dry-run
    sleep 3600  # 等待1小时
done
END_TIME=$(date)
echo "测试开始时间: $START_TIME"
echo "测试结束时间: $END_TIME"
EOF

# 执行长时间测试（后台运行）
chmod +x long_running_test.sh
nohup ./long_running_test.sh > long_test.log 2>&1 &

# 监控内存使用
top -p $(pgrep -f long_running_test.sh) -d 60
```

**预期结果：**
- ✅ 无内存泄漏
- ✅ CPU使用率稳定
- ✅ 连续运行24小时无崩溃

## 📊 测试结果验证标准

### 成功标准
| 测试类型 | 成功标准 | 验证方法 |
|---------|---------|---------|
| 单元测试 | 所有测试通过 | pytest返回码0 |
| 集成测试 | 模块间数据流正常 | 日志无错误，功能正常 |
| 回测测试 | 生成完整报告，策略盈利 | 回测报告总回报率>0 |
| 实盘模拟 | 完整流程执行成功 | 日志显示各阶段完成 |
| 性能测试 | 资源使用稳定 | top/htop监控无异常 |

### 失败处理
- **API密钥问题**：更新 `.env` 文件中的密钥
- **邮件配置问题**：检查 `email_config.env` 配置
- **数据下载失败**：确保富途牛牛已启动并连接
- **回测结果为空**：检查数据文件是否存在，日期范围是否匹配

## 🚀 执行顺序建议

1. **先执行单元测试** - 确保基础模块正常
2. **再执行集成测试** - 验证模块间协作
3. **然后执行回测测试** - 评估策略有效性
4. **最后执行实盘模拟** - 验证完整交易流程
5. **性能测试可选** - 根据需要执行

## 📝 交付成果

完成所有测试后，将生成以下文件：

```
backtest_reports/
├── report_YYYYMMDD_HHMMSS.md      # 回测报告
├── results_YYYYMMDD_HHMMSS.json   # 详细结果
├── equity_curve.png               # 资金曲线
├── trade_distribution.png         # 交易分布
├── optimization_results.csv        # 参数优化结果
└── analysis_report.md             # 分析报告

logs/
├── backtest_enhanced.log          # 回测日志
├── data_download.log              # 数据下载日志
└── chanlun_bot.log                # 主程序日志
```

## ⚠️ 注意事项

1. **API密钥**：确保 `.env` 文件中的API密钥有效
2. **富途连接**：执行实盘模拟前确保富途牛牛已启动
3. **数据完整性**：回测前确保 `stock_cache/` 目录有完整数据
4. **网络环境**：视觉评分需要稳定的网络连接
5. **资源监控**：长时间运行时监控系统资源使用情况

## 🔧 故障排除指南

### 常见问题及解决方案

| 问题 | 现象 | 解决方案 |
|------|------|----------|
| API密钥过期 | 视觉评分失败 | 更新 `.env` 文件中的 `GEMINI_API_KEY` |
| 邮件发送失败 | SSL连接错误 | 检查 `email_config.env` 中的邮件服务器设置 |
| K_1M订阅失败 | 请求K线前未订阅 | 统一使用K_30M周期，避免混合使用 |
| 买入信号缺失 | 只能检测卖点 | 实现 `should_buy()` 方法 |
| 数据下载失败 | 获取自选股失败 | 确保富途牛牛已启动并连接行情服务器 |
| 回测结果为空 | 无有效时间点 | 检查数据文件是否存在，日期范围是否匹配 |

### 调试命令

```bash
# 查看详细日志
tail -f chanlun_bot.log

# 检查API密钥状态
grep -v "^#" .env | grep API

# 检查数据文件
ls -la stock_cache/ | wc -l

# 检查Python依赖
pip list | grep -E "(futu|pandas|google)"

# 内存使用监控
ps aux | grep python
```

---
**测试计划版本：1.0**  
**最后更新：2026-03-04**  
**执行此计划前请确保已阅读并理解所有注意事项**