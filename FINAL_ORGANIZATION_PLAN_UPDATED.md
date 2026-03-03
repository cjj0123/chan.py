# Chanlun Bot 最终整理方案（最终版）

## 核心主程序（保留于根目录）

### 港股交易系统
- `futu_hk_visual_trading_fixed.py` - 【核心】港股视觉交易系统（修复版，当前主力）
- `HKMarket.py` - 港股市场相关代码

### A股扫描系统  
- `cn_stock_visual_trading.py` - A股视觉交易系统（邮件通知版，当前定时任务使用）

### 通用核心模块
- `visual_judge.py` - 视觉评分模块（支持 Gemini 和 Qwen 双模型）
- `send_email_report.py` - 邮件发送模块

### 配置文件
- `config.py` - 交易配置
- `ChanConfig.py` - 缠论配置
- `email_config.env` - 邮件配置
- `scheduler_config.py` - 交易时间配置
- `load_api_key.py` - API密钥加载

### 核心算法模块
- `Chan.py` - 缠论核心算法
- `Common/` - 通用组件
- `Bi/`, `Seg/`, `KLine/`, `BuySellPoint/`, `Plot/` - 缠论各组件

## 整理措施

### 1. 移至 archive/ 目录
- `futu_hk_visual_trading.py` - 港股视觉交易系统（原版）
- `futu_hk_visual_trading_live_final.py` - 港股视觉扫描引擎
- `scan_cn_stocks_visual.py` - A股视觉扫描程序（备选轻量级程序）
- `scan_and_save_signals.py` - 午休扫描脚本（非核心功能）
- `execute_pending_signals.py` - 执行待定信号（非核心功能）
- `close_all_positions.py` - 平仓所有持仓（非核心功能）
- `hk_visual_backtest_30m.py` - 港股视觉回测系统（非核心功能）
- 各种 `_bak`, `_temp`, `_final` 结尾的文件
- 所有 `test_*.py` 测试文件（除了核心功能必需的）

### 2. 移至 backtesting/ 目录（独立的回测系统）
- `backtester.py` - 回测系统（这是一个独立的系统，不被主程序直接调用，用于策略验证）
- `enhanced_backtester.py`
- 各种 backtest_* 文件
- `backtest_reports/` 目录
- 相关回测配置和结果文件

### 3. 移至 scripts/ 目录
- `run_scheduled_scan.sh`
- 各种 cron 配置文件
- 其他辅助脚本

### 4. 保持现有目录结构
- `charts/` - A股图表
- `charts_hk_scan/` - 港股扫描图表
- `hk_backtest_with_visual/` - 港股回测图表
- `logs/` - 日志目录

## 关于回测系统的说明

`backtester.py` 是一个独立的回测系统，主要用于：
- 策略验证和参数优化
- 历史数据回测
- 性能评估

该系统不被主交易程序直接调用，而是作为一个独立的工具用于开发和验证交易策略。因此，它应该被移到 backtesting/ 目录中，而不是作为核心运行文件保留在根目录。

## 执行优先级

### 第一步：创建目录并移动文件
```bash
mkdir -p archive backtesting scripts
```

### 第二步：移动非核心文件
- 移动旧版本和测试文件到 archive/
- 移动回测相关文件到 backtesting/
- 移动脚本文件到 scripts/

### 第三步：验证核心功能
- 确保 `futu_hk_visual_trading_fixed.py` 正常工作
- 确保 `cn_stock_visual_trading.py` 正常工作
- 确保视觉评分系统正常工作

### 第四步：更新文档
- 更新 README.md 说明新的目录结构
- 更新定时任务配置（如果路径发生变化）

## 注意事项
- 在执行整理前，确保所有核心功能都经过测试
- 保留必要的依赖文件，如 `send_email_report.py` 如果核心程序需要的话
- 确保 cron 配置文件指向正确的程序路径
- 保留必要的 README 文件说明系统架构