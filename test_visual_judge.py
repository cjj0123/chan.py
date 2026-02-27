#!/usr/bin/env python3
"""
测试新版 visual_judge.py 的效果
"""
import sys
import os
import json
sys.path.insert(0, '/Users/jijunchen/.openclaw/workspace/chan.py')

# 从 OpenClaw 配置文件读取 API Key
config_path = os.path.expanduser('~/.openclaw/openclaw.json')
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        config = json.load(f)
        google_api_key = config.get('models', {}).get('providers', {}).get('google', {}).get('apiKey')
        if google_api_key:
            os.environ['GOOGLE_API_KEY'] = google_api_key
            print(f"✅ 已从 OpenClaw 配置加载 API Key")

from visual_judge import VisualJudge

def test_visual_judge():
    """测试视觉评分模块"""
    print("=" * 60)
    print("🧪 测试新版 VisualJudge")
    print("=" * 60)
    
    # 初始化（不使用 mock）
    judge = VisualJudge(use_mock=False)
    
    # 选择一对测试图表（30M + 5M）
    test_images = [
        "/Users/jijunchen/.openclaw/workspace/chan.py/charts/HK_00100_20260226_182558_30M.png",
        "/Users/jijunchen/.openclaw/workspace/chan.py/charts/HK_00100_20260226_182558_5M.png"
    ]
    
    print(f"\n📊 测试图片:")
    for img in test_images:
        print(f"   - {img.split('/')[-1]}")
    
    print("\n" + "-" * 60)
    print("🤖 调用 Gemini API 分析中...")
    print("-" * 60)
    
    # 执行评估
    result = judge.evaluate(test_images)
    
    print("\n" + "=" * 60)
    print("📋 完整结果:")
    print("=" * 60)
    
    if result:
        for key, value in result.items():
            if isinstance(value, str) and len(value) > 80:
                print(f"   {key}: {value[:80]}...")
            else:
                print(f"   {key}: {value}")
    else:
        print("❌ 评估失败，无结果返回")
    
    return result

if __name__ == "__main__":
    test_visual_judge()
