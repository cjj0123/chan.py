"""
Gemini 视觉评分模块 - 使用 Google GenAI SDK (新版)
"""
import os
import json
import random
from PIL import Image

# 尝试导入 google.genai (新版)
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    print("⚠️ google.genai 未安装，将使用 Mock 模式")
    print("   安装命令: pip install google-genai")

# 从环境变量获取 Google API 密钥
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
USE_MOCK_IF_NO_API = True

MASTER_PROMPT = """System / Role Definition
You are a Master Quantitative Trader specializing in Chan Theory (缠论). You are analyzing stock charts to validate specific algorithmic signals. You possess strict, objective visual reasoning capabilities regarding "Interval Recursion" (区间套) and "MACD Dynamics" (动力学).

User Instruction Input Context:
I have provided two K-line charts for the same stock at the same time:
1. Image 1 (Left/Top): 30-Minute Level (30M) - PRIMARY SIGNAL SOURCE. This is where you identify the main buy/sell signal.
2. Image 2 (Right/Bottom): 5-Minute Level (5M) - CONFIRMATION & REFERENCE. Use this to validate the 30M signal with finer granularity.

Visual Legend (Crucial):
* Yellow Lines: Bi (Strokes/笔) - Strictly calculated trend segments.
* Red Lines: Seg (Segments/线段) - Higher-level trend segments composed of multiple Bi.
* Blue Rectangles: ZhongShu (Pivots/Centers/中枢) - Consolidation zones.
* Purple Text/Arrows: BUY signals (b1, b2, b3a, b3b, etc.)
* Orange Text/Arrows: SELL signals (s1, s2, s3a, s3b, etc.)
* Dashed Yellow Line: The latest/incomplete Bi stroke.
* Dashed Red Line: The latest/incomplete Seg stroke.

Signal Code Definitions (Lookup Table):
* Divergence Phase (Bottom/Top):
  * b1p / s1p: Potential 1st Buy/Sell (Divergence Point). Focus: Extreme Price + MACD Area Shrinking.
  * b1 / s1: 1st Buy/Sell Confirmed. Focus: Bottom/Top FenXing (Fractal) formed after divergence.
* Trend Relay Phase (Correction/Pullback):
  * b2 / s2: 2nd Buy/Sell. Focus: Higher Low (Buy) or Lower High (Sell).
  * b2s / s2s: 2nd Buy/Sell Sub-level Confirmation. Focus: A smaller structure confirming the b2/s2.
* Trend Follow Phase (Breakout/Extension):
  * b3a / s3a: 3rd Buy/Sell Alert. Focus: Strong Breakout/Breakdown from Pivot.
  * b3b / s3b: 3rd Buy/Sell Confirmed. Focus: Pullback does not touch Pivot High (Buy) / Rebound does not touch Pivot Low (Sell).

CRITICAL INSTRUCTION:
First, carefully examine the 30M chart. Look for any BUY/SELL signal markers (purple text for buy, orange text for sell).

Your Task:
1. Check (on 30M Chart): 
   - If NO signal markers are present on the 30M chart → Return detected_signal: "NONE", score: 0, action: "WAIT"
   - If signal markers ARE present → Identify the latest signal code (e.g., "b2" or "s3b")
   
2. Verify (using 5M Chart - ONLY if 30M has signal): 
   - Check if the 5M chart shows confirming structure (interval recursion) for the 30M signal.
   
3. Score: Rate the Quality/Confidence of this signal (0-100).
   * High Score (80-100): Textbook 30M pattern + Strong 5M confirmation + MACD alignment.
   * Low Score (0-50): Weak 30M structure, no 5M confirmation, or counter-trend risk.
   * Score 0: NO signal present on 30M chart

Analysis Logic (Step-by-Step):
* Step 1: 30M Primary Signal Analysis
  * Identify the latest marked signal (b1/b2/b3a/b3b or s1/s2/s3a/s3b) on the 30M chart.
  * Evaluate the Bi (Yellow Line) structure: Is it clear and well-formed?
  * Evaluate the Seg (Red Line) structure: Does the higher-level trend support the signal?
  * Check ZhongShu (Blue Rectangle) context: Is the signal at a key support/resistance level?
  * Examine MACD on 30M: Is there divergence? Is momentum favorable?

* Step 2: 5M Confirmation Analysis (Interval Recursion)
  * Locate the corresponding time period on the 5M chart.
  * Does the 5M show finer-grained confirmation of the 30M signal?
  * Evaluate both Bi and Seg structures on 5M: Do they align with 30M analysis?
  * For BUY signals: Does 5M show a completed bottom structure or bullish breakout?
  * For SELL signals: Does 5M show a completed top structure or bearish breakdown?
  * Check 5M MACD: Does it confirm the direction (bullish crossover for buy, bearish for sell)?

* Step 3: Overall Signal Quality Assessment
  * Multi-level Alignment: Do Bi, Seg, and ZhongShu all support the same direction?
  * Strength: Is the breakout/breakdown decisive across multiple levels?
  * Risk: Are there nearby pivot levels or conflicting Seg directions that could act as obstacles?

Output Requirement: Return ONLY a valid JSON object. No other text.
{
  "detected_signal": "string (e.g., b2, s1p) - THE SIGNAL FROM 30M CHART",
  "direction": "BUY or SELL",
  "30f_trend_status": "Bullish/Bearish/Consolidation",
  "30f_macd_status": "Deep Divergence/Standard/No Divergence/Momentum Building",
  "5f_confirmation": "Strong/Moderate/Weak/None - How well 5M confirms 30M",
  "score": 0,
  "reasoning": "Explain: 1) What 30M signal was detected, 2) How 5M confirmed it, 3) Why the score was given.",
  "key_risk": "string (e.g., 5M lacks confirmation, near strong resistance, MACD weakening)"
}"""


class VisualJudge:
    def __init__(self, use_mock=False):
        self.use_mock = use_mock
        self.client = None
        
        # 初始化 Gemini 客户端
        if GENAI_AVAILABLE and GOOGLE_API_KEY and not use_mock:
            try:
                self.client = genai.Client(api_key=GOOGLE_API_KEY)
                print("✅ Gemini 客户端初始化成功 (google.genai)")
            except Exception as e:
                print(f"⚠️ Gemini 客户端初始化失败: {e}")
                self.use_mock = True
        else:
            if not GENAI_AVAILABLE:
                print("⚠️ google.genai 不可用")
            elif not GOOGLE_API_KEY:
                print("⚠️ GOOGLE_API_KEY 未设置")
            self.use_mock = True

    def call_gemini_api(self, image_paths):
        """调用 Google Gemini API 进行视觉分析 (使用新版 SDK)"""
        if self.use_mock or not self.client:
            return None
        
        try:
            # 加载图片
            images = []
            for img_path in image_paths:
                if os.path.exists(img_path):
                    img = Image.open(img_path)
                    images.append(img)
                    print(f"   📷 加载图片: {os.path.basename(img_path)}")
                else:
                    print(f"⚠️ 图片不存在: {img_path}")
                    return None
            
            if len(images) < 2:
                print("⚠️ 需要至少2张图片（30M和5M）")
                return None
            
            print("   🤖 调用 Gemini-2.5-pro 分析中...")
            
            # 构建内容
            contents = [MASTER_PROMPT, images[0], images[1]]
            
            # 发送请求 (新版 SDK 语法)
            response = self.client.models.generate_content(
                model="gemini-2.5-pro",
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                    response_mime_type="application/json"
                )
            )
            
            # 解析 JSON 响应
            import re
            response_text = response.text.strip()
            
            # 移除 Markdown 代码块标记（如果存在）
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            elif response_text.startswith('```'):
                response_text = response_text[3:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            # 尝试提取 JSON 部分
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                response_text = json_match.group(0)
            
            result = json.loads(response_text)
            
            # 打印详细结果
            print(f"   📊 Gemini 原始返回:")
            print(f"      - detected_signal: {result.get('detected_signal')}")
            print(f"      - direction: {result.get('direction')}")
            print(f"      - 30f_trend_status: {result.get('30f_trend_status')}")
            print(f"      - 5f_macd_status: {result.get('5f_macd_status')}")
            print(f"      - score: {result.get('score')}")
            print(f"      - reasoning: {result.get('reasoning', '')[:60]}...")
            print(f"      - key_risk: {result.get('key_risk')}")
            
            # 转换分数为 0-100 制
            original_score = result.get('score', 50)
            result['original_score'] = original_score
            
            # 根据 direction 确定 action
            direction = result.get('direction', '').upper()
            if direction == 'BUY' and original_score >= 70:
                result['action'] = 'BUY'
            elif direction == 'SELL' and original_score <= 30:
                result['action'] = 'SELL'
            else:
                result['action'] = 'WAIT'
            
            result['signal_quality'] = '高' if original_score >= 80 else ('中' if original_score >= 50 else '低')
            result['analysis'] = result.get('reasoning', '')[:100]
            
            print(f"   ✅ Gemini 评分: {original_score}/100 | {result['action']} | {result['detected_signal']}")
            return result
            
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON 解析失败: {e}")
            return None
        except Exception as e:
            print(f"⚠️ API 调用异常: {e}")
            return None

    def evaluate(self, image_paths):
        """调用大模型进行视觉评分，如果使用模拟模式，则基于趋势清晰度和中枢复杂度进行评估"""
        print(f"👁️ [VisualJudge] 正在视觉分析：{[os.path.basename(p) for p in image_paths]}")
        
        # 尝试调用真实 API
        if not self.use_mock:
            result = self.call_gemini_api(image_paths)
            if result:
                return result
            else:
                print("⚠️ API 调用失败，降级到 Mock 模式")
                self.use_mock = True
        
        # Mock 模式
        print("   🎲 使用 Mock 评分模式")
        
        trend_clarity = random.uniform(0, 1)
        pivot_complexity = random.uniform(0, 1)
        base_score = trend_clarity * 60 + (1 - pivot_complexity) * 40
        volatility = random.uniform(-15, 15)
        score = max(0, min(100, base_score + volatility))
        
        if score >= 75:
            signal_quality = "高"
            action = "BUY"
        elif score >= 50:
            signal_quality = "中"
            action = "WAIT"
        else:
            signal_quality = "低"
            action = "WAIT"
        
        result = {
            "detected_signal": "mock",
            "direction": "BUY" if score >= 60 else "SELL",
            "30f_trend_status": "Bullish" if trend_clarity > 0.5 else "Bearish",
            "5f_macd_status": "Standard",
            "score": int(score),
            "original_score": int(score),
            "reasoning": f"Mock评分: 趋势清晰度({trend_clarity:.2f}), 中枢复杂度({pivot_complexity:.2f})",
            "key_risk": "Mock模式 - 无真实风险分析",
            "signal_quality": signal_quality,
            "analysis": f"趋势清晰度({trend_clarity:.2f})与中枢复杂度({pivot_complexity:.2f})综合评估",
            "action": action
        }
        
        print(f"   ✅ Mock 评分: {result['score']}/100 | {result['action']}")
        return result
