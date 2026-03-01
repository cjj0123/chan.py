# 港股缠论交易系统 - 历史回测方案

## 📋 目录

1. [现有架构分析](#1-现有架构分析)
2. [问题诊断与改进点](#2-问题诊断与改进点)
3. [回测系统设计方案](#3-回测系统设计方案)
4. [实施步骤](#4-实施步骤)
5. [配置参数说明](#5-配置参数说明)
6. [使用示例](#6-使用示例)

---

## 1. 现有架构分析

### 1.1 核心组件

当前项目已具备以下回测相关组件：

| 组件 | 文件 | 功能 | 状态 |
|------|------|------|------|
| 回测引擎 | [`backtester.py`](backtester.py) | 主回测逻辑、策略适配、交易模拟 | ✅ 基础功能完成 |
| 数据加载器 | [`BacktestDataLoader.py`](BacktestDataLoader.py) | Parquet 数据加载、K 线格式转换 | ✅ 基础功能完成 |
| 实盘交易 | [`futu_hk_visual_trading_fixed.py`](futu_hk_visual_trading_fixed.py:50) | 富途 API 对接、缠论分析、视觉评分 | ✅ 生产就绪 |
| 缠论核心 | [`Chan.py`](Chan.py) | 缠论算法实现（笔、线段、中枢、买卖点） | ✅ 核心引擎 |
| 港股市场 | [`HKMarket.py`](HKMarket.py) | 港股每手股数查询 | ⚠️ 功能单一 |

### 1.2 数据流架构

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  stock_cache/   │ ──► │ BacktestDataLoader│ ──► │ BacktestKLineUnit │
│  *.parquet      │     │  load_kline_data() │     │  兼容性数据结构   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  回测报告.md     │ ◄── │ BacktestReporter │ ◄── │ BacktestBroker  │
│  绩效统计        │     │  generate_report() │     │  交易执行/资金管理│
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                        ▲
                                                        │
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  CChan 缠论实例  │ ◄── │ BacktestStrategy │ ◄── │ DataIterator    │
│  买卖点识别      │     │ Adapter.get_signal()│   │  时间序列迭代    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

### 1.3 现有回测流程

[`basic_mode_backtest()`](backtester.py:514) 函数实现了基础回测流程：

```python
# 1. 初始化组件
chan_config = CChanConfig()
loader = BacktestDataLoader()
broker = BacktestBroker(initial_funds=100000.0)
strategy_adapter = BacktestStrategyAdapter(mock_trader, chan_config)

# 2. 数据迭代器
data_iterator = BacktestDataIterator(loader, watchlist, "30M", start_date, end_date)

# 3. 主循环 - 按时间迭代
for current_time, snapshot in data_iterator:
    for code in watchlist:
        # 获取缠论信号
        signal = strategy_adapter.get_signal(code, snapshot[code])
        # 执行交易
        if signal:
            broker.execute_trade(...)

# 4. 生成报告
reporter.generate_report(performance_results)
```

---

## 2. 问题诊断与改进点

### 2.1 识别的问题

经过分析，发现以下 **5-7 个潜在问题源**：

| # | 问题 | 影响 | 优先级 |
|---|------|------|--------|
| 1 | **数据覆盖不足** - stock_cache 中仅有少量股票数据 | 无法进行多股票组合回测 | 🔴 高 |
| 2 | **每手股数硬编码** - DEFAULT_LOT_SIZES 手动配置 | 交易数量计算可能错误 | 🟡 中 |
| 3 | **视觉评分缺失** - 回测跳过视觉评分环节 | 信号质量无法过滤 | 🟡 中 |
| 4 | **清算价格简化** - 持仓按成本价清算 | 最终收益计算不准确 | 🟡 中 |
| 5 | **时间轴对齐问题** - 多频率数据可能不同步 | 信号生成时机偏差 | 🟠 中低 |
| 6 | **交易成本简化** - 固定 0.1% 费率 | 港股印花税/佣金计算不精确 | 🟢 低 |
| 7 | **无参数优化** - 缺少参数遍历功能 | 无法优化策略参数 | 🟢 低 |

### 2.2 根本原因分析（Root Cause Analysis）

**核心问题 1：数据覆盖不足**
- **原因**: 数据缓存目录仅有 3 只港股的日线/分钟线数据
- **影响**: 回测结果缺乏统计显著性
- **验证方法**: 检查 `stock_cache/` 目录文件数量

**核心问题 2：每手股数硬编码**
- **原因**: 回测环境无法调用富途 API 获取实时每手股数
- **影响**: 买入数量计算错误，可能导致资金利用率偏差
- **验证方法**: 对比 [`DEFAULT_LOT_SIZES`](backtester.py:506) 与实际值

---

## 3. 回测系统设计方案

### 3.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           港股回测系统 v2.0                              │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │  数据获取层  │  │  数据处理层  │  │  策略引擎层  │  │  交易执行层  │    │
│  │             │  │             │  │             │  │             │    │
│  │ • Futu API  │  │ • Parquet   │  │ • CChan     │  │ • Broker    │    │
│  │ • 历史 K 线   │  │ • 数据转换   │  │ • 买卖点识别 │  │ • 仓位管理   │    │
│  │ • 每手股数   │  │ • 时间对齐   │  │ • 信号过滤   │  │ • 成本计算   │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
│                                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                      │
│  │  报告生成层  │  │  参数优化层  │  │  可视化层   │                      │
│  │             │  │             │  │             │                      │
│  │ • Markdown  │  │ • 网格搜索   │  │ • 资金曲线   │                      │
│  │ • JSON 统计  │  │ • 参数遍历   │  │ • 回撤分析   │                      │
│  │ • CSV 明细   │  │ • 最优组合   │  │ • 信号分布   │                      │
│  └─────────────┘  └─────────────┘  └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流设计

```
Step 1: 数据准备
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ 富途 API 获取  │───►│ Parquet 存储 │───►│ 回测时加载   │
│ 历史 K 线数据  │    │ stock_cache/ │    │ BacktestKLineUnit │
└──────────────┘    └──────────────┘    └──────────────┘

Step 2: 信号生成
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ K 线数据输入  │───►│ CChan 缠论计算│───►│ BSP 买卖点输出│
└──────────────┘    └──────────────┘    └──────────────┘

Step 3: 交易执行
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ 信号 + 仓位   │───►│ Broker 执行  │───►│ 交易记录     │
│ 资金检查     │    │ 买入/卖出     │    │ 持仓更新     │
└──────────────┘    └──────────────┘    └──────────────┘

Step 4: 报告生成
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ 交易记录     │───►│ 绩效计算     │───►│ Markdown 报告 │
│ 资金曲线     │    │ 统计指标     │    │ JSON/CSV 导出 │
└──────────────┘    └──────────────┘    └──────────────┘
```

### 3.3 核心类设计

#### 3.3.1 数据加载增强

```python
class EnhancedBacktestDataLoader(BacktestDataLoader):
    """增强的数据加载器，支持：
    1. 自动从 Futu API 下载缺失数据
    2. 批量获取每手股数信息
    3. 数据完整性校验
    """
    
    def download_missing_data(self, code: str, freq: str, start_date: str, end_date: str):
        """从富途 API 下载缺失的历史数据"""
        pass
    
    def get_lot_size_map(self, codes: List[str]) -> Dict[str, int]:
        """批量获取每手股数"""
        pass
```

#### 3.3.2 交易成本精确计算

```python
class HKStockBroker(BacktestBroker):
    """港股交易经纪商，精确计算交易成本：
    - 佣金：0.03% (最低 3 港元)
    - 印花税：0.1% (向上取整)
    - 交易费：0.00565%
    - 中央结算费：0.002%
    """
    
    def calculate_hk_costs(self, amount: float, is_buy: bool) -> float:
        """计算港股交易总成本"""
        commission = max(3.0, amount * 0.0003)
        stamp_duty = math.ceil(amount * 0.001) if is_buy else math.ceil(amount * 0.001)
        trading_fee = amount * 0.0000565
        clearing_fee = amount * 0.00002
        return commission + stamp_duty + trading_fee + clearing_fee
```

#### 3.3.3 视觉评分模拟

```python
class MockVisualJudge:
    """回测环境下的视觉评分模拟器
    基于历史信号特征进行评分：
    - 买卖点类型权重
    - 中枢位置评分
    - MACD 背离强度
    """
    
    def score_signal(self, chan_result: Dict) -> float:
        """根据缠论分析结果模拟视觉评分"""
        base_score = 50
        # 一类买卖点加分
        if '1 买' in chan_result['bsp_type'] or '1 卖' in chan_result['bsp_type']:
            base_score += 30
        # 中枢震荡加分
        if chan_result.get('zs_cnt', 0) > 0:
            base_score += 10
        return min(100, base_score)
```

### 3.4 回测模式设计

| 模式 | 描述 | 适用场景 |
|------|------|----------|
| **Basic** | 基础回测，使用默认参数 | 快速验证策略逻辑 |
| **Advanced** | 高级回测，支持自定义参数 | 详细策略分析 |
| **Parameter Sweep** | 参数遍历优化 | 寻找最优参数组合 |
| **Walk-Forward** | 滚动窗口回测 | 验证策略稳定性 |

---

## 4. 实施步骤

### 4.1 第一阶段：数据准备（1-2 天）

```bash
# Step 1.1: 检查现有数据
ls -la stock_cache/

# Step 1.2: 下载缺失的历史数据
python3 -c "
from futu import *
from datetime import datetime

quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

# 获取自选股列表
ret, data = quote_ctx.get_user_security('港股')
codes = data['code'].tolist()

# 下载每只股票的 30M/5M/DAY 数据
for code in codes[:10]:  # 先测试前 10 只
    for freq in [KLType.K_30M, KLType.K_5M, KLType.K_DAY]:
        ret, data = quote_ctx.get_history_kline(
            code, 
            ktype=freq,
            start='2024-01-01',
            end='2025-12-31'
        )
        if ret == RET_OK:
            data.to_parquet(f'stock_cache/{code}_K_{freq.name}.parquet')
            print(f'✅ {code} {freq.name} 下载成功')

quote_ctx.close()
"

# Step 1.3: 获取每手股数信息
python3 -c "
from futu import *
quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

ret, data = quote_ctx.get_user_security('港股')
codes = data['code'].tolist()

lot_size_map = {}
for code in codes:
    ret, info = quote_ctx.get_stock_basicinfo(Market.HK, [code])
    if ret == RET_OK:
        lot_size_map[code] = info.iloc[0]['lot_size']

import json
with open('lot_size_config.json', 'w') as f:
    json.dump(lot_size_map, f, indent=2)

quote_ctx.close()
print('✅ 每手股数配置已保存')
"
```

### 4.2 第二阶段：回测引擎增强（2-3 天）

```python
# Step 2.1: 创建增强的回测引擎
# 文件：enhanced_backtester.py

from backtester import BacktestBroker, BacktestReporter, BacktestStrategyAdapter
from BacktestDataLoader import BacktestDataLoader
import json

class EnhancedBacktestBroker(BacktestBroker):
    """港股精确交易成本计算"""
    
    HK_COST_RATES = {
        'commission': 0.0003,      # 佣金 0.03%
        'commission_min': 3.0,     # 最低 3 港元
        'stamp_duty': 0.001,       # 印花税 0.1%
        'trading_fee': 0.0000565,  # 交易费
        'clearing_fee': 0.00002,   # 中央结算费
    }
    
    def calculate_hk_cost(self, amount: float, is_buy: bool) -> float:
        commission = max(self.HK_COST_RATES['commission_min'], 
                        amount * self.HK_COST_RATES['commission'])
        stamp_duty = math.ceil(amount * self.HK_COST_RATES['stamp_duty'])
        trading_fee = amount * self.HK_COST_RATES['trading_fee']
        clearing_fee = amount * self.HK_COST_RATES['clearing_fee']
        return commission + stamp_duty + trading_fee + clearing_fee

# Step 2.2: 添加参数优化功能
class ParameterOptimizer:
    """策略参数优化器"""
    
    def __init__(self, base_config: Dict):
        self.base_config = base_config
    
    def grid_search(self, param_grid: Dict, backtest_func: Callable) -> pd.DataFrame:
        """网格搜索最优参数"""
        from itertools import product
        
        results = []
        param_combinations = list(product(*param_grid.values()))
        
        for combo in param_combinations:
            config = self.base_config.copy()
            for i, key in enumerate(param_grid.keys()):
                config[key] = combo[i]
            
            result = backtest_func(config)
            results.append({**config, **result})
        
        return pd.DataFrame(results).sort_values('total_return_pct', ascending=False)
```

### 4.3 第三阶段：报告与可视化（1-2 天）

```python
# Step 3.1: 增强报告生成
class EnhancedBacktestReporter(BacktestReporter):
    """增强的回测报告生成器"""
    
    def generate_detailed_report(self, results: Dict) -> str:
        """生成详细回测报告"""
        report = []
        report.append("# 港股缠论回测详细报告\n")
        
        # 1. 核心指标
        report.append("## 📊 核心绩效指标\n")
        report.append(f"- 总回报率：**{results['total_return_pct']*100:.2f}%**")
        report.append(f"- 年化回报率：**{self.calculate_annualized_return(results):.2f}%**")
        report.append(f"- 夏普比率：**{self.calculate_sharpe_ratio(results):.2f}**")
        report.append(f"- 最大回撤：**{results['max_drawdown_pct']*100:.2f}%**")
        report.append(f"- 胜率：**{self.calculate_win_rate(results):.2f}%**")
        
        # 2. 交易明细
        report.append("\n## 📝 交易明细\n")
        report.append(self.generate_trade_table())
        
        # 3. 股票表现
        report.append("\n## 📈 个股表现\n")
        report.append(self.generate_stock_performance_table())
        
        return "\n".join(report)
    
    def export_to_json(self, results: Dict, filename: str):
        """导出 JSON 格式结果"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    
    def export_to_csv(self, trades: List[Dict], filename: str):
        """导出 CSV 格式交易明细"""
        import csv
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
```

### 4.4 第四阶段：测试验证（1 天）

```bash
# Step 4.1: 运行基础回测测试
python3 backtester.py --backtest

# Step 4.2: 验证回测结果
python3 -c "
import json
with open('backtest_results.json') as f:
    results = json.load(f)

print('回测验证:')
print(f'  总回报率：{results[\"total_return_pct\"]*100:.2f}%')
print(f'  交易次数：{results[\"trades_count\"]}')
print(f'  最大回撤：{results[\"max_drawdown_pct\"]*100:.2f}%')
"

# Step 4.3: 对比实盘表现（如有）
# 比较回测结果与实际交易记录的差异
```

---

## 5. 配置参数说明

### 5.1 回测核心参数

```yaml
# backtest_config.yaml

# 基础配置
backtest:
  initial_funds: 100000      # 初始资金 (港元)
  start_date: "2024-01-01"   # 回测开始日期
  end_date: "2025-12-31"     # 回测结束日期
  main_freq: "30M"           # 主操作周期
  watchlist: "港股"          # 自选股组名

# 交易配置
trading:
  max_position_ratio: 0.2    # 单票最大仓位比例
  min_visual_score: 60       # 最小视觉评分阈值
  max_signal_age_hours: 4    # 信号最大有效期 (小时)

# 缠论配置
chan:
  bi_strict: true            # 严格笔
  one_bi_zs: false           # 一笔中枢
  seg_algo: "chan"           # 线段算法
  bs_type: "1,1p,2,2s,3a,3b" # 买卖点类型
  macd:
    fast: 12
    slow: 26
    signal: 9

# 成本配置
cost:
  commission_rate: 0.0003    # 佣金费率
  commission_min: 3.0        # 最低佣金
  stamp_duty: 0.001          # 印花税
  trading_fee: 0.0000565     # 交易费
```

### 5.2 参数优化范围

```yaml
# param_grid.yaml

# 缠论参数优化范围
param_grid:
  macd_fast: [8, 12, 16]
  macd_slow: [20, 26, 32]
  macd_signal: [6, 9, 12]
  min_zs_cnt: [0, 1, 2]
  divergence_rate: [0.5, 1.0, 2.0]
  
# 交易参数优化范围
trading_param_grid:
  max_position_ratio: [0.1, 0.2, 0.3]
  min_visual_score: [50, 60, 70, 80]
  max_signal_age_hours: [2, 4, 6, 8]
```

---

## 6. 使用示例

### 6.1 快速开始

```bash
# 1. 准备数据（首次运行）
python3 -m scripts.download_hk_data --watchlist "港股" --start 2024-01-01 --end 2025-12-31

# 2. 运行基础回测
python3 backtester.py --backtest

# 3. 查看结果
cat backtest_report_*.md
```

### 6.2 高级回测

```bash
# 使用自定义配置运行回测
python3 -c "
from enhanced_backtester import EnhancedBacktestEngine

engine = EnhancedBacktestEngine(
    initial_funds=200000,
    start_date='2024-01-01',
    end_date='2025-06-30',
    watchlist=['HK.00700', 'HK.00836', 'HK.02688'],
    config_file='backtest_config.yaml'
)

results = engine.run()
engine.generate_report(results)
"

# 参数优化
python3 -c "
from enhanced_backtester import ParameterOptimizer

optimizer = ParameterOptimizer(base_config={...})
results = optimizer.grid_search(
    param_grid={
        'macd_fast': [8, 12, 16],
        'macd_slow': [20, 26, 32],
    },
    backtest_func=run_backtest
)

print(results.head(10))  # 显示前 10 个最优结果
"
```

### 6.3 结果分析

```python
# 分析回测结果
import pandas as pd
import matplotlib.pyplot as plt

# 加载结果
with open('backtest_results.json') as f:
    results = json.load(f)

# 绘制资金曲线
equity_curve = pd.DataFrame(results['equity_curve'])
plt.figure(figsize=(12, 6))
plt.plot(equity_curve['time'], equity_curve['value'])
plt.title('资金曲线')
plt.xlabel('时间')
plt.ylabel('资产净值 (HKD)')
plt.grid(True)
plt.savefig('equity_curve.png')

# 绘制回撤曲线
drawdown = (equity_curve['value'] - equity_curve['value'].cummax()) / equity_curve['value'].cummax()
plt.figure(figsize=(12, 4))
plt.fill_between(drawdown['time'], drawdown['value'], 0, alpha=0.5, color='red')
plt.title('回撤分析')
plt.xlabel('时间')
plt.ylabel('回撤 (%)')
plt.grid(True)
plt.savefig('drawdown.png')
```

---

## 附录

### A. 文件结构

```
Chanlun_Bot/
├── backtester.py                 # 主回测引擎
├── BacktestDataLoader.py         # 数据加载器
├── enhanced_backtester.py        # 增强回测引擎 (新增)
├── backtest_config.yaml          # 回测配置文件 (新增)
├── param_grid.yaml               # 参数优化配置 (新增)
├── stock_cache/                  # 历史数据缓存
│   ├── HK.00700_K_30M.parquet
│   ├── HK.00700_K_5M.parquet
│   └── ...
├── backtest_reports/             # 回测报告输出 (新增)
│   ├── report_20240101_20251231.md
│   ├── backtest_results.json
│   └── trade_log.csv
└── scripts/
    ├── download_hk_data.py       # 数据下载脚本 (新增)
    └── analyze_results.py        # 结果分析脚本 (新增)
```

### B. 关键指标计算公式

| 指标 | 公式 |
|------|------|
| 总回报率 | (期末资产 - 期初资产) / 期初资产 |
| 年化回报率 | (1 + 总回报率)^(252/交易天数) - 1 |
| 夏普比率 | (年化回报率 - 无风险利率) / 收益率标准差 |
| 最大回撤 | max((峰值 - 谷值) / 峰值) |
| 胜率 | 盈利交易次数 / 总交易次数 |
| 盈亏比 | 平均盈利 / 平均亏损 |

### C. 港股交易成本明细

| 费用类型 | 费率 | 备注 |
|----------|------|------|
| 佣金 | 0.03% | 最低 3 港元 |
| 印花税 | 0.1% | 向上取整，买卖双边收取 |
| 交易费 | 0.00565% | 买卖双边收取 |
| 中央结算费 | 0.002% | 买卖双边收取 |
| 平台费 |  varies | 券商收取，因券商而异 |

---

## 总结

本回测方案基于现有代码架构，提供了从数据准备、策略执行到报告生成的完整流程。通过实施本方案，可以实现：

1. **数据完整性**: 自动下载和管理历史 K 线数据
2. **成本精确性**: 精确计算港股交易各项费用
3. **策略可优化**: 支持参数遍历和网格搜索
4. **报告丰富性**: 生成详细的 Markdown/JSON/CSV 报告
5. **结果可验证**: 提供可视化和统计分析工具

建议按阶段实施，先完成基础数据准备和回测验证，再逐步添加高级功能。
