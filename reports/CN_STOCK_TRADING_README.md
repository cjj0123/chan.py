# A 股缠论视觉交易系统 - 使用说明

## 📋 功能概述

**A 股缠论信号扫描程序** - 基于港股程序逻辑，专为 A 股市场设计

**核心功能：**
- ✅ 缠论买卖点识别（1 买、2 买、3 买、1 卖、2 卖、3 卖）
- ✅ Gemini 视觉评分（≥70 分触发通知）
- ✅ 4 小时时间窗口过滤（只通知新信号）
- ✅ Apple Notes 备忘录通知（含图表图片）
- ❌ **不执行交易**（仅扫描通知）

---

## 📁 文件说明

| 文件 | 说明 |
| :--- | :--- |
| `cn_stock_visual_trading.py` | A 股主程序 |
| `crontab_cn_stock_trading.txt` | Crontab 定时任务配置 |
| `run_cn_stock_scan.sh` | 手动启动脚本 |
| `cn_stock_trading.log` | 运行日志 |
| `charts_cn/` | 图表保存目录 |

---

## ⏰ 扫描时间安排

**A 股交易时间：** 周一至周五 09:30-11:30, 13:00-15:00

| 时间 | 任务 | 说明 |
| :--- | :--- | :--- |
| **09:26** | 盘前扫描 | 集合竞价后，开盘前 |
| **09:31** | 盘中扫描 | 开盘后第 1 次 |
| **10:01** | 盘中扫描 | 每 30 分钟 |
| **10:31** | 盘中扫描 | 每 30 分钟 |
| **11:01** | 盘中扫描 | 每 30 分钟 |
| **11:31** | 盘中扫描 | 上午收盘 |
| **13:01** | 盘中扫描 | 下午开盘 |
| **13:31** | 盘中扫描 | 每 30 分钟 |
| **14:01** | 盘中扫描 | 每 30 分钟 |
| **14:31** | 盘中扫描 | 每 30 分钟 |
| **15:01** | 盘中扫描 | 收盘前 |

**共 11 次扫描/交易日**

---

## 🚀 安装步骤

### 1. 安装 macOS launchd 任务（推荐）

```bash
# 加载 launchd 配置
launchctl load ~/Library/LaunchAgents/com.openclaw.cnstock.plist
```

### 2. 验证安装

```bash
# 查看已安装的任务
launchctl list | grep cnstock

# 应该看到：com.openclaw.cnstock
```

### 3. 手动测试

```bash
# 手动执行一次扫描
./run_cn_stock_scan.sh

# 或直接用 Python 执行
python3 cn_stock_visual_trading.py
```

---

## 📊 使用示例

### 手动执行扫描

```bash
cd /Users/jijunchen/.openclaw/workspace/chan.py
python3 cn_stock_visual_trading.py
```

### 查看日志

```bash
# 查看最新日志
tail -f logs/cn_stock_*.log

# 查看今天的日志
cat logs/cn_stock_$(date +%Y%m%d)*.log
```

### 查看图表

```bash
# 打开图表目录
open charts_cn/

# 查看最新图表
ls -lt charts_cn/ | head -10
```

---

## 🔔 备忘录通知

**当发现有效信号时：**

1. 自动创建 Apple Notes 备忘录
2. 标题：`🎯 A 股交易信号 - YYYY-MM-DD HH:MM`
3. 内容：
   - 信号详情（股票代码、类型、评分）
   - 图表图片（30M + 5M K 线图）
   - 扫描时间、信号数量

**无信号时：** 不发送通知，避免打扰

---

## ⚙️ 配置参数

### 修改自选股组

```python
trader = CNStockVisualTrading(
    cn_watchlist_group="A 股",  # 修改为你的自选股组名
    min_visual_score=70         # 视觉评分阈值（0-100）
)
```

### 修改评分阈值

```python
# 在 crontab_cn_stock_trading.txt 中修改启动参数
$PYTHON cn_stock_visual_trading.py --min-score 80  # 提高到 80 分
```

### 修改日志目录

```bash
# 在 crontab_cn_stock_trading.txt 中修改
export LOG_DIR=/your/custom/log/path
```

---

## 📝 日志示例

```
2026-02-27 14:31:05,123 - INFO - ======================================================================
2026-02-27 14:31:05,123 - INFO - 🔍 A 股缠论信号扫描开始...
2026-02-27 14:31:05,123 - INFO - ======================================================================
2026-02-27 14:31:05,456 - INFO - 获取到 50 只 A 股
2026-02-27 14:31:05,456 - INFO - 分析股票：SH.600519
2026-02-27 14:31:06,789 - INFO - SH.600519 1 信号在 4 小时窗口内（0.5 个交易小时前），继续分析
2026-02-27 14:31:06,789 - INFO - SH.600519 缠论分析：1 信号，价格：1850.00
2026-02-27 14:31:06,789 - INFO - SH.600519 信号类型：b1, 是否买入：True
2026-02-27 14:31:08,123 - INFO - 生成图表：['charts_cn/SH_600519_20260227_143106_30M.png', ...]
2026-02-27 14:31:15,456 - INFO - SH.600519 视觉评分：85/100, 建议：BUY
2026-02-27 14:31:15,456 - INFO - ✅ SH.600519 信号收集成功 (评分：85)
2026-02-27 14:31:20,789 - INFO - 共收集到 1 个有效信号
2026-02-27 14:31:20,789 - INFO - 卖出信号：0 个，买入信号：1 个
2026-02-27 14:31:25,123 - INFO - ✅ 备忘录已创建：🎯 A 股交易信号 - 2026-02-27 14:31
2026-02-27 14:31:30,456 - INFO - 📊 已插入 2 张图表
2026-02-27 14:31:30,456 - INFO - ======================================================================
2026-02-27 14:31:30,456 - INFO - ✅ A 股扫描完成
2026-02-27 14:31:30,456 - INFO - ======================================================================
```

---

## ❓ 常见问题

### Q1: 如何暂停定时任务？

```bash
# 卸载 launchd 任务
launchctl unload ~/Library/LaunchAgents/com.openclaw.cnstock.plist

# 重新加载
launchctl load ~/Library/LaunchAgents/com.openclaw.cnstock.plist
```

### Q2: 如何修改扫描频率？

编辑 `~/Library/LaunchAgents/com.openclaw.cnstock.plist`，修改 `StartCalendarInterval` 部分：

```xml
<!-- 改为每小时扫描一次 -->
<dict>
    <key>Hour</key>
    <integer>*</integer>
    <key>Minute</key>
    <integer>1</integer>
</dict>
```

然后重新加载：
```bash
launchctl unload ~/Library/LaunchAgents/com.openclaw.cnstock.plist
launchctl load ~/Library/LaunchAgents/com.openclaw.cnstock.plist
```

### Q3: 图表占用太多空间怎么办？

```bash
# 清理 7 天前的图表
find charts_cn/ -name "*.png" -mtime +7 -delete

# 查看图表目录大小
du -sh charts_cn/
```

### Q4: 如何在节假日暂停任务？

```bash
# 卸载任务
launchctl unload ~/Library/LaunchAgents/com.openclaw.cnstock.plist

# 节后重新加载
launchctl load ~/Library/LaunchAgents/com.openclaw.cnstock.plist
```

### Q5: 如何查看 launchd 任务状态？

```bash
# 查看任务列表
launchctl list | grep cnstock

# 查看日志
tail -f ~/Library/Logs/com.openclaw.cnstock.log
```

---

## 📈 与港股程序的区别

| 功能 | 港股程序 | A 股程序 |
| :--- | :--- | :--- |
| **交易执行** | ✅ 支持（模拟/实盘） | ❌ 仅扫描通知 |
| **数据源** | Futu 港股 | Futu A 股 |
| **扫描时间** | 港股交易时间 | A 股交易时间 |
| **自选股组** | "港股" | "A 股" |
| **日志文件** | `futu_hk_trading.log` | `cn_stock_trading.log` |
| **图表目录** | `charts/` | `charts_cn/` |

---

## 🎯 下一步建议

1. **创建 A 股自选股组** - 在 Futu 中创建名为"A 股"的自选股组
2. **安装 Crontab** - `crontab crontab_cn_stock_trading.txt`
3. **测试运行** - `./run_cn_stock_scan.sh`
4. **监控日志** - 定期检查 `logs/cn_stock_*.log`
5. **调整参数** - 根据实际需求调整评分阈值

---

## 📞 技术支持

- 查看日志：`tail -f logs/cn_stock_*.log`
- 检查程序：`python3 -m py_compile cn_stock_visual_trading.py`
- 查看 Crontab：`crontab -l | grep cn_stock`
