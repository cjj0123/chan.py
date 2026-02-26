# 缠论视觉增强交易系统 - 项目进度

## 核心状态
- **系统状态**: Production Ready
- **定时任务**: 已配置并激活 (`crontab_visual_trading.txt`)
- **执行脚本**: `futu_sim_trading_enhanced.py --single`

## 关键配置
- **视觉评分模型**: Gemini 2.5 Pro
- **买入阈值**: `VISUAL_SCORING_THRESHOLD = 0.7` (70分)
- **快速通道阈值**: `INSTANT_BUY_THRESHOLD = 0.9` (90分)
- **仓位控制**: 单票最大 20% 总资金

## 执行逻辑
1.  **信号扫描**: 每30分钟扫描一次缠论买卖点。
2.  **视觉评分**: 对买点信号调用 Gemini API 进行专业评分 (0-10分)。
3.  **决策执行**:
    -   评分 < 0.7: 忽略信号。
    -   评分 >= 0.9: **立即执行**买入（快速通道）。
    -   0.7 <= 评分 < 0.9: 排序后依次执行买入（普通通道）。
4.  **卖点处理**: 触发缠论卖点信号时，**全仓卖出**。

## 最后更新
- **日期**: 2026-02-27
- **操作**: 添加避坑指南 - Apple Notes 图片插入方法

---

## 避坑指南

### 1. Apple Notes 图片插入 (appscript 方法)

**问题**: 使用 `memo` CLI 或 AppleScript 无法将图片正确插入到备忘录中。

**解决方案**: 使用 Python 的 `appscript` 库直接操作 Apple Notes。

```python
from appscript import app, mactypes, k

# 连接到 Notes 应用
notes = app('Notes')

# 获取或创建文件夹
folder_name = "量化交易报告"
try:
    folder = notes.folders[folder_name]
except:
    notes.make(new=k.folder, with_properties={k.name: folder_name})
    folder = notes.folders[folder_name]

# 获取目标笔记
note_title = "缠论图表测试 - HK.00700 - 2026-02-27"
note = folder.notes[note_title]

# 添加图片附件
image_path = "/path/to/chart.png"
note.make(new=k.attachment, at=note.end, with_data=mactypes.File(image_path))
```

**关键要点**:
- 使用 `mactypes.File()` 包装文件路径
- 使用 `k.attachment` 指定附件类型
- 使用 `at=note.end` 将附件添加到笔记末尾
- 需要安装 `appscript`: `pip install appscript`

**参考文档**: [appscript 官方文档](https://appscript.sourceforge.io/)