#!/usr/bin/env python3
"""
自动加载 API Key 配置
在程序启动时自动调用
"""

import os
import sys

def load_api_keys():
    """从 memory/api_keys.md 加载 API Key"""
    api_keys_file = os.path.join(os.path.dirname(__file__), '..', 'memory', 'api_keys.md')
    
    if not os.path.exists(api_keys_file):
        # 尝试其他路径
        api_keys_file = '/Users/jijunchen/.openclaw/workspace/memory/api_keys.md'
    
    if os.path.exists(api_keys_file):
        try:
            with open(api_keys_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 提取 Google API Key
            if 'API Key:' in content:
                for line in content.split('\n'):
                    if 'API Key:' in line and 'Google' not in line:
                        # 提取 key 值
                        key = line.split('`')[1].strip()
                        if key.startswith('AIza'):
                            os.environ['GOOGLE_API_KEY'] = key
                            print(f"✅ 已加载 Google API Key: {key[:20]}...")
                            return True
            
            print("⚠️ 未找到有效的 API Key")
            return False
            
        except Exception as e:
            print(f"⚠️ 加载 API Key 失败：{e}")
            return False
    else:
        print(f"⚠️ API Keys 文件不存在：{api_keys_file}")
        return False

# 自动加载
if __name__ == "__main__":
    load_api_keys()
