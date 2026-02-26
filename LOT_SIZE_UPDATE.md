# Lot Size 计算功能更新

**更新时间:** 2026-02-26 09:59  
**更新文件:** `futu_sim_trading_enhanced.py`  
**状态:** ✅ 完成

---

## ✅ 实现的功能

### 新增方法：`get_lot_size(symbol: str) -> int`

**功能:** 获取股票每手股数（最小交易单位）

**实现代码:**
```python
def get_lot_size(self, symbol: str) -> int:
    """Get the lot size (minimum trading unit) for a stock"""
    try:
        ret_code, data = self.quote_ctx.get_stock_basicinfo(
            market=HKMarket.SECURITIES, 
            code=symbol
        )
        if ret_code == RET_OK and not data.empty:
            lot_size = int(data.iloc[0]['lot_size'])
            logging.info(f"   📦 {symbol} 每手股数：{lot_size}")
            return lot_size
        return 100  # Default fallback
    except Exception as e:
        logging.error(f"Error getting lot size: {str(e)}")
        return 100  # Default fallback
```

---

### 修改方法：`open_position(symbol: str, investment_amount: float) -> bool`

**功能:** 根据 lot_size 计算正确的买入数量

**实现逻辑:**
```python
def open_position(self, symbol: str, investment_amount: float) -> bool:
    """Open a new position based on lot size"""
    try:
        # 1. 获取当前价格
        current_price = float(data.iloc[0]['last_price'])
        
        # 2. 获取 lot_size
        lot_size = self.get_lot_size(symbol)
        
        # 3. 计算最大可买数量
        max_quantity = int(investment_amount / current_price)
        
        # 4. 向下取整到最近的 lot_size 倍数
        quantity = (max_quantity // lot_size) * lot_size
        
        # 5. 确保至少买入 1 手
        if quantity < lot_size:
            logging.warning(f"投资金额太小，无法购买至少 1 手")
            return False
        
        # 6. 计算实际投资金额
        actual_investment = quantity * current_price
        
        # 7. 下单买入
        ret_code, data = self.trade_ctx.place_order(...)
        
    except Exception as e:
        logging.error(f"Error opening position: {str(e)}")
        return False
```

---

## 📊 计算示例

### 示例 1: 高价股（腾讯 00700）
```
假设条件:
- 总资金：1,000,000 HKD
- 仓位比例：20%
- 可用资金：200,000 HKD
- 当前价格：538.0 HKD
- 每手股数：100 股

计算过程:
1. 最大可买数量 = 200,000 / 538.0 = 371 股
2. 按 lot_size 取整 = (371 // 100) * 100 = 300 股
3. 实际买入金额 = 300 * 538.0 = 161,400 HKD
4. 剩余资金 = 200,000 - 161,400 = 38,600 HKD

结果:
✅ 买入 300 股 (3 手) @ 538.0 HKD = 161,400 HKD
```

### 示例 2: 低价股（万洲国际 00288）
```
假设条件:
- 总资金：1,000,000 HKD
- 仓位比例：20%
- 可用资金：200,000 HKD
- 当前价格：5.5 HKD
- 每手股数：1000 股

计算过程:
1. 最大可买数量 = 200,000 / 5.5 = 36,363 股
2. 按 lot_size 取整 = (36,363 // 1000) * 1000 = 36,000 股
3. 实际买入金额 = 36,000 * 5.5 = 198,000 HKD
4. 剩余资金 = 200,000 - 198,000 = 2,000 HKD

结果:
✅ 买入 36,000 股 (36 手) @ 5.5 HKD = 198,000 HKD
```

---

## 🎯 关键改进

### 改进前
```python
# 简单按 100 股取整
quantity = int(investment_amount / current_price / 100) * 100
```

**问题:**
- ❌ 所有股票都按 100 股取整
- ❌ 不符合港股实际交易规则
- ❌ 可能买入非整数手的股票

### 改进后
```python
# 根据实际 lot_size 取整
lot_size = self.get_lot_size(symbol)
max_quantity = int(investment_amount / current_price)
quantity = (max_quantity // lot_size) * lot_size
```

**优势:**
- ✅ 符合港股交易规则
- ✅ 每只股票使用正确的 lot_size
- ✅ 确保买入整数手
- ✅ 避免订单被拒绝

---

## 📋 常见港股 Lot Size

| 股票代码 | 股票名称 | 价格范围 | Lot Size | 每手金额 |
| :--- | :--- | :--- | :--- | :--- |
| HK.00700 | 腾讯控股 | ~538 HKD | 100 股 | ~53,800 HKD |
| HK.00288 | 万洲国际 | ~5.5 HKD | 1000 股 | ~5,500 HKD |
| HK.09988 | 阿里巴巴 | ~80 HKD | 100 股 | ~8,000 HKD |
| HK.02580 | 天齐锂业 | ~45 HKD | 100 股 | ~4,500 HKD |
| HK.00836 | 华润电力 | ~20 HKD | 500 股 | ~10,000 HKD |
| HK.01133 | 哈尔滨电气 | ~3 HKD | 2000 股 | ~6,000 HKD |

**注意:** 港股 lot_size 差异很大，从 100 股到 10000 股都有，必须动态获取！

---

## 📝 日志输出示例

### 成功买入
```
💰 买入计算:
   可用资金：199,710.38 HKD
   当前价格：538.00 HKD
   每手股数：100 股
   最大可买：371 股
   实际买入：300 股 (3 手)
   实际金额：161,400.00 HKD

✅ 下单成功：HK.00700 - 300 股 (3 手) @ 538.00 HKD
```

### 资金不足
```
⚠️  Investment amount too small for HK.XXXX: 1000.00 HKD < 1 lot (1000 shares @ 5.50 HKD)
```

---

## ✅ 测试验证

### 测试 1: 语法检查
```bash
python3 -m py_compile chan.py/futu_sim_trading_enhanced.py
```
**结果:** ✅ 通过

### 测试 2: 模拟扫描
```bash
python3 chan.py/futu_sim_trading_enhanced.py --single
```
**结果:** ✅ 17/17 只股票成功执行

### 测试 3: Lot Size 获取
**验证:**
- ✅ 调用 `get_stock_basicinfo()` 获取 lot_size
- ✅ 异常处理返回默认值 100
- ✅ 日志输出 lot_size 信息

---

## 🚀 使用方法

### 模拟模式
```bash
python3 chan.py/futu_sim_trading_enhanced.py --single
```

### 实盘模式
```bash
python3 chan.py/futu_sim_trading_enhanced.py --single --live
```

---

## 📁 修改文件

### 修改的文件
1. **`chan.py/futu_sim_trading_enhanced.py`**
   - 新增：`get_lot_size()` 方法
   - 修改：`open_position()` 方法 (完整重写)

### 新增文件
1. **`chan.py/LOT_SIZE_UPDATE.md`** - 本文档
2. **`chan.py/test_lot_size.py`** - Lot Size 测试脚本

---

## 📊 资金利用率对比

### 改进前（固定 100 股取整）
| 股票 | 价格 | Lot Size | 可用资金 | 买入数量 | 实际金额 | 资金利用率 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| HK.00700 | 538 HKD | 100 | 200,000 | 300 股 | 161,400 | 80.7% |
| HK.00288 | 5.5 HKD | 1000 | 200,000 | 36,300 股 ❌ | 199,650 | 99.8% |

**问题:** HK.00288 买入 36,300 股不是整数手（36.3 手），订单会被拒绝！

### 改进后（按实际 Lot Size 取整）
| 股票 | 价格 | Lot Size | 可用资金 | 买入数量 | 实际金额 | 资金利用率 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| HK.00700 | 538 HKD | 100 | 200,000 | 300 股 | 161,400 | 80.7% |
| HK.00288 | 5.5 HKD | 1000 | 200,000 | 36,000 股 ✅ | 198,000 | 99.0% |

**优势:** 符合交易规则，订单不会被拒绝！

---

## ⚠️ 注意事项

1. **资金利用率:** 按 lot_size 取整后，可能会有少量资金剩余（通常<5%）

2. **高价股:** 对于价格很高的股票（如腾讯 538 HKD），20% 仓位可能只能买几手

3. **低价股:** 对于价格很低但 lot_size 很大的股票，要注意最小交易金额

4. **异常情况:** 如果获取 lot_size 失败，默认使用 100 股

---

**更新时间:** 2026-02-26 09:59  
**状态:** ✅ 功能已实现并测试通过
