#!/usr/bin/env python3
"""
测试Qwen API连接性
"""
import os
from dotenv import load_dotenv
import dashscope
from dashscope import MultiModalConversation

# 只加载一次环境变量，优先级：系统环境变量 > .env文件 > email_config.env文件
# 避免重复加载导致覆盖
if not os.getenv("DASHSCOPE_API_KEY"):
    load_dotenv()  # 加载 .env 文件（如果存在）
if not os.getenv("DASHSCOPE_API_KEY"):
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'email_config.env'))  # 加载配置文件

# 设置API密钥
api_key = os.getenv("DASHSCOPE_API_KEY")
if not api_key:
    print("❌ DASHSCOPE_API_KEY 未设置")
    exit(1)

print(f"✅ DASHSCOPE_API_KEY 已加载: {api_key[:10]}...")

dashscope.api_key = api_key

# 测试API调用
try:
    # 创建一个简单的测试消息
    messages = [
        {
            'role': 'user',
            'content': [
                {'text': 'Hello, this is a test message to check API connectivity.'}
            ]
        }
    ]

    print("🔄 正在测试Qwen API连接...")
    response = MultiModalConversation.call(
        model='qwen3.5-plus',
        messages=messages,
        temperature=0.1,
    )

    if response and response.status_code == 200:
        print("✅ Qwen API 连接测试成功!")
        content = response.output.choices[0].message.content
        print(f"📝 响应内容: {content}")
    else:
        print(f"❌ Qwen API 连接测试失败: {response.code if response else 'No response'} - {response.message if response else 'N/A'}")
        if hasattr(response, 'request_id'):
            print(f"   请求ID: {response.request_id}")

except Exception as e:
    print(f"❌ Qwen API 调用异常: {e}")
    import traceback
    print(f"详细错误信息: {traceback.format_exc()}")