"""
Gemini 视觉评分模块 - 使用 Google Generative AI SDK
"""
import os
import json
import random
from PIL import Image

# 尝试导入 google.generativeai
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    print("⚠️ google.generativeai 未安装，将使用 Mock 模式")

# 从环境变量获取 Google API 密钥
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
USE_MOCK_IF_NO_API = True

MASTER_PROMPT = """System / Role Definition
You are a Master Quantitative Trader specializing in Chan Theory (缠论). You are analyzing stock charts to validate specific algorithmic signals. You possess strict, objective visual reasoning capabilities regarding "Interval Recursion" (区间套) and "MACD Dynamics" (动力学).

User Instruction Input Context:
I have provided two K-line charts for the same stock at the same time:
1. Image 1 (Left/Top): 30-Minute Level (30F) - Provides Trend Context & Major Resistance/Support.
2. Image 2 (Right/Bottom): 5-Minute Level (5F) - Provides the precise Trigger Structure.

Visual Legend (Crucial):
* Yellow Lines: Bi (Strokes) - Strictly calculated.
* Rectangles: ZhongShu (Pivots/Centers).
* Text Labels: The chart contains SPECIFIC signal codes. You must identify which code represents the current setup.

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

Your Task:
1. Identify: Find the latest signal code (e.g., "b2" or "s3b") marked on the 5F chart.
2. Verify: Check if the visual structure matches the definition of that code.
3. Score: Rate the Quality/Confidence of this signal (0-100).
   * High Score (80-100): Textbook pattern + Strong MACD confirmation + 30F Resonance.
   * Low Score (0-50): False signal, weak structure, or counter-trend risk.

Analysis Logic (Step-by-Step):
* Step 1: 30F Context Check
  * If evaluating a BUY (b)*: Is 30F at a support level or showing bottom divergence?
  * If evaluating a SELL (s)*: Is 30F at a resistance level or showing top divergence?
* Step 2: 5F Structure & MACD Check (The Core)
  * For b1p/b1 (Divergence): Compare the Entering Segment (a) vs Leaving Segment (c). Is MACD Area(c) < Area(a)? (Crucial).
  * For b2/b2s (Structure): Is the pullback shallow? Does it stay above the previous low?
  * For b3a/b3b (Trend): Is the breakout powerful? Is the pullback distinctly away from the Pivot (GG/DD)?
  * (Logic is inverted for Sell signals s1p/s1, s2, s3).
* Step 3: Signal Purity
  * Are the Yellow Lines (Bi) clear? Or is the chart messy (Choppy)?
  * Is the MACD crossing the Zero Axis favorably?

Output Requirement: Return ONLY a valid JSON object. No other text.
{
  "detected_signal": "string (e.g., b2, s1p)",
  "direction": "BUY or SELL",
  "30f_trend_status": "Bullish/Bearish/Consolidation",
  "5f_macd_status": "Deep Divergence/Standard/No Divergence",
  "score": 0,
  "reasoning": "Concise analysis of why this specific b*/s* signal is strong or weak.",
  "key_risk": "string (e.g., MACD leaking, near pressure level)"
}"""


class VisualJudge:
    def __init__(self, use_mock=False):
        self.use_mock = use_mock
        self.model = None
        
        # 初始化 Gemini 模型
        if GENAI_AVAILABLE and GOOGLE_API_KEY and not use_mock:
            try:
                genai.configure(api_key=GOOGLE_API_KEY)
                self.model = genai.GenerativeModel(
                    'gemini-2.5-pro',
                    generation_config={"response_mime_type": "application/json"}
                )
                print("✅ Gemini 模型初始化成功")
            except Exception as e:
                print(f"⚠️ Gemini 模型初始化失败: {e}")
                self.use_mock = True
        else:
            if not GENAI_AVAILABLE:
                print("⚠️ google.generativeai 不可用")
            elif not GOOGLE_API_KEY:
                print("⚠️ GOOGLE_API_KEY 未设置")
            self.use_mock = True

    def call_gemini_api(self, image_paths):
        """调用 Google Gemini API 进行视觉分析"""
        if self.use_mock or not self.model:
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
            
            # 发送请求
            response = self.model.generate_content([MASTER_PROMPT] + images)
            
            # 解析 JSON 响应
            result = json.loads(response.text)
            
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
