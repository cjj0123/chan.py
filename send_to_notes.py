#!/usr/bin/env python3
"""
将图表发送到 Apple Notes
"""
import subprocess
from datetime import datetime

def send_to_apple_notes():
    """使用 AppleScript 将图片插入备忘录"""
    
    chart_30m = "/Users/jijunchen/.openclaw/workspace/chan.py/charts/HK_00100_20260226_182558_30M.png"
    chart_5m = "/Users/jijunchen/.openclaw/workspace/chan.py/charts/HK_00100_20260226_182558_5M.png"
    
    # 获取当前时间
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # AppleScript - 创建带图片的笔记
    applescript = f'''
tell application "Notes"
    activate
    
    -- 创建新笔记
    set noteTitle to "HK.00100 图表分析 - {now}"
    set noteBody to "股票: HK.00100 (长和)
生成时间: 2026-02-26 18:25:58
信号类型: s1 (1类卖点)
视觉评分: 90/100 (高质量)
趋势状态: Bearish (看跌)
MACD状态: Deep Divergence (深度背驰)
5M确认度: Strong (强烈确认)

---
30分钟图:"
    
    set newNote to make new note with properties {{name:noteTitle, body:noteBody}}
    
    -- 尝试插入图片（通过剪贴板方式）
    tell application "Finder"
        set image30m to POSIX file "{chart_30m}" as alias
    end tell
    
    -- 设置笔记内容（包含图片路径信息）
    set body of newNote to noteBody & "
[30M图表: {chart_30m}]

5分钟图:
[5M图表: {chart_5m}]

---
分析摘要:
• Gemini检测到清晰的s1卖点信号
• 30M图显示顶部背驰结构
• 5M图提供强烈的区间套确认
• 风险: 当前处于反弹/盘整阶段"
    
    return "笔记已创建: " & noteTitle
end tell
'''
    
    try:
        result = subprocess.run(
            ['osascript', '-e', applescript],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            print(f"✅ {result.stdout.strip()}")
            print(f"\n📊 包含以下图片信息:")
            print(f"   • 30分钟图: {chart_30m}")
            print(f"   • 5分钟图: {chart_5m}")
        else:
            print(f"❌ AppleScript 错误: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        # 备用方案：使用 memo CLI 创建文本笔记
        create_text_note()

def create_text_note():
    """备用方案：使用 memo CLI 创建文本笔记"""
    print("\n📝 使用备用方案 (memo CLI)...")
    
    note_content = f"""HK.00100 (长和) 缠论图表分析

生成时间: 2026-02-26 18:25:58

【Gemini视觉评分结果】
• 识别信号: s1 (1类卖点)
• 方向: SELL
• 视觉评分: 90/100 (高质量)
• 趋势状态: Bearish (看跌)
• MACD状态: Deep Divergence (深度背驰)
• 5M确认度: Strong (强烈确认)

【图表文件位置】
• 30分钟图: /Users/jijunchen/.openclaw/workspace/chan.py/charts/HK_00100_20260226_182558_30M.png
• 5分钟图: /Users/jijunchen/.openclaw/workspace/chan.py/charts/HK_00100_20260226_182558_5M.png

【风险提示】
30M s1信号后的初始急剧下跌已经发生，当前价格走势是在较低水平的反弹/盘整。
风险在于这种盘整可能在下一轮下跌之前进一步延长。
"""
    
    try:
        result = subprocess.run(
            ['memo', 'notes', '-a', 'HK.00100 图表分析'],
            input=note_content,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            print("✅ 文本笔记已创建到 Apple Notes")
        else:
            print(f"⚠️ memo CLI 错误: {result.stderr}")
            
    except FileNotFoundError:
        print("❌ memo CLI 未安装")
        print("   安装命令: brew tap antoniorodr/memo && brew install antoniorodr/memo/memo")
    except Exception as e:
        print(f"❌ 备用方案也失败: {e}")

if __name__ == "__main__":
    send_to_apple_notes()
