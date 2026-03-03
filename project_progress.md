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

### 1. Apple Notes 图片插入 (AppleScript 方法)

**问题**: 在较新版本的 macOS 中，使用 AppleScript 的 `insert image from file` 命令无法将图片嵌入到 Apple Notes 备忘录中，会报语法错误。

**解决方案**: 改用 `make new attachment at end with data` 命令。

**错误示例**:
```applescript
-- 这个命令在新系统中会失败
tell application "Notes"
    tell note "My Note"
        insert image from file "/path/to/image.png"
    end tell
end tell
```

**正确示例**:
```applescript
-- 使用 attachment 方式
tell application "Notes"
    tell note "My Note"
        make new attachment at end with data "/path/to/image.png"
    end tell
end tell
```

**在 Python 中的调用方式**:
```python
import subprocess

title = "My Note"
image_path = "/path/to/image.png"
script = f'tell application "Notes" to tell note "{title}" to make new attachment at end with data "{image_path}"'
subprocess.run(["osascript", "-e", script])
```

**关键要点**:
- **不要使用** `insert image from file`。
- **必须使用** `make new attachment at end with data`。
- 确保文件路径是绝对路径。
- 此方法已在 macOS Sequoia (15.x) 上验证有效。

### 2. Apple Notes 图片插入 (appscript 方法)

**替代方案**: 如果不想使用 `osascript`，也可以使用 Python 的 `appscript` 库。

```python
from appscript import app, mactypes, k

# 连接到 Notes 应用
notes = app('Notes')
folder = notes.folders["量化交易报告"]
note = folder.notes["Note Title"]

# 添加图片附件
image_path = "/path/to/chart.png"
note.make(new=k.attachment, at=note.end, with_data=mactypes.File(image_path))
```

**关键要点**:
- 需要安装 `appscript`: `pip install appscript`
- 使用 `mactypes.File()` 包装文件路径

**参考文档**: [appscript 官方文档](https://appscript.sourceforge.io/)