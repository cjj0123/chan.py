# 港股回测系统使用指南

## 📁 新增文件清单

本次实施新增以下文件：

| 文件 | 路径 | 功能 |
|------|------|------|
| 回测方案 | [`HK_BACKTEST_PLAN.md`](HK_BACKTEST_PLAN.md) | 完整的回测方案设计文档 |
| 数据下载 | [`scripts/download_hk_data.py`](scripts/download_hk_data.py) | 从富途 API 下载历史数据 |
| 增强引擎 | [`enhanced_backtester.py`](enhanced_backtester.py) | 增强的回测引擎（精确成本、参数优化） |
| 配置文件 | [`backtest_config.yaml`](backtest_config.yaml) | 回测配置参数 |
| 结果分析 | [`scripts/analyze_results.py`](scripts/analyze_results.py) | 回测结果分析与可视化 |
| 使用指南 | [`BACKTEST_README.md`](BACKTEST_README.md) | 本文档 |

---

## 🚀 快速开始

### 步骤 1：下载历史数据

```bash
# 下载前 10 只股票的 30M/5M/DAY 数据（2024 年全年）
python3 scripts/download_hk_data.py \
    --watchlist "港股" \
    --start 2024-01-01 \
    --end 2024-12-31 \
    --freqs 30M 5M DAY \
    --limit 10

# 下载全部股票数据（可能需要较长时间）
python3 scripts/download_hk_data.py \
    --watchlist "港股" \
    --start 2024-01-01 \
    --end 2025-12-31 \
    --freqs 30M 5M DAY
```

**输出：**
- `stock_cache/HK.XXXXX_K_30M.parquet` - 30 分钟 K 线
- `stock_cache/HK.XXXXX_K_5M.parquet` - 5 分钟 K 线
- `stock_cache/HK.XXXXX_K_DAY.parquet` - 日线 K 线
- `stock_cache/lot_size_config.json` - 每手股数配置

### 步骤 2：运行基础回测

```bash
# 使用原有回测引擎
python3 backtester.py --backtest

# 使用增强回测引擎
python3 enhanced_backtester.py \
    --initial-funds 100000 \
    --start 2024-01-01 \
    --end 2024-12-31 \
    --watchlist HK.00700 HK.00836 HK.02688
```

### 步骤 3：分析回测结果

```bash
# 分析 JSON 结果
python3 scripts/analyze_results.py backtest_reports/results_*.png

# 生成可视化图表和分析报告
python3 scripts/analyze_results.py \
    backtest_reports/results_20260228_*.json \
    --output-dir backtest_reports/
```

---

## 📋 详细使用说明

### 数据下载脚本参数

```bash
python3 scripts/download_hk_data.py [选项]

必选参数:
  --start TEXT          开始日期 (YYYY-MM-DD)
  --end TEXT            结束日期 (YYYY-MM-DD)

可选参数:
  --watchlist TEXT      自选股组名 (默认：港股)
  --freqs TEXT [TEXT ...]  频率列表 (默认：30M 5M DAY)
  --cache-dir TEXT      缓存目录 (默认：stock_cache)
  --overwrite           覆盖已存在的文件
  --limit INT           限制下载股票数量 (0=不限制)

示例:
  # 下载腾讯控股 2024 年数据
  python3 scripts/download_hk_data.py --start 2024-01-01 --end 2024-12-31 \
      --watchlist "港股" --limit 1

  # 下载指定频率
  python3 scripts/download_hk_data.py --start 2024-01-01 --end 2024-06-30 \
      --freqs 30M DAY
```

### 增强回测引擎参数

```bash
python3 enhanced_backtester.py [选项]

可选参数:
  --initial-funds FLOAT   初始资金 (默认：100000)
  --start TEXT            开始日期 (默认：2024-01-01)
  --end TEXT              结束日期 (默认：2025-12-31)
  --watchlist TEXT [TEXT ...]  股票列表
  --no-hk-costs           不使用港股精确成本
  --output-dir TEXT       输出目录 (默认：backtest_reports)

示例:
  # 使用默认配置
  python3 enhanced_backtester.py

  # 自定义配置
  python3 enhanced_backtester.py \
      --initial-funds 200000 \
      --start 2024-06-01 \
      --end 2024-12-31 \
      --watchlist HK.00700 HK.00836
```

### 结果分析脚本参数

```bash
python3 scripts/analyze_results.py [结果文件] [选项]

必选参数:
  results_file          JSON 格式的回测结果文件

可选参数:
  --output-dir TEXT     输出目录 (默认：.)
  --no-plots            不生成图表

示例:
  # 完整分析（生成图表和报告）
  python3 scripts/analyze_results.py backtest_reports/results.json

  # 仅打印摘要
  python3 scripts/analyze_results.py backtest_reports/results.json --no-plots
```

---

## 📊 输出文件说明

### 回测报告目录结构

```
backtest_reports/
├── report_20260228_153000.md      # Markdown 格式回测报告
├── results_20260228_153000.json   # JSON 格式详细结果
├── trades_20260228_153000.csv     # CSV 格式交易明细
├── equity_curve.png               # 资金曲线图
└── trade_distribution.png         # 交易分布图
```

### Markdown 报告内容

```markdown
# 港股缠论回测详细报告

## 📋 1. 回测参数
- 回测范围：2024-01-01 至 2024-12-31
- 初始资金：100,000.00 HKD
- 主频率：30M
- 使用港股精确成本：是

## 📊 2. 核心绩效指标
- 期末总资产：XXX,XXX.XX HKD
- 总回报率：XX.XX%
- 年化回报率：XX.XX%
- 最大回撤：XX.XX%
- 夏普比率：X.XX

## 📈 3. 交易统计
- 总交易次数：XX
- 买入次数：XX
- 卖出次数：XX
- 胜率：XX.XX%
- 盈亏比：X.XX

## 💰 4. 交易成本明细
- 总交易成本：X,XXX.XX HKD
  - 佣金：XXX.XX HKD
  - 印花税：XXX.XX HKD
  - 交易费：XX.XX HKD
  - 中央结算费：XX.XX HKD

## 📝 5. 交易明细
| 时间 | 代码 | 动作 | 数量 | 价格 | 成本 |
|------|------|------|------|------|------|
| ...  | ...  | ...  | ...  | ...  | ...  |
```

---

## 🔧 配置说明

### 修改回测配置

编辑 [`backtest_config.yaml`](backtest_config.yaml)：

```yaml
# 修改回测区间
backtest:
  start_date: "2024-01-01"
  end_date: "2025-06-30"

# 修改股票列表
stocks:
  - "HK.00700"  # 腾讯
  - "HK.00836"  # 华润电力
  - "HK.02688"  # 新奥能源

# 修改缠论参数
chan:
  macd:
    fast: 12
    slow: 26
    signal: 9
  bs_type: "1,1p,2,2s,3a,3b"

# 修改仓位配置
trading:
  max_position_ratio: 0.25  # 单票最大 25% 仓位
```

---

## 📈 策略优化

### 参数网格搜索

使用 [`enhanced_backtester.py`](enhanced_backtester.py:356) 中的 `ParameterOptimizer` 类：

```python
from enhanced_backtester import ParameterOptimizer, run_backtest

# 基础配置
base_config = {
    'initial_funds': 100000,
    'start_date': '2024-01-01',
    'end_date': '2024-12-31',
}

# 参数网格
param_grid = {
    'macd_fast': [8, 12, 16],
    'macd_slow': [20, 26, 32],
    'macd_signal': [6, 9, 12],
}

# 运行优化
optimizer = ParameterOptimizer(base_config)
results = optimizer.grid_search(param_grid, run_backtest)

# 查看最优结果
print(results.head(10))
```

---

## ⚠️ 注意事项

### 数据下载
1. 确保富途牛牛已启动并连接到行情服务器
2. 下载大量数据可能需要较长时间，请耐心等待
3. 建议先下载少量股票测试，确认配置正确

### 回测执行
1. 首次运行前确保已安装依赖：`pip3 install pandas numpy pyarrow matplotlib`
2. 回测结果依赖于历史数据质量，请确保数据完整
3. 增强引擎使用港股精确成本计算，结果更准确

### 结果分析
1. 回测结果仅供参考，不代表未来表现
2. 注意检查最大回撤是否在可接受范围内
3. 建议进行多参数组合测试，验证策略稳定性

---

## 🐛 故障排除

### 问题：数据下载失败

```
❌ 获取自选股失败：...
```

**解决方案：**
1. 检查富途牛牛是否已启动
2. 确认自选股组名称正确（默认"港股"）
3. 检查网络连接

### 问题：回测结果为空

```
❌ 无有效时间点进行回测
```

**解决方案：**
1. 检查 `stock_cache/` 目录是否有数据文件
2. 确认回测日期范围与数据日期范围匹配
3. 检查股票代码格式是否正确（如 `HK.00700`）

### 问题：导入错误

```
ImportError: No module named 'futu'
```

**解决方案：**
```bash
pip3 install futu-api
```

---

## 📞 技术支持

如有问题，请检查：
1. [`HK_BACKTEST_PLAN.md`](HK_BACKTEST_PLAN.md) - 完整方案设计
2. 日志文件：`backtest_enhanced.log`、`data_download.log`
3. 现有回测文件：[`backtester.py`](backtester.py)、[`BacktestDataLoader.py`](BacktestDataLoader.py)
