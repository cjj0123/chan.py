# A 股缠论扫描程序逻辑说明

**文件：** `cn_stock_visual_trading.py`

**功能：** 扫描 A 股缠论信号，发送备忘录通知（含图表），**不执行交易**

---

## 📋 完整流程图

```
┌─────────────────────────────────────────────────────────────┐
│  1. 程序启动                                                 │
│     - 加载 API Key（memory/api_keys.md）                     │
│     - 初始化日志                                             │
│     - 连接 Futu OpenD                                        │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  2. 初始化 CNStockVisualTrading 类                           │
│     - cn_watchlist_group = "沪深"                           │
│     - min_visual_score = 70                                 │
│     - dry_run = True（只扫描不交易）                         │
│     - 配置 CChan 参数                                        │
│     - 初始化 VisualJudge（Gemini API）                       │
│     - 创建 charts_cn/ 目录                                   │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  3. scan_and_trade() 主流程                                 │
│     - 获取自选股列表（实时从 Futu 获取）                       │
│     - 遍历每只股票                                           │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  4. 对每只股票执行：                                         │
│     a) 获取股票信息（价格、名称）                            │
│     b) 缠论分析（CChan）                                    │
│     c) 4 小时时间过滤                                        │
│     d) 生成图表（30M + 5M）                                  │
│     e) Gemini 视觉评分                                      │
│     f) 收集≥70 分的信号                                      │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  5. 信号处理                                                │
│     - 分离买卖信号                                           │
│     - 按评分排序                                             │
│     - 统计数量                                               │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  6. 发送备忘录通知（如果有信号）                             │
│     - 创建 Apple Notes 备忘录                                │
│     - 写入股票名称、信号类型、评分、Gemini 分析               │
│     - 插入图表图片（30M + 5M）                               │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  7. 发送邮件报告（可选）                                     │
│     - HTML 格式                                              │
│     - 内嵌图表图片                                           │
│     - 包含详细分析                                           │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  8. 完成扫描                                                │
│     - 记录日志                                               │
│     - 关闭 Futu 连接                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 核心函数详解

### 1. `__init__(self, cn_watchlist_group="沪深", min_visual_score=70)`

**功能：** 初始化交易系统

**关键配置：**
```python
self.dry_run = True  # 只扫描不交易
self.chan_config = CChanConfig({
    "bi_strict": True,
    "seg_algo": "chan",
    "trigger_step": False,
})
self.visual_judge = VisualJudge()  # Gemini API
```

---

### 2. `get_cn_watchlist_codes()`

**功能：** 实时获取 A 股自选股列表

**流程：**
```python
1. 重新创建 Futu 连接（确保可用）
2. 调用 get_user_security("沪深")
3. 过滤 SH. 和 SZ. 开头的股票
4. 返回股票代码列表
```

**输出：** `['SH.600641', 'SZ.301589', ...]`（43 只）

---

### 3. `get_stock_info(code)`

**功能：** 获取股票详细信息

**返回：**
```python
{
    'current_price': 13.27,
    'stock_name': '国电南瑞',
    'market_val': 1000000,
    'lot_size': 100
}
```

---

### 4. `analyze_with_chan(code)`

**功能：** 缠论分析

**流程：**
```python
1. 获取 30 分钟 K 线数据（30 天）
2. CChan 分析
3. 获取最新买卖点
4. 时间过滤（4 小时窗口）
5. 返回信号信息
```

**返回：**
```python
{
    'code': 'SH.600886',
    'bsp_type': 's1',  # 1 类卖点
    'is_buy_signal': False,
    'bsp_price': 13.27,
    'chan_analysis': {...}
}
```

---

### 5. `calculate_trading_hours(start_time, end_time)`

**功能：** 计算交易小时数（排除非交易时段）

**A 股交易时间：**
- 上午：09:30 - 11:30
- 下午：13:00 - 15:00

**逻辑：**
```python
if 信号时间 > 4 小时前:
    return True  # 在窗口内
else:
    return False  # 跳过
```

---

### 6. `generate_charts(code, chan_30m)`

**功能：** 生成 30M + 5M 图表

**流程：**
```python
1. 生成 30 分钟图（缠论标注）
   - K 线、笔、线段、中枢、MACD
2. 生成 5 分钟图（辅助分析）
   - K 线、笔、中枢、MACD
3. 保存到 charts_cn/ 目录
4. 返回文件路径列表
```

**输出：**
```python
[
    'charts_cn/SH_600886_20260227_144945_30M.png',
    'charts_cn/SH_600886_20260227_144945_5M.png'
]
```

---

### 7. `visual_judge.evaluate(chart_paths)`

**功能：** Gemini 视觉评分

**流程：**
```python
1. 加载 30M 和 5M 图片
2. 调用 Gemini 2.5-pro API
3. 传入缠论分析 Prompt
4. 获取 JSON 响应
5. 解析评分和分析
```

**返回：**
```python
{
    'score': 82,
    'action': 'BUY',
    'analysis': '趋势清晰，买点明确...',
    'key_risk': '注意上方阻力位...'
}
```

---

### 8. `scan_and_trade()`

**功能：** 主扫描流程

**伪代码：**
```python
def scan_and_trade():
    # 1. 获取自选股
    watchlist = get_cn_watchlist_codes()
    
    # 2. 遍历扫描
    for code in watchlist:
        # a) 获取信息
        stock_info = get_stock_info(code)
        
        # b) 缠论分析
        chan_result = analyze_with_chan(code)
        if not chan_result:
            continue
        
        # c) 时间过滤
        if not in_4h_window(chan_result.time):
            continue
        
        # d) 生成图表
        chart_paths = generate_charts(code)
        
        # e) 视觉评分
        visual_result = visual_judge.evaluate(chart_paths)
        
        # f) 收集信号
        if visual_result.score >= 70:
            all_signals.append({
                'code': code,
                'stock_name': stock_info['name'],
                'is_buy': chan_result.is_buy,
                'bsp_type': chan_result.bsp_type,
                'score': visual_result.score,
                'chart_paths': chart_paths,
                'visual_result': visual_result
            })
    
    # 3. 分离买卖信号
    buy_signals = [s for s in all_signals if s['is_buy']]
    sell_signals = [s for s in all_signals if not s['is_buy']]
    
    # 4. 发送通知
    if all_signals:
        send_scan_result_to_notes({
            'valid_signals': len(all_signals),
            'buy_signals': buy_signals,
            'sell_signals': sell_signals
        })
        
        # 可选：发送邮件
        send_email_report(all_signals, chart_paths)
```

---

### 9. `send_scan_result_to_notes(scan_summary)`

**功能：** 发送 Apple Notes 备忘录

**内容：**
```
🎯 A 股缠论视觉交易信号
═══════════════════════════════

⏰ 扫描时间：2026-02-27 15:01:00
✅ 有效信号：4 个

【买入信号】1 个
─────────────────────────────
1. SH.600886 国电南瑞
   信号类型：b1
   视觉评分：82/100
   分析：趋势清晰，买点明确...

【卖出信号】3 个
─────────────────────────────
1. SH.600995 国网信通
   信号类型：s1
   视觉评分：75/100
   分析：...

📊 图表：8 张图片已插入
```

**流程：**
```python
1. 创建备忘录（AppleScript）
2. 写入文本内容
3. 插入图表图片（30M + 5M）
4. 记录日志
```

---

## ⚙️ 配置参数

### 类初始化参数
```python
cn_watchlist_group = "沪深"       # 自选股组名
min_visual_score = 70             # 视觉评分阈值
```

### CChan 配置
```python
{
    "bi_strict": True,            # 严格笔
    "seg_algo": "chan",           # 缠论线段算法
    "trigger_step": False,        # 不逐步触发
}
```

### 时间过滤
```python
4 小时窗口 = 4 个交易小时
```

### 评分阈值
```python
score >= 70  → 收集信号
score >= 80  → 高质量信号
```

---

## 📊 数据流

```
Futu OpenD
    │
    ├─→ get_cn_watchlist_codes() → 43 只股票
    │
    ├─→ get_stock_info() → 价格、名称
    │
    └─→ CChan → 买卖点信号
           │
           ├─→ 4 小时过滤 → 15 只股票
           │
           ├─→ generate_charts() → 30 张图片
           │
           └─→ Gemini API → 评分
                  │
                  └─→ score >= 70 → 4 个信号
                         │
                         ├─→ Apple Notes → 备忘录
                         │
                         └─→ Email → HTML 报告
```

---

## 🎯 关键特性

| 特性 | 实现方式 |
| :--- | :--- |
| **实时获取** | 每次扫描重新连接 Futu |
| **4 小时过滤** | calculate_trading_hours() |
| **Gemini 评分** | VisualJudge.evaluate() |
| **图表生成** | CPlotDriver (30M + 5M) |
| **股票名称** | get_stock_info() |
| **通知方式** | Apple Notes + Email |
| **不交易** | dry_run = True |

---

## 🔍 日志示例

```
2026-02-27 14:49:13,616 - INFO - Futu 行情连接已建立
2026-02-27 14:49:13,618 - INFO - A 股扫描初始化完成 - 评分阈值：70
2026-02-27 14:49:13,618 - INFO - ======================================================================
2026-02-27 14:49:13,618 - INFO - 🔍 A 股缠论信号扫描开始...
2026-02-27 14:49:15,337 - INFO - 获取到 43 只 A 股
2026-02-27 14:49:15,338 - INFO - 分析股票：SH.600641
...
2026-02-27 14:49:47,016 - INFO - SH.600886 视觉评分：82/100, 建议：BUY
2026-02-27 14:49:47,016 - INFO - ✅ SH.600886 信号收集成功 (评分：82)
2026-02-27 14:49:47,016 - INFO - 共收集到 4 个有效信号
2026-02-27 14:49:47,178 - INFO - ✅ 备忘录已创建：🎯 A 股交易信号 - 2026-02-27 14:49
2026-02-27 14:49:48,180 - INFO - 📊 已插入 8 张图表
2026-02-27 14:49:48,180 - INFO - ✅ A 股扫描完成
```

---

## 🚀 下次扫描（15:01）

**将自动执行：**
1. ✅ 加载 API Key
2. ✅ 获取 43 只 A 股
3. ✅ 缠论分析
4. ✅ Gemini 评分
5. ✅ 发送通知

**预期结果：**
- 稳定的 Gemini 评分（不再随机）
- 包含股票名称
- 包含 Gemini 分析细节
- 插入图表图片

---

**A 股扫描程序逻辑说明完成！** 📋
