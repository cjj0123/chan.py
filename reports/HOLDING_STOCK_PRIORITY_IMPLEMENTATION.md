# 港股程序持仓股票优先处理功能实现说明

## 修改概述

本次修改实现了港股程序优先查询已持仓股票的信号和执行功能，确保对已持仓股票的及时监控和响应。

## 具体修改内容

### 1. 信号收集阶段 (`_collect_candidate_signals` 方法)

#### 修改前：
- 按自选股顺序处理所有股票
- 没有区分持仓股票和非持仓股票的处理优先级

#### 修改后：
- 首先分离持仓股票和非持仓股票
- 优先处理持仓股票（高优先级）
- 然后处理非持仓股票（低优先级）
- 对持仓股票和非持仓股票分别进行分批处理，确保持仓股票得到及时处理

#### 关键代码变更：
```python
# 获取持仓股票列表
position_stocks = []
non_position_stocks = []

for code in watchlist_codes:
    position_qty = self.get_position_quantity(code)
    if position_qty > 0:
        position_stocks.append((code, position_qty))
    else:
        non_position_stocks.append(code)

logger.info(f"持仓股票: {len(position_stocks)} 只, 非持仓股票: {len(non_position_stocks)} 只")

# 优先处理持仓股票
all_codes_to_process = []
for code, qty in position_stocks:
    all_codes_to_process.append(code)
all_codes_to_process.extend(non_position_stocks)
```

### 2. 交易执行阶段 (`_execute_trades` 方法)

#### 修改前：
- 按评分排序后统一处理所有卖出信号
- 没有区分持仓相关和非持仓相关的信号处理优先级

#### 修改后：
- 优先处理持仓股票的卖出信号
- 确保对持仓股票的及时响应
- 买入信号仍然按评分排序处理

#### 关键代码变更：
```python
# 获取持仓股票列表
position_stocks = set()
for signal in all_signals:
    if signal['position_qty'] > 0:
        position_stocks.add(signal['code'])

# 重新排序卖出信号：持仓股票优先
sell_signals_position = [s for s in sell_signals if s['code'] in position_stocks]
sell_signals_non_position = [s for s in sell_signals if s['code'] not in position_stocks]
sell_signals = sell_signals_position + sell_signals_non_position
```

## 功能优势

1. **及时响应**：持仓股票的信号会被优先处理，确保及时响应持仓股票的变化
2. **风险控制**：对于持仓股票的卖出信号能更快执行，有助于风险控制
3. **资源优化**：优先处理重要的持仓股票，合理分配系统资源
4. **保持原有逻辑**：在优先处理持仓股票的同时，保持了原有的评分和过滤逻辑

## 测试验证

通过 `test_position_priority.py` 脚本验证了以下逻辑：

1. ✅ 信号收集时优先处理持仓股票
2. ✅ 交易执行时优先处理持仓相关的卖出信号
3. ✅ 正确过滤持仓股票的买入信号（避免重复买入）
4. ✅ 维持原有的评分和资金管理逻辑

## 影响范围

- 文件：`futu_hk_visual_trading_fixed.py`
- 方法：`_collect_candidate_signals`, `_execute_trades`
- 不影响其他模块，仅优化港股扫描和交易的优先级处理逻辑

## 部署说明

此修改无需额外配置，直接替换原文件即可生效。系统将继续按照原有方式运行，但会优先处理持仓股票的相关信号。