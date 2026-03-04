# 通用核心模块作用及调用关系

## 视觉评分模块 (`visual_judge.py`)

### 作用
- 实现 AI 视觉评分，支持 Gemini 和 Qwen 双重回退机制
- 需要 30M 和 5M 双级别图表进行评分
- 返回评分、建议操作和分析理由

### 被调用情况
- `futu_hk_visual_trading_fixed.py`: 第35行 `from visual_judge import VisualJudge`
- `cn_stock_visual_trading.py`: 第54行 `from visual_judge import VisualJudge`

## 缠论核心模块 (`Chan.py`, `ChanConfig.py`)

### 作用
- `Chan.py`: 缠论核心算法实现
- `ChanConfig.py`: 缠论配置定义
- 提供多级别分析、笔、线段、中枢、买卖点等缠论核心功能

### 被调用情况
- `futu_hk_visual_trading_fixed.py`: 
  - 第26行 `from Chan import CChan`
  - 第27行 `from ChanConfig import CChanConfig`
  - 多处使用 CChan 进行分析和图表生成
- `cn_stock_visual_trading.py`:
  - 第45行 `from Chan import CChan`
  - 第46行 `from ChanConfig import CChanConfig`
  - 多处使用 CChan 进行分析和图表生成

## 邮件发送模块 (`send_email_report.py`)

### 作用
- 发送包含图表的交易报告邮件
- 处理邮件模板和附件

### 被调用情况
- `futu_hk_visual_trading_fixed.py`: 第36行 `from send_email_report import send_stock_report`
- `cn_stock_visual_trading.py`: 第55行 `from send_email_report import send_stock_report`

## 配置模块 (`config.py`, `ChanConfig.py`, `email_config.env`, `scheduler_config.py`)

### 作用
- `config.py`: 交易配置（最小视觉评分、仓位比例等）
- `ChanConfig.py`: 缠论配置（已在上面说明）
- `email_config.env`: 邮件服务器配置
- `scheduler_config.py`: 交易时间配置

### 被调用情况
- 两个主程序都使用这些配置文件进行相应设置

## 总结
这些通用核心模块是两个主程序（港股和A股）共同依赖的基础组件，必须保留在根目录以确保两个程序都能正常访问和使用。它们提供了视觉评分、缠论分析、邮件发送等关键功能，是整个系统的核心支撑。