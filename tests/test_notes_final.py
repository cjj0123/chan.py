#!/usr/bin/env python3
"""
最终测试 Apple Notes 通知功能
"""

import os
import subprocess
from datetime import datetime

def test_final():
    """最终测试"""
    now = datetime.now()
    title = "🧪 最终测试 - " + now.strftime('%Y-%m-%d %H:%M:%S')
    text_content = "最终测试通知，验证 attachment 方式插入图片。"
    
    # 使用一个简单的测试图片
    test_image = "/System/Library/CoreServices/DefaultDesktop.heic"
    
    try:
        # 1. 创建备忘录
        script1 = f'tell application "Notes" to make new note with properties {{name:"{title}", body:"{text_content}"}}'
        result1 = subprocess.run(["osascript", "-e", script1], capture_output=True, text=True, timeout=10)
        
        if result1.returncode == 0:
            print(f"✅ 备忘录已创建: {title}")
            
            # 2. 插入图片作为附件
            if os.path.exists(test_image):
                abs_path = os.path.abspath(test_image)
                script2 = f'tell application "Notes" to tell note "{title}" to make new attachment at end with data "{abs_path}"'
                result2 = subprocess.run(["osascript", "-e", script2], capture_output=True, text=True, timeout=10)
                
                if result2.returncode == 0:
                    print("✅ 图片已作为附件成功插入")
                else:
                    print(f"❌ 插入图片失败: {result2.stderr}")
        else:
            print(f"❌ 创建备忘录失败: {result1.stderr}")
            
    except Exception as e:
        print(f"❌ 测试异常: {e}")

if __name__ == "__main__":
    test_final()