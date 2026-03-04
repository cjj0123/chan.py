# Gemini 2.5 模型测试报告

**测试时间:** 2026-02-26 10:37  
**测试模型:** `gemini-2.5-flash`  
**测试状态:** ❌ API Key 无效

---

## ❌ 测试结果

**错误信息:**
```
400 API key not valid. Please pass a valid API key.
[reason: "API_KEY_INVALID"
service: "generativelanguage.googleapis.com"]
```

**当前 API Key 状态:**
- **长度:** 21 字符
- **前缀:** `__OPENCLAW...`
- **格式:** ❌ 不正确

**正确的 Google API Key 格式:**
- **长度:** 约 40 字符
- **前缀:** `AIzaSy`
- **示例:** `AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXX`

---

## ⚠️ 问题原因

当前的 `GOOGLE_API_KEY` 环境变量设置的是一个占位符或内部 Key，不是有效的 Google API Key。

---

## ✅ 解决方案

### 1. 获取真正的 Google API Key

**访问:** https://aistudio.google.com/app/apikey

**步骤:**
1. 使用 Google 账号登录
2. 点击 **"Create API Key"**
3. 选择或创建项目
4. 复制完整的 API Key（约 40 字符，以 `AIzaSy` 开头）

### 2. 设置正确的环境变量

```bash
# 替换为你的真实 API Key
export GOOGLE_API_KEY="AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXX"

# 验证
echo $GOOGLE_API_KEY
# 应该显示类似：AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXX
```

### 3. 测试 API Key

```bash
python3 << 'EOF'
import os
import google.generativeai as genai

api_key = os.getenv('GOOGLE_API_KEY')
print(f"API Key 长度：{len(api_key)}")
print(f"API Key 前缀：{api_key[:10]}...")

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')
response = model.generate_content('你好')
print("✅ API Key 有效！")
print(f"响应：{response.text}")
EOF
```

---

## 📊 当前系统状态

| 功能 | 状态 | 说明 |
| :--- | :--- | :--- |
| **代码集成** | ✅ | Gemini API 集成完成 |
| **模型配置** | ✅ | gemini-2.5-flash |
| **降级机制** | ✅ | 自动降级到本地算法 |
| **本地评分** | ✅ | 正常工作 |
| **API Key** | ❌ | 格式不正确 |

---

## 🔄 降级方案

由于 API Key 无效，系统已自动降级到本地算法：

```
⚠️  API 不可用，使用本地算法评分：HK.XXXX - 0.XX
```

**本地算法功能:**
- ✅ 趋势评分 (20%)
- ✅ 背驰评分 (30%)
- ✅ 形态评分 (30%)
- ✅ 自动降级

**测试结果:**
- 扫描股票：36 只
- 买点信号：正常工作
- 评分范围：0.50 - 1.00
- 系统运行：✅ 正常

---

## 📝 下一步

### 选项 1: 使用真实 API Key（推荐）

获取有效的 Google API Key 后：
```bash
export GOOGLE_API_KEY="AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXX"
python3 chan.py/futu_sim_trading_enhanced.py --single
```

### 选项 2: 继续使用本地算法

当前本地算法工作正常，可以继续使用：
- 免费
- 快速
- 稳定
- 无需 API Key

---

## 📚 相关文档

1. **`VISUAL_SCORE_API_INTEGRATION.md`** - API 集成详解
2. **`GOOGLE_API_KEY_SETUP.md`** - API Key 设置指南
3. **`FINAL_VISUAL_SCORE_TEST_REPORT.md`** - 测试报告

---

**更新时间:** 2026-02-26 10:37  
**状态:** ⚠️ 需要有效的 Google API Key（`AIzaSy` 开头，约 40 字符）
