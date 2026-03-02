#!/usr/bin/env python3
"""
测试 Gemini API 连接性
"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'email_config.env'))

# 检查 API 密钥
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("❌ GOOGLE_API_KEY 未设置")
    exit(1)

print(f"✅ GOOGLE_API_KEY 已加载：{api_key[:10]}...")

# 尝试导入并测试 Gemini
try:
    import google.generativeai as genai
    print("✅ google-genai 库已安装")
    
    # 配置 API 密钥
    genai.configure(api_key=api_key)
    
    # 创建模型
    model = genai.GenerativeModel('gemini-2.5-pro')
    print("✅ 模型 gemini-2.5-pro 初始化成功")
    
    # 测试 API 调用
    print("🔄 正在测试 Gemini API 连接...")
    response = model.generate_content("Hello, this is a test message to check API connectivity.")
    
    print("✅ Gemini API 连接测试成功!")
    print(f"📝 响应内容：{response.text[:100]}...")
    
except ImportError as e:
    print(f"❌ google-genai 库未安装：{e}")
    print("   安装命令：pip install google-genai")
except Exception as e:
    print(f"❌ Gemini API 调用异常：{e}")
    import traceback
    print(f"详细错误信息：{traceback.format_exc()}")