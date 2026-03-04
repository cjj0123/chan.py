# 缠论视觉交易系统

![缠论框架](./Image/chan.py_image_1.svg)

**基于缠论的量化交易系统，支持A股和港股市场，集成大模型视觉评分功能**

## 🌟 核心功能

### 📊 双市场支持
- **A股市场**: `cn_stock_visual_trading.py` - A股缠论信号扫描与邮件通知（**不执行交易**）
- **港股市场**: `futu_hk_visual_trading_fixed.py` - 港股缠论信号扫描、视觉评分与**自动交易执行**

### 🤖 视觉智能评分
- **双模型支持**: 同时集成 Google Gemini 和 Alibaba Qwen 大模型
- **回退机制**: 当主模型不可用时自动切换到备用模型
- **智能过滤**: 仅对评分≥70分的高质量信号进行处理
- **时间窗口**: 4小时时间窗口过滤，避免重复信号

### 🔔 通知系统
- **邮件通知**: 自动发送包含缠论图表的交易报告
- **A股**: 仅提供信号扫描和通知
- **港股**: 支持真实交易执行（需配置Futu API）

### 📈 缠论核心算法
- **完整缠论实现**: 笔、线段、中枢、买卖点等核心元素
- **多级别分析**: 支持不同时间周期的缠论分析
- **可视化图表**: 自动生成专业的缠论分析图表

## 📁 项目目录结构

```
├── cn_stock_visual_trading.py      # A股主程序（仅扫描通知）
├── futu_hk_visual_trading_fixed.py # 港股主程序（支持交易执行）  
├── visual_judge.py                 # 视觉评分模块（Gemini + Qwen）
├── send_email_report.py            # 邮件发送模块
├── Chan.py                         # 缠论核心算法
├── ChanConfig.py                   # 缠论配置
├── config.py                       # 交易配置
├── scheduler_config.py             # 调度配置
├── crontab_cn_stock_trading.txt    # 定时任务配置
├── run_cn_stock_scan.sh            # 手动启动脚本
├── requirements.txt                # 依赖包列表
├── .env                            # API密钥配置
├── email_config.env                # 邮件配置
├── charts/                         # 生成的缠论图表
├── stock_cache/                    # 股票数据缓存
├── backtesting/                    # 回测系统
├── reports/                        # 项目文档和报告
├── chan_trading.db                 # 交易数据库
└── trading_data.db                 # 交易数据存储
```

## ⚙️ 快速开始

### 1. 环境要求
- Python 3.11+ (推荐)
- pip包管理器

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置API密钥
创建 `.env` 文件并配置API密钥：
```env
# Google Gemini API Key
GOOGLE_API_KEY=your_gemini_api_key

# DashScope API Key (Qwen)
DASHSCOPE_API_KEY=your_qwen_api_key
```

### 4. 配置邮件通知
创建 `email_config.env` 文件：
```env
# 邮件配置
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
RECIPIENT_EMAIL=recipient@example.com
```

### 5. 运行程序
- **A股扫描（仅通知）**: `python cn_stock_visual_trading.py`
- **港股扫描（可交易）**: 
  - 模拟模式: `python futu_hk_visual_trading_fixed.py --tag core_scan`
  - 真实交易: `python futu_hk_visual_trading_fixed.py --tag cas_execute`
- **手动启动**: `./run_cn_stock_scan.sh`

### 6. 定时任务
使用crontab设置定时任务：
```bash
# 编辑crontab
crontab -e

# 添加以下内容（根据实际路径调整）
*/5 * * * 1-5 /path/to/Chanlun_Bot/run_cn_stock_scan.sh
```

## 📋 功能模块说明

### 核心交易程序
- **A股程序**: 扫描A股缠论买卖点，支持1买、2买、3买、1卖、2卖、3卖，仅通过邮件发送报告
- **港股程序**: 基于Futu API的港股缠论分析，支持真实交易执行（买入/卖出订单）
- **视觉评分**: 使用大模型对缠论图表进行质量评分，确保信号质量

### 配置文件
- **`.env`**: 存储Google Gemini和DashScope API密钥
- **`email_config.env`**: 邮件服务器和账户配置
- **`config.py`**: 交易参数和策略配置
- **`scheduler_config.py`**: 扫描时间调度配置

### 数据存储
- **`charts/`**: 存储生成的缠论分析图表
- **`stock_cache/`**: 缓存股票历史数据，提高性能
- **`*.db`**: SQLite数据库，存储交易记录和信号

### 回测系统
- **`backtesting/`**: 独立的回测框架，支持策略验证
- **`reports/`**: 包含详细的回测报告和测试结果

## 🛡️ 开发原则

- **模块解耦**: 视觉判断逻辑与下单逻辑完全分离
- **安全第一**: A股仅提供通知，港股交易需明确指定执行模式
- **可扩展性**: 支持轻松添加新的市场和分析模型
- **稳定性**: 具备完善的错误处理和回退机制

## 📚 相关文档

详细使用说明和配置指南请参考 [`reports/`](./reports/) 目录中的文档：
- [A股扫描程序逻辑说明](./reports/A%20股扫描程序逻辑说明.md)
- [CN_STOCK_TRADING_README](./reports/CN_STOCK_TRADING_README.md)
- [BACKTEST_README](./reports/BACKTEST_README.md)
- [快速上手指南](./reports/quick_guide.md)

## 📞 联系方式

如有使用问题或建议，欢迎通过邮件联系或在GitHub上提交Issue。

---

**注意**: 本系统仅用于教育和研究目的，不构成投资建议。使用前请确保了解相关风险。