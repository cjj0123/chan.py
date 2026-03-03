# 港股缠论视觉策略 监控与报告模块

## 概述

`Monitoring` 模块为港股缠论视觉策略提供全面的监控和报告功能。它能够自动计算交易性能指标、生成HTML格式的每日报告，并通过邮件发送给用户。

## 功能特性

### 1. 性能指标计算 (`metrics.py`)
- **总盈亏 (P&L)**: 计算指定时间段内的总盈亏
- **胜率**: 计算盈利交易的比例
- **夏普比率**: 衡量风险调整后的收益
- **最大回撤**: 记录最大资金回撤幅度
- **交易统计**: 包括信号总数、已执行订单数、当前持仓数等

### 2. 报告生成与发送 (`reporter.py`)
- **HTML报告**: 使用Jinja2模板引擎生成结构化的HTML报告
- **邮件集成**: 支持通过SMTP服务器发送邮件报告
- **数据可视化**: 在报告中以表格形式展示持仓和交易详情

### 3. 自动集成
- 已集成到主交易程序 `futu_hk_visual_trading_fixed.py` 中
- 每次扫描交易完成后自动触发报告生成和发送

## 模块结构

```
Monitoring/
├── __init__.py          # 包初始化文件
├── metrics.py           # 性能指标计算器
├── reporter.py          # 报告生成器
├── test_monitoring_report.py  # 测试脚本
└── README_Monitoring.md # 本说明文件
```

## 使用方法

### 1. 配置邮件设置
在 `Config/config.yaml` 文件中添加邮件配置：

```yaml
email:
  smtp_server: "smtp.gmail.com"
  smtp_port: 587
  sender_email: "your_email@gmail.com"
  sender_password: "your_app_password"
  recipient_email: "recipient@example.com"
```

### 2. 手动测试报告功能
运行测试脚本来验证报告功能：

```bash
python3 Monitoring/test_monitoring_report.py
```

### 3. 自动报告
主交易程序会在每次扫描交易完成后自动生成并发送报告，无需手动干预。

## 依赖项

- pandas >= 1.3.0
- jinja2 >= 3.0.0
- sqlite3 (Python内置)

## 数据库要求

监控模块需要以下数据库表结构：

- `trading_signals`: 存储交易信号
- `trading_orders`: 存储交易订单  
- `trading_positions`: 存储当前持仓

如果数据库不存在，模块会自动创建这些表。

## 扩展性

该模块设计为可扩展的架构：

- **添加新指标**: 在 `CMetricsCalculator` 类中添加新的计算方法
- **自定义报告模板**: 修改 `_generate_html_report` 方法中的HTML模板
- **多渠道通知**: 可以在 `CReporter` 类中添加其他通知方式（如微信、Telegram等）

## 注意事项

1. **数据库连接**: 确保数据库路径配置正确
2. **邮件安全**: 建议使用应用专用密码而不是账户密码
3. **性能影响**: 报告生成过程可能会增加主程序的执行时间，建议在非交易时段运行
4. **数据完整性**: 报告的准确性依赖于数据库中的数据完整性

## 版本历史

- **v1.0.0**: 初始版本，包含基本的指标计算和HTML报告生成功能
- **v1.0.1**: 修复了pandas导入问题和配置加载问题
- **v1.0.2**: 添加了完整的测试脚本和文档