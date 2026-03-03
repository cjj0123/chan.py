#!/usr/bin/env python3
"""
测试 Apple Notes 通知功能，特别是图片嵌入
"""

import os
import subprocess
from datetime import datetime

def test_notes_with_image():
    """测试创建带图片的备忘录"""
    now = datetime.now()
    title = "🧪 测试通知 - " + now.strftime('%Y-%m-%d %H:%M:%S')
    text_content = "这是一条测试通知，用于验证图片是否能正确嵌入。\n\n- 图表1: 30分钟K线\n- 图表2: 5分钟K线"
    
    # 创建一个测试图片 (使用系统自带的图片)
    test_image = "/System/Library/CoreServices/DefaultDesktop.heic"
    if not os.path.exists(test_image):
        test_image = "/System/Library/CoreServices/DefaultDesktop.jpg"
    
    # 转义标题和文本
    escaped_title = title.replace('"', '\\"')
    escaped_text = text_content.replace('"', '\\"').replace("\n", "\\n")
    
    try:
        # 1. 创建文本备忘录
        script1 = f'tell application "Notes"\n    make new note with properties {{name:"{escaped_title}", body:"{escaped_text}"}}\nend tell'
        result = subprocess.run(["osascript", "-e", script1], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print(f"✅ 备忘录已创建: {title}")
            
            # 2. 插入测试图片
            if os.path.exists(test_image):
                abs_path = os.path.abspath(test_image)
                script2 = f'tell application "Notes"\n    tell note "{escaped_title}"\n        insert image from file "{abs_path}"\n    end tell\nend tell'
                result2 = subprocess.run(["osascript", "-e", script2], capture_output=True, text=True, timeout=10)
                
                if result2.returncode == 0:
                    print("✅ 图片已成功插入")
                else:
                    print(f"❌ 插入图片失败: {result2.stderr}")
            else:
                print("⚠️ 测试图片不存在，跳过图片插入")
        else:
            print(f"❌ 创建备忘录失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 测试过程中发生异常: {e}")

if __name__ == "__main__":
    test_notes_with_image()