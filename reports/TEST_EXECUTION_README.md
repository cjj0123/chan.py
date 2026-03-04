# 测试执行指南

## 🚀 快速开始

### 1. 环境准备
```bash
# 确保富途牛牛已启动并连接行情服务器
# 确保API密钥已配置（.env 文件）
# 确保邮件配置已设置（email_config.env 文件）

# 安装必要依赖
pip3 install -r requirements.txt
```

### 2. 执行完整测试
```bash
# 赋予执行权限
chmod +x scripts/run_all_tests.sh

# 执行完整测试计划
./scripts/run_all_tests.sh
```

### 3. 查看结果
```bash
# 查看回测报告
ls -la backtest_reports/
cat backtest_reports/report_*.md

# 查看系统日志
tail -50 chanlun_bot.log

# 查看测试执行日志
cat test_execution.log
```

## ⚙️ 自定义测试配置

编辑 [`config/test_config.yaml`](../config/test_config.yaml) 文件来自定义测试参数：

- **测试执行选项**: 选择要执行的测试层次
- **回测参数**: 设置初始资金（默认100万港币）、日期范围、股票列表
- **实盘模拟**: 配置dry-run模式和超时时间
- **数据下载**: 自定义自选股组和K线频率

## 📊 预期结果

### 成功标准
- ✅ 单元测试：所有模块功能正常
- ✅ 集成测试：模块间数据流正常
- ✅ 回测测试：生成完整报告，策略盈利（>0%回报率）
- ✅ 实盘模拟：完整交易流程执行成功

### 输出文件
```
backtest_reports/
├── report_YYYYMMDD_HHMMSS.md      # 回测报告（包含23.27%回报率示例）
├── results_YYYYMMDD_HHMMSS.json   # 详细结果
├── equity_curve.png               # 资金曲线图
└── trade_distribution.png         # 交易分布图

logs/
├── test_execution.log             # 测试执行日志
├── backtest_enhanced.log          # 回测日志
└── chanlun_bot.log                # 主程序日志
```

## 🐛 故障排除

### 常见问题
1. **API密钥过期**：更新 `.env` 文件中的 `GEMINI_API_KEY`
2. **邮件发送失败**：检查 `email_config.env` 配置
3. **数据下载失败**：确保富途牛牛已启动
4. **回测结果为空**：检查 `stock_cache/` 目录是否有数据

### 调试命令
```bash
# 检查API密钥
grep -v "^#" .env | grep API

# 检查数据文件
ls -la stock_cache/ | wc -l

# 查看详细日志
tail -f chanlun_bot.log
```

## 📝 参考文档

- [全面测试执行计划](COMPREHENSIVE_TEST_EXECUTION_PLAN.md)
- [测试结果示例](TEST_EXECUTION_EXAMPLE.md)
- [回测系统使用指南](BACKTEST_README.md)

---
**注意**: 测试结果仅供参考，不代表未来表现。请在实盘前充分验证策略。