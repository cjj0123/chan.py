# 任务：创建并运行环境测试脚本

## 需求
在 `/Users/jijunchen/.openclaw/workspace/` 目录下创建一个名为 `test_connection.py` 的文件，内容如下：

```python
import datetime
print(f"Current time: {datetime.datetime.now()}")
```

然后运行该脚本确认 Python 环境正常。

## 执行步骤
1. 进入工作目录：`cd /Users/jijunchen/.openclaw/workspace/`
2. 创建文件 `test_connection.py` 并写入上述代码
3. 运行脚本：`python3 test_connection.py`
4. 确认输出当前时间

## 期望结果
脚本成功运行，输出格式为：`Current time: 2026-02-28 HH:MM:SS.ffffff`

---
任务时间：2026-02-28 19:06
