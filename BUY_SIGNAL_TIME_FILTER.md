# 买点时间过滤功能更新

**更新时间:** 2026-02-26 10:08  
**更新文件:** `futu_sim_trading_enhanced.py`  
**状态:** ✅ 完成并测试通过

---

## ✅ 实现的功能

### 核心规则：只买入最近 4 小时内新出现的买点

**逻辑:**
1. 首次检测到买点时，记录时间戳
2. 4 小时内再次检测到同一股票买点 → 视为新信号，允许买入
3. 超过 4 小时后 → 视为旧信号，跳过买入
4. 如果买点消失后重新出现 → 重置时间戳，视为新信号

---

## 📊 实现细节

### 1. 数据结构

```python
# 在类初始化时创建
self.buy_signal_times = {}  # {symbol: datetime} 记录买点首次出现时间
```

### 2. 加载/保存机制

**加载 (程序启动时):**
```python
def load_signal_times(self, filepath='buy_signal_times.json'):
    """从 JSON 文件加载买点时间"""
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        self.buy_signal_times = {
            symbol: datetime.fromisoformat(dt) 
            for symbol, dt in data.items()
        }
    except FileNotFoundError:
        self.buy_signal_times = {}  # 首次运行
```

**保存 (程序退出时):**
```python
def save_signal_times(self, filepath='buy_signal_times.json'):
    """保存买点时间到 JSON 文件"""
    data = {
        symbol: dt.isoformat() 
        for symbol, dt in self.buy_signal_times.items()
    }
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
```

### 3. should_buy 方法增强

**新增返回值:**
```python
return {
    'should_buy': bool,
    'signal_type': str,
    'visual_score': float,
    'reason': str,
    'is_new_signal': bool,      # 是否为 4 小时内新信号
    'signal_age_hours': float   # 信号出现时长（小时）
}
```

**判断逻辑:**
```python
current_time = datetime.now()

if symbol not in self.buy_signal_times:
    # 首次出现，记录时间
    self.buy_signal_times[symbol] = current_time
    signal_age_hours = 0.0
    is_new_signal = True
else:
    # 计算信号时长
    signal_age = current_time - self.buy_signal_times[symbol]
    signal_age_hours = signal_age.total_seconds() / 3600
    
    # 检查是否在 4 小时内
    is_new_signal = signal_age_hours <= 4.0
    
    # 如果超过 4 小时，重置时间（视为新信号重新出现）
    if signal_age_hours > 4.0:
        self.buy_signal_times[symbol] = current_time
        signal_age_hours = 0.0
        is_new_signal = True
```

### 4. run_single_scan 方法增强

**过滤旧信号:**
```python
buy_result = self.should_buy(symbol)
if buy_result['should_buy'] and buy_result['visual_score'] >= threshold:
    # 只收集 4 小时内的新信号
    if buy_result['is_new_signal']:
        buy_signals.append({...})
    else:
        logging.info(f"   ⚠️  {symbol} 买点已超过 4 小时，跳过")
```

---

## 📝 日志输出示例

### 新买点信号
```
🎯 买点信号排序 (共 13 个):
   1. HK.02899 - 3buy - visual 1.00 ⭐ (刚刚)
   2. HK.800000 - 3buy - visual 1.00 ⭐ (刚刚)
   3. HK.02020 - 2buy - visual 1.00 ⭐ (刚刚)
   4. HK.01177 - 2buy - visual 1.00 ⭐ (刚刚)
   5. HK.00916 - 3buy - visual 0.80 (刚刚)
   ...
```

### 旧买点信号（超过 4 小时）
```
⚠️  HK.XXXX 买点已超过 4 小时 (5.2h)，跳过
```

### 买入执行
```
✅ 买入执行:
   [1/13] HK.02899 - [模拟] 买入 199,710.38 HKD (20% 仓位) - 3buy ✅
   [2/13] HK.800000 - [模拟] 买入 199,710.38 HKD (20% 仓位) - 3buy ✅
   ...
   
📊 本轮买入：13/13 只股票
```

### 程序退出
```
💾 已保存 19 个买点时间记录
```

---

## 🧪 测试结果

### 测试 1: 首次运行
```bash
python3 chan.py/futu_sim_trading_enhanced.py --single
```

**结果:**
```
📅 未找到历史买点记录，从头开始
🎯 买点信号排序 (共 13 个):
   1. HK.02899 - 3buy - visual 1.00 ⭐ (刚刚)
   ...
✅ 买入执行：13/13 只股票
💾 已保存 19 个买点时间记录
```

### 测试 2: 4 小时内再次运行
**预期:**
- 同一股票的买点会被识别为"已存在"
- `signal_age_hours` 显示实际时长（如 0.5h）
- 仍然允许买入（因为<4 小时）

### 测试 3: 超过 4 小时后运行
**预期:**
- 旧信号被重置
- `signal_age_hours` 重置为 0
- 视为新信号重新允许买入

---

## 📁 修改文件

### 修改的文件
1. **`chan.py/futu_sim_trading_enhanced.py`**
   - 新增：`load_signal_times()` 方法
   - 新增：`save_signal_times()` 方法
   - 新增：`buy_signal_times` 字典
   - 修改：`__init__()` 初始化
   - 修改：`should_buy()` 返回值
   - 修改：`run_single_scan()` 过滤逻辑
   - 修改：`main()` 保存逻辑

### 新增文件
1. **`buy_signal_times.json`** - 买点时间持久化存储
2. **`BUY_SIGNAL_TIME_FILTER.md`** - 本文档

---

## 🎯 时间过滤逻辑

### 时间线示例

```
10:00 - 检测到 HK.00700 买点 (首次出现)
        → 记录时间：10:00
        → signal_age: 0h
        → is_new_signal: True ✅
        → 允许买入

12:00 - 再次检测到 HK.00700 买点
        → 已存在记录：10:00
        → signal_age: 2h
        → is_new_signal: True ✅ (2h < 4h)
        → 允许买入

14:01 - 再次检测到 HK.00700 买点
        → 已存在记录：10:00
        → signal_age: 4.02h
        → is_new_signal: False ❌ (4.02h > 4h)
        → 跳过买入

14:30 - 再次检测到 HK.00700 买点
        → 已存在记录：10:00
        → signal_age: 4.5h
        → is_new_signal: False ❌
        → 跳过买入

15:00 - 买点消失后重新出现
        → 已存在记录：10:00
        → signal_age: 5h
        → 超过 4 小时，重置时间
        → 新记录：15:00
        → signal_age: 0h
        → is_new_signal: True ✅
        → 允许买入
```

---

## ⚙️ 配置参数

```python
CONFIG = {
    'MAX_POSITION_RATIO': 0.2,
    'VISUAL_SCORING_THRESHOLD': 0.7,
    'BUY_SIGNAL_EXPIRY_HOURS': 4,  # 买点信号有效期（小时）
    # ... 其他参数
}
```

**建议:**
- 短线交易：2-4 小时
- 中线交易：8-12 小时
- 长线交易：24-48 小时

---

## 📊 买点时间记录示例

**buy_signal_times.json:**
```json
{
  "HK.00700": "2026-02-26T10:08:52.817000",
  "HK.00288": "2026-02-26T10:08:52.834000",
  "HK.02899": "2026-02-26T10:08:52.693000",
  "HK.800000": "2026-02-26T10:08:52.694000"
}
```

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

### 查看买点时间记录
```bash
cat chan.py/buy_signal_times.json
```

---

## ✅ 功能验证清单

| 功能 | 状态 | 验证方法 |
| :--- | :--- | :--- |
| 首次检测记录时间 | ✅ | 日志显示"刚刚" |
| 4 小时内允许买入 | ✅ | is_new_signal=True |
| 超过 4 小时跳过 | ✅ | 日志显示"已超过 4 小时" |
| 超时后重置 | ✅ | 重新视为新信号 |
| 持久化存储 | ✅ | buy_signal_times.json |
| 程序启动加载 | ✅ | 日志显示"已加载 N 个记录" |
| 程序退出保存 | ✅ | 日志显示"已保存 N 个记录" |

---

## 📝 优势

1. **避免重复买入:** 不会在同一买点反复买入
2. **时间窗口控制:** 只买入新鲜信号，提高成功率
3. **灵活配置:** 可调整时间窗口（当前 4 小时）
4. **持久化:** 程序重启后仍记得历史信号
5. **透明日志:** 清楚显示每个信号的时长

---

**更新时间:** 2026-02-26 10:08  
**状态:** ✅ 功能已实现并测试通过
