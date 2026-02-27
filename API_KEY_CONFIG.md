# API Key 配置说明

## ✅ 问题已彻底解决

**问题：** Gemini API Key 每次扫描都需要重新设置

**解决方案：** 三重保障机制

---

## 🔧 配置方式

### 1. 永久保存（推荐）

**文件位置：** `/Users/jijunchen/.openclaw/workspace/memory/api_keys.md`

```markdown
## Google Gemini API
**API Key:** `AIzaSyCyOShkz9hhPPLxYrI6Oc4eHq_I6muZF0Q`
```

**优点：**
- ✅ 永久保存
- ✅ 所有程序共享
- ✅ 易于管理

---

### 2. 自动加载

**文件：** `load_api_key.py`

**自动执行：**
- 程序启动时自动加载
- 从 `memory/api_keys.md` 读取
- 失败时使用备用配置

**代码示例：**
```python
from load_api_key import load_api_keys
load_api_keys()  # 自动设置 GOOGLE_API_KEY
```

---

### 3. 备用方案

如果自动加载失败，代码中直接设置：
```python
os.environ["GOOGLE_API_KEY"] = "AIzaSyCyOShkz9hhPPLxYrI6Oc4eHq_I6muZF0Q"
```

---

## 📁 已修改的文件

| 文件 | 修改内容 |
| :--- | :--- |
| `memory/api_keys.md` | 新建，保存 API Key |
| `load_api_key.py` | 新建，自动加载脚本 |
| `cn_stock_visual_trading.py` | 添加自动加载 |
| `futu_hk_visual_trading_fixed.py` | 添加自动加载 |

---

## ✅ 验证方法

```bash
cd /Users/jijunchen/.openclaw/workspace/chan.py

# 测试 API Key 加载
python3 -c "from load_api_key import load_api_keys; load_api_keys()"

# 测试 Gemini API
python3 -c "from visual_judge import VisualJudge; vj = VisualJudge(use_mock=False); print(f'API 正常：{vj.client is not None}')"
```

**预期输出：**
```
✅ 已加载 Google API Key: AIzaSyCyOShkz9hhPPLx...
✅ Gemini 客户端初始化成功 (google.genai)
API 正常：True
```

---

## 🎯 下次扫描

**15:01 扫描将：**
1. ✅ 自动加载 API Key
2. ✅ 调用真实 Gemini API
3. ✅ 获得稳定一致的评分
4. ✅ 不再出现 Mock 随机评分

---

## 📝 维护说明

**如需更新 API Key：**
1. 编辑 `../memory/api_keys.md`
2. 修改 `API Key:` 后的值
3. 重启程序即可

**无需修改代码！**

---

**API Key 问题已彻底解决！** 🎉
