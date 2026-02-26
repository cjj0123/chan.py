import os
import json
import requests
from PIL import Image
import io
import base64
import random

# 从环境变量获取 Google API 密钥
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
USE_MOCK_IF_NO_API = True

PROMPT_TEMPLATE = """
你是一位资深的缠论交易专家。分析提供的 30M 和 5M K 线图，对买点信号打分（0-10 分）。

评分标准：
1. 结构完整性 (30%)：30M 下跌中枢是否清晰，c 段是否背驰于 b 段
2. 力度与形态 (40%)：拒绝急跌，有底分型止跌迹象
3. 次级别确认 (30%)：5M 图是否有盘整背驰

决策规则：Score >= 8 则 BUY，否则 WAIT

**只输出 JSON，不要任何其他文字**：
{"score": 整数 0-10, "signal_quality": "高/中/低", "analysis": "一句话理由", "action": "BUY 或 WAIT"}
"""

class VisualJudge:
    def __init__(self, use_mock=False):
        self.use_mock = use_mock

    def call_gemini_api(self, image_paths):
        """调用 Google Gemini API 进行视觉分析"""
        if not GOOGLE_API_KEY:
            if USE_MOCK_IF_NO_API:
                print("⚠️ 没有找到 GOOGLE_API_KEY，使用 Mock 模式")
                self.use_mock = True
                return None
            else:
                raise Exception("GOOGLE_API_KEY 未设置")

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GOOGLE_API_KEY}"

            images = []
            for img_path in image_paths:
                if os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        image_data = f.read()
                        image_base64 = base64.b64encode(image_data).decode('utf-8')
                        images.append({
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": image_base64
                            }
                        })

            if not images:
                print("⚠️ 没有有效的图片文件")
                return None

            request_body = {
                "contents": [{"parts": [{"text": PROMPT_TEMPLATE}] + images}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048}
            }

            response = requests.post(url, json=request_body, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if "candidates" in result and len(result["candidates"]) > 0:
                    content = result["candidates"][0]["content"]["parts"][0]["text"]
                    content = content.strip().replace("```json", "").replace("```", "").strip()
                    if "{" in content and "}" in content:
                        start = content.find("{")
                        end = content.rfind("}") + 1
                        content = content[start:end]
                    try:
                        parsed = json.loads(content)
                        # 将0-10分转换为0-100分制
                        parsed['original_score'] = parsed['score']
                        parsed['score'] = int(parsed['score'] * 10)  # 转换为0-100分制
                        print(f"   ✅ Gemini 评分：{parsed['score']}/100 | {parsed['action']} | {parsed['analysis']}")
                        return parsed
                    except json.JSONDecodeError as e:
                        print(f"⚠️ JSON 解析失败：{e}")
                        print(f"原始内容：{content[:200]}...")
                        return None
                else:
                    print(f"⚠️ API 返回无效结果：{result}")
                    return None
            else:
                print(f"⚠️ API 调用失败：{response.status_code} - {response.text[:200]}")
                return None

        except Exception as e:
            print(f"⚠️ API 调用异常：{e}")
            return None

    def evaluate(self, image_paths):
        """调用大模型进行视觉评分，如果使用模拟模式，则基于趋势清晰度和中枢复杂度进行评估"""
        print(f"👁️ [VisualJudge] 正在视觉分析：{image_paths}")

        if self.use_mock:
            # 使用增强的模拟逻辑，基于趋势清晰度和中枢复杂度
            trend_clarity = random.uniform(0, 1)  # 趋势清晰度 (0-1)
            pivot_complexity = random.uniform(0, 1)  # 中枢复杂度 (0-1)，值越低表示越简单
            
            # 计算综合得分 (0-100)
            # 趋势越清晰、中枢越简单，得分越高
            base_score = trend_clarity * 60 + (1 - pivot_complexity) * 40
            
            # 添加一些随机波动以增加真实性
            volatility = random.uniform(-15, 15)
            score = max(0, min(100, base_score + volatility))
            
            # 根据得分确定信号质量
            if score >= 75:
                signal_quality = "高"
            elif score >= 50:
                signal_quality = "中"
            else:
                signal_quality = "低"
            
            # 生成交易行动建议
            if score >= 75 and trend_clarity > 0.7:
                action = "BUY"
            elif score >= 75 and pivot_complexity < 0.4:
                action = "BUY"
            elif score <= 25 and trend_clarity < 0.3:
                action = "SELL"
            elif score <= 25 and pivot_complexity > 0.7:
                action = "SELL"
            else:
                action = "WAIT"
            
            # 生成分析描述
            if action == "BUY":
                if trend_clarity > 0.7:
                    analysis = f"趋势清晰度高({trend_clarity:.2f})，建议买入"
                else:
                    analysis = f"中枢结构简单({pivot_complexity:.2f})，建议买入"
            elif action == "SELL":
                if trend_clarity < 0.3:
                    analysis = f"趋势不明确({trend_clarity:.2f})，建议卖出"
                else:
                    analysis = f"中枢结构复杂({pivot_complexity:.2f})，建议卖出"
            else:
                analysis = f"趋势清晰度({trend_clarity:.2f})与中枢复杂度({pivot_complexity:.2f})均一般，建议观望"

            result = {
                "score": int(score),
                "signal_quality": signal_quality,
                "analysis": analysis,
                "action": action,
                "trend_clarity": trend_clarity,
                "pivot_complexity": pivot_complexity
            }
            
            print(f"   ✅ 模拟评分：{result['score']}/100 | {result['action']} | {result['analysis']}")
            return result

        valid_image_paths = [img_path for img_path in image_paths if os.path.exists(img_path)]
        if not valid_image_paths:
            print("⚠️ 没有有效的图片，使用 Mock 模式")
            self.use_mock = True
            return self.evaluate(image_paths)

        result = self.call_gemini_api(valid_image_paths)

        if result:
            return result
        else:
            print("⚠️ API 调用失败，降级到 Mock 模式")
            self.use_mock = True
            return self.evaluate(image_paths)
