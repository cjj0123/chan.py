# GUI 扫描错误修复计划

## 1. 问题分析

经过代码审查，我已定位到 GUI 在进行“离线扫描”时报错的根本原因。

- **错误模块**: 数据接口 `DataAPI/SQLiteAPI.py`
- **触发条件**: 当从本地数据库 `chan_trading.db` 中读取到一条“坏”的K线数据时，程序会崩溃。具体来说，当一条日K线数据同时满足以下条件时会触发错误：
    1.  最低价 `low` <= 0
    2.  开盘价 `open`、最高价 `high` 和收盘价 `close` 也全部都 <= 0
- **根本原因**: 在 `create_item_dict_from_db` 函数中，有一行代码试图在一组非正数的价格中寻找最小值，但由于列表为空，调用 `min()` 函数时引发了 `ValueError`，导致扫描线程中断。

## 2. 修复方案

我将修改 `DataAPI/SQLiteAPI.py` 文件中的 `create_item_dict_from_db` 函数，使其能够更稳健地处理这类异常数据。

**具体修改如下：**

- **文件**: [`DataAPI/SQLiteAPI.py`](DataAPI/SQLiteAPI.py:43)
- **目的**: 在计算最低价时，防止对一个空列表求最小值。

```python
# --- 原始代码 (Line 43) ---
if l <= 0: l = min(p for p in [o, h, c] if p > 0)

# --- 修复后代码 ---
positive_prices = [p for p in [o, h, c] if p > 0]
if l <= 0: l = min(positive_prices) if positive_prices else valid_price
```

这个修改会先检查是否存在任何一个正数价格，如果存在，则取其中的最小值；如果不存在，则使用之前计算的 `valid_price`（我们已知它在这种情况下必然是正数）作为备用值。这能确保代码不会再因为空列表而崩溃。

## 3. 下一步

我将等待您的批准，然后切换到“代码”模式来实施这个修复。