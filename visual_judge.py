"""
视觉评分模块 - 支持 Gemini 和 Qwen 双模型, 具备回退机制
"""
import os
import json
import base64
from PIL import Image
import re

# 尝试导入 google.genai (Gemini)
try:
    import google.generativeai as genai
    from google.generativeai.types import GenerationConfig
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️ google.generativeai 未安装，Gemini 模型不可用。")
    print("   安装命令: pip install google-generativeai")

# 尝试导入 dashscope (Qwen)
try:
    import dashscope
    from dashscope import MultiModalConversation
    QWEN_AVAILABLE = True
except ImportError:
    QWEN_AVAILABLE = False
    print("⚠️ dashscope 未安装，Qwen 模型不可用。")
    print("   安装命令: pip install dashscope")

# API 密钥配置
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

MASTER_PROMPT = """System / Role Definition
You are a Master Quantitative Trader specializing in Chan Theory (缠论). You are evaluating a specific algorithmic signal that has already been identified by our system. You possess strict, objective visual reasoning capabilities regarding "Interval Recursion" (区间套) and "MACD Dynamics" (动力学).

User Instruction Input Context:
I have provided two K-line charts for the same stock at the same time:
1. Image 1 (Left/Top): 30-Minute Level (30M) - PRIMARY SIGNAL SOURCE. This is where the algorithm has identified a specific buy/sell signal.
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
The algorithm has ALREADY identified a specific signal on the 30M chart. Your task is to EVALUATE the quality and reliability of this signal, not to detect it yourself.

Your Task:
1. Confirm (on 30M Chart):
   - Verify the presence of the signal that the algorithm has identified
   - Assess the quality of the signal formation
   
2. Validate (using 5M Chart):
   - Check if the 5M chart shows confirming structure (interval recursion) for the 30M signal.
   
3. Evaluate: Rate the Quality/Confidence of this signal (0-100).
   * High Score (80-100): Textbook 30M pattern + Strong 5M confirmation + MACD alignment.
   * Medium Score (50-79): Clear 30M signal with moderate 5M confirmation.
   * Low Score (0-49): Weak 30M structure, no 5M confirmation, or counter-trend risk.

Analysis Logic (Step-by-Step):
* Step 1: 30M Primary Signal Evaluation
  * Confirm the signal type that was identified (b1/b2/b3a/b3b or s1/s2/s3a/s3b) on the 30M chart.
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
  "evaluated_signal": "string (e.g., b2, s1p) - THE SIGNAL THAT WAS IDENTIFIED BY ALGORITHM",
  "direction": "BUY or SELL",
  "30f_trend_status": "Bullish/Bearish/Consolidation",
  "30f_macd_status": "Deep Divergence/Standard/No Divergence/Momentum Building",
  "5f_confirmation": "Strong/Moderate/Weak/None - How well 5M confirms 30M",
  "score": 0,
  "reasoning": "Explain: 1) What 30M signal was evaluated, 2) How 5M confirmed it, 3) Why the score was given.",
  "key_risk": "string (e.g., 5M lacks confirmation, near strong resistance, MACD weakening)"
}
"""

class VisualJudge:
    def __init__(self):
        self.gemini_client = None
        self.qwen_client = None

        # 初始化 Gemini
        if GEMINI_AVAILABLE and GOOGLE_API_KEY:
            try:
                genai.configure(api_key=GOOGLE_API_KEY)
                self.gemini_client = genai.GenerativeModel('gemini-pro-vision')
                print("✅ Gemini 客户端初始化成功")
            except Exception as e:
                print(f"⚠️ Gemini 客户端初始化失败: {e}")
        else:
            if not GEMINI_AVAILABLE:
                pass # 消息已在顶部打印
            elif not GOOGLE_API_KEY:
                print("⚠️ GOOGLE_API_KEY 未设置，Gemini 不可用")

        # 初始化 Qwen
        if QWEN_AVAILABLE and DASHSCOPE_API_KEY:
            try:
                dashscope.api_key = DASHSCOPE_API_KEY
                # Qwen 的初始化是即时调用，所以这里只设置 api_key
                self.qwen_client = True # 标记为可用
                print("✅ Qwen (DashScope) API Key 设置成功")
            except Exception as e:
                print(f"⚠️ Qwen (DashScope) 初始化失败: {e}")
                self.qwen_client = False
        else:
            if not QWEN_AVAILABLE:
                pass # 消息已在顶部打印
            elif not DASHSCOPE_API_KEY:
                print("⚠️ DASHSCOPE_API_KEY 未设置，Qwen 不可用")
    
    def _prepare_images(self, image_paths):
        """加载并验证图片路径"""
        images = []
        for img_path in image_paths:
            if os.path.exists(img_path):
                images.append(img_path)
                print(f"   📷 加载图片: {os.path.basename(img_path)}")
            else:
                print(f"⚠️ 图片不存在: {img_path}")
                return None
        
        if len(images) < 2:
            print("⚠️ 需要至少2张图片（30M和5M）")
            return None
        return images

    def _parse_llm_response(self, response_text):
        """从LLM返回的文本中提取并解析JSON"""
        response_text = response_text.strip()
        
        # 移除Markdown代码块标记
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            response_text = json_match.group(0)
        else:
            # 如果没有花括号，可能整个字符串就是json，或者格式错误
            print("⚠️ 在响应中未找到有效的JSON结构")
            return None
            
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON 解析失败: {e}")
            print(f"   原始响应: {response_text}")
            return None

    def _post_process_result(self, result, model_name):
        """对解析后的JSON结果进行标准化处理"""
        print(f"   📊 {model_name} 原始返回:")
        print(f"      - score: {result.get('score')}")
        print(f"      - direction: {result.get('direction')}")
        print(f"      - reasoning: {result.get('reasoning', '')[:60]}...")

        score = result.get('score', 50)
        direction = result.get('direction', '').upper()
        
        if direction == 'BUY':
            result['action'] = 'BUY'
        elif direction == 'SELL':
            result['action'] = 'SELL'
        else:
            result['action'] = 'WAIT'
            
        result['analysis'] = f"({model_name}) {result.get('reasoning', '')}"
        result['score'] = int(score) # 确保是整数
        
        print(f"   ✅ {model_name} 评分: {result['score']}/100 | {result['action']}")
        return result

    def call_gemini_api(self, image_paths, signal_type):
        """调用 Gemini API"""
        print("   🤖 调用 Gemini-1.0-Pro-Vision...")
        
        images = [Image.open(p) for p in image_paths]
        prompt = f"已知信号类型: {signal_type}\n\n{MASTER_PROMPT}" if signal_type else MASTER_PROMPT
        contents = [prompt] + images

        generation_config = GenerationConfig(
            temperature=0.1,
            max_output_tokens=2048,
            response_mime_type="application/json",
        )
        
        response = self.gemini_client.generate_content(contents, generation_config=generation_config)
        result = self._parse_llm_response(response.text)
        
        if result:
            return self._post_process_result(result, "Gemini")
        return None

    def call_qwen_api(self, image_paths, signal_type):
        """调用 Qwen API"""
        print("   🤖 调用 Qwen-VL-Plus (备用)...")
        
        prompt = f"已知信号类型: {signal_type}\n\n{MASTER_PROMPT}" if signal_type else MASTER_PROMPT
        
        messages = [{'role': 'user', 'content': []}]
        messages[0]['content'].append({'text': prompt})
        for path in image_paths:
            messages[0]['content'].append({'image': f'file://{os.path.abspath(path)}'})

        response = MultiModalConversation.call(
            model='qwen-vl-plus',
            messages=messages,
            temperature=0.1,
        )

        if response and response.status_code == 200:
            content = response.output.choices[0].message.content
            result = self._parse_llm_response(content)
            if result:
                return self._post_process_result(result, "Qwen")
        else:
            print(f"⚠️ Qwen API 调用失败: {response.code if response else 'No response'} - {response.message if response else 'N/A'}")
        return None

    def evaluate(self, image_paths, signal_type=None):
        """
        按顺序调用大模型进行视觉评分，具备回退机制
        顺序: Gemini -> Qwen
        """
        print(f"👁️ [VisualJudge] 正在视觉分析：{[os.path.basename(p) for p in image_paths]}")
        if signal_type:
            print(f"   📌 已知信号类型: {signal_type}")
            
        images = self._prepare_images(image_paths)
        if not images:
            return self._return_error("图片加载失败")

        # 1. 尝试 Gemini
        if self.gemini_client:
            try:
                result = self.call_gemini_api(images, signal_type)
                if result:
                    return result
            except Exception as e:
                print(f"⚠️ Gemini API 调用异常: {e}")
        else:
            print("-> Gemini 不可用，跳过。")

        # 2. 尝试 Qwen (如果 Gemini 失败)
        if self.qwen_client:
            try:
                print("-> 降级至 Qwen 模型...")
                result = self.call_qwen_api(images, signal_type)
                if result:
                    return result
            except Exception as e:
                print(f"⚠️ Qwen API 调用异常: {e}")
        else:
            print("-> Qwen 不可用，跳过。")
            
        # 3. 如果全部失败
        print("❌ 所有视觉评分模型均调用失败。")
        return self._return_error("所有模型均调用失败")
        
    def _return_error(self, reason):
        """返回一个表示错误的标准化字典"""
        return {
            "evaluated_signal": "ERROR",
            "direction": "WAIT",
            "score": 0,
            "reasoning": f"评分失败: {reason}",
            "key_risk": "模型调用失败，无法进行风险评估",
            "analysis": f"评分失败: {reason}",
            "action": "WAIT"
        }
