#!/usr/bin/env python3
"""
测试 Apple Notes 通知功能 v2 - 修复图片插入问题
"""

import os
import subprocess
from datetime import datetime

def test_notes_with_image_v2():
    """测试创建带图片的备忘录 - 使用更稳健的 AppleScript"""
    now = datetime.now()
    title = "🧪 测试通知 v2 - " + now.strftime('%Y-%m-%d %H:%M:%S')
    text_content = "这是一条测试通知 v2，用于验证图片是否能正确嵌入。\n\n- 图表1: 30分钟K线\n- 图表2: 5分钟K线"
    
    # 创建一个测试图片 (使用系统自带的图片)
    test_image = "/System/Library/CoreServices/DefaultDesktop.heic"
    if not os.path.exists(test_image):
        test_image = "/System/Library/CoreServices/DefaultDesktop.jpg"
    
    try:
        # 使用单个 AppleScript 完成所有操作
        script = f'''
        tell application "Notes"
            set newNote to make new note at folder "量化交易报告" with properties {{name:"{title}", body:"{text_content}"}}
            if "{test_image}" exists then
                tell newNote
                    insert image from file "{test_image}"
                end tell
            end if
        end tell
        '''
        
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0:
            print(f"✅ 备忘录已创建并插入图片: {title}")
        else:
            print(f"❌ 操作失败: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 测试过程中发生异常: {e}")

if __name__ == "__main__":
    test_notes_with_image_v2()