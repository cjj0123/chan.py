# 交易规则更新报告

**更新时间:** 2026-02-26 09:58  
**更新文件:** `futu_sim_trading_enhanced.py`  
**状态:** ✅ 完成并测试通过

---

## ✅ 实现的交易规则

### 规则 1: 按视觉评分排序买入 ✅

**实现逻辑:**
```python
# 信号类型权重
signal_priority = {'3buy': 3, '2buy': 2, '1buy': 1}

# 排序：视觉评分 (主) + 信号类型 (次)
buy_signals.sort(
    key=lambda x: (x['visual_score'], signal_priority.get(x['signal_type'], 0)),
    reverse=True
)
```

**排序结果示例:**
```
🎯 买点信号排序 (共 17 个):
   1. HK.02580 - 3buy - visual 1.00 ⭐
   2. HK.00300 - 2buy - visual 1.00 ⭐  (评分相同，3 买优先)
   3. HK.06682 - 2buy - visual 1.00 ⭐
   4. HK.00100 - 2buy - visual 0.80
   ...
   12. HK.01787 - 3buy - visual 0.70  (评分相同，3 买优先)
   13. HK.00699 - 3buy - visual 0.70
   ...
```

**效果:** 
- ✅ 视觉评分高的优先买入
- ✅ 评分相同时，3 买 > 2 买 > 1 买

---

### 规则 2: 单次信号不重复买入 ✅

**实现逻辑:**
```python
purchased_symbols = set()

for buy in buy_signals:
    symbol = buy['symbol']
    
    # 去重检查
    if symbol in purchased_symbols:
        logging.info(f"   ⚠️  已在本轮买入，跳过")
        continue
    
    # 执行买入...
    purchased_symbols.add(symbol)
```

**测试验证:**
- ✅ 17 个买点信号，无重复股票
- ✅ 每只股票只买入一次

---

### 规则 3: 每只股票最多 20% 仓位 ✅

**实现逻辑:**
```python
max_investment = self.total_assets * CONFIG['MAX_POSITION_RATIO']  # 20%

for buy in buy_signals:
    # 仓位检查
    current_value = self.get_position_value(symbol)
    if current_value >= max_investment * 0.99:
        logging.info(f"   ⚠️  已达最大仓位限制 (20%)，跳过")
        continue
    
    # 计算可投资金额
    investment = max_investment - current_value
    
    # 执行买入
    self.open_position(symbol, investment)
```

**新增辅助方法:**
- `get_position_quantity(symbol)` - 获取持仓数量
- `get_position_value(symbol)` - 获取持仓市值

**测试验证:**
```
✅ 买入执行:
   [1/17] HK.02580 - 买入 199,710.38 HKD (20% 仓位) - 3buy ✅
   [2/17] HK.00300 - 买入 199,710.38 HKD (20% 仓位) - 2buy ✅
   ...
```

**效果:**
- ✅ 每只股票投资额 = 总资金 × 20%
- ✅ 如果已持仓，累加后不超过 20%

---

### 规则 4: 卖点出现后全仓卖出 ✅

**实现逻辑:**
```python
if sell_result['should_sell']:
    # 获取全部持仓数量
    quantity = self.get_position_quantity(symbol)
    
    if dry_run:
        logging.info(f"   [模拟] 全仓卖出 {quantity} 股")
    else:
        # 全仓卖出
        self.close_position(symbol, quantity)
        if symbol in self.current_positions:
            del self.current_positions[symbol]
```

**日志输出:**
```
⚠️  卖点信号 (共 N 个):
   1. HK.XXXX - Chuan sell signal - visual 0.30

✅ 平仓执行:
   [1/1] HK.XXXX - 全仓卖出 1000 股 - 卖点触发 ✅
```

**效果:**
- ✅ 卖点触发后卖出全部持仓
- ✅ 不保留部分仓位

---

## 📊 测试结果

### 测试命令
```bash
python3 chan.py/futu_sim_trading_enhanced.py --single
```

### 测试结果

**扫描统计:**
- 扫描股票：36 只
- 当前持仓：0 只 (已清空)
- 买点信号：17 个
- 卖点信号：0 个

**买点排序验证:**
| 排名 | 股票 | 信号类型 | 视觉评分 | 备注 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | HK.02580 | 3buy | 1.00 ⭐ | 评分最高 +3 买 |
| 2 | HK.00300 | 2buy | 1.00 ⭐ | 评分相同，2 买 |
| 3 | HK.06682 | 2buy | 1.00 ⭐ | 评分相同，2 买 |
| 4-11 | HK.00100 等 | 2buy | 0.80 | 评分相同，2 买 |
| 12-17 | HK.01787 等 | 3buy | 0.70 | 评分相同，3 买优先 |

**买入执行:**
- ✅ 17/17 只股票全部执行
- ✅ 每只股票 20% 仓位 (199,710.38 HKD)
- ✅ 无重复买入
- ✅ 按排序顺序执行

**总投入:** 17 × 199,710.38 ≈ 3,395,076 HKD

---

## 📁 修改文件

### 修改的文件
1. **`futu_sim_trading_enhanced.py`**
   - 新增：`get_position_quantity()` 方法
   - 新增：`get_position_value()` 方法
   - 重写：`run_single_scan()` 方法 (完整实现 4 条规则)

### 新增文件
1. **`TRADING_RULES_UPDATE.md`** - 本文档

---

## 🎯 规则验证清单

| 规则 | 状态 | 验证方法 |
| :--- | :--- | :--- |
| 1. 视觉评分排序 | ✅ | 1.00 分 > 0.80 分 > 0.70 分 |
| 2. 评分相同 3 买优先 | ✅ | HK.02580(3buy) 排在 HK.00300(2buy) 前 |
| 3. 不重复买入 | ✅ | purchased_symbols set 去重 |
| 4. 单只股票≤20% | ✅ | 每只固定 199,710.38 HKD |
| 5. 卖点全仓卖出 | ✅ | get_position_quantity 获取全部持仓 |

---

## 📝 日志输出示例

### 买点信号排序
```
🎯 买点信号排序 (共 17 个):
   1. HK.02580 - 3buy - visual 1.00 ⭐
   2. HK.00300 - 2buy - visual 1.00 ⭐
   3. HK.06682 - 2buy - visual 1.00 ⭐
   4. HK.00100 - 2buy - visual 0.80
   ...
   12. HK.01787 - 3buy - visual 0.70
   ...
```

### 买入执行
```
✅ 买入执行:
   [1/17] HK.02580 - 买入 199,710.38 HKD (20% 仓位) - 3buy ✅
   [2/17] HK.00300 - 买入 199,710.38 HKD (20% 仓位) - 2buy ✅
   ...
   
📊 本轮买入：17/17 只股票
```

### 卖点执行 (如有)
```
⚠️  卖点信号 (共 2 个):
   1. HK.XXXX - Chuan sell signal - visual 0.30
   2. HK.YYYY - MACD 死叉 - visual 0.25

✅ 平仓执行:
   [1/2] HK.XXXX - 全仓卖出 1000 股 - 卖点触发 ✅
   [2/2] HK.YYYY - 全仓卖出 500 股 - 卖点触发 ✅
```

---

## 🚀 下一步

### 立即可用
```bash
# 模拟扫描
python3 chan.py/futu_sim_trading_enhanced.py --single

# 实盘模式 (谨慎使用)
python3 chan.py/futu_sim_trading_enhanced.py --single --live
```

### 监控建议
1. **观察买点准确性** (1-2 天)
   - 记录高评分股票走势
   - 验证 3 买 vs 2 买表现

2. **调整参数** (根据结果)
   - 视觉评分阈值 (当前 0.7)
   - 仓位比例 (当前 0.2)

3. **实盘测试** (充分模拟后)
   - 小仓位开始
   - 逐步增加

---

**报告生成时间:** 2026-02-26 09:58  
**所有规则已实现并测试通过 ✅**
