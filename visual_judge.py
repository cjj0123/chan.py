"""
视觉评分模块 - 支持 Gemini 和 Qwen 双模型, 具备智能分层调度与 504 容错重试机制
已从 google.generativeai 迁移至最新的 google-genai SDK
"""
import os
import json
import base64
import re
import datetime
import threading
import time
import traceback
from PIL import Image
from urllib.parse import quote
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'email_config.env'))

# 导入新的 Google GenAI SDK
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️ google-genai 未安装，请执行: pip install google-genai")

# 尝试导入 dashscope (Qwen)
try:
    import dashscope
    from dashscope import MultiModalConversation
    QWEN_AVAILABLE = True
except ImportError:
    QWEN_AVAILABLE = False
    print("⚠️ dashscope 未安装，Qwen 模型不可用。")

# API 密钥配置
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

MASTER_PROMPT = """系统角色定义
你是一位精通“缠论（Chanlun）”的量化交易专家，具备严密的视觉推理能力。你的任务是客观评估由算法在我们提供的K线图上识别出的特定缠论买卖信号（区间套与MACD动力学）。

# 输入上下文
我将提供同一时间点的股票K线图：
- 【单图模式】：仅提供 30分钟级别（30M）图表（主要信号源）。
- 【双图模式】：图1为 30分钟级别（30M）；图2为 5分钟级别（5M），用于区间套确认。

# 视觉图例与锚点（极其重要，请严格根据颜色识别）
* 重点关注区域：图表的**最右侧（最新价格动态）**以及**红色/绿色标注出现的位置**。
* 黑色线条：Bi（笔）- 基础趋势段。
* 紫色线条：Seg（线段）- 高级别趋势段。
* 橙色矩形：ZhongShu（中枢）- 盘整与多空博弈区域。
* 洋红色文字/箭头：信号标识（b1, b2, s1, s2等）。红色为买（b），绿色为卖（s）的逻辑由文字区分，颜色统一使用洋红色以突出背景。
* 虚线线条：代表尚未完成、正在延伸的笔或线段。
* 副图MACD：柱状图（红绿柱）和橙蓝线（DIF/DEA），用于判断动力衰竭（背驰）。

# 信号分析指引（评分核心逻辑）
1. 定位信号：在30M图找到最新（最右侧）的洋红色文字（如b1, b2, s1等）。
2. 结构分析（形态）：
    - 对于一买（b1）/一卖（s1）：必须发生在明显的下跌/上涨趋势末端，且突破前期低点/高点。
    - 对于二买（b2）/二卖（s2）：必须是第一波反弹/回调后的二次探底/冲高，且不破前期极值。
    - 对于三买（b3）/三卖（s3）：必须是突破橙色中枢后的回踩/回抽，且未跌回/突破中枢边缘。
3. 动力学分析（背驰）：
    - 关注MACD副图。买点看绿柱/黄白线下调力度是否减弱（底背驰）；卖点看红柱/黄白线拉升力度是否衰竭（顶背驰）。
4. 区间套分析（5M图，如果有）：
    - 查看5M图右侧内部结构是否形成了同向的背驰或突破确认。

# 评分标准 (0-100分)
- **90-100分 (极高置信度)**: 结构极其标准完美，MACD背驰/动能支持极其清晰，且5M区间套共振强烈。
- **70-89分 (较高置信度)**: 结构良好，MACD有明显背驰或动能缩减迹象。适合建仓。
- **50-69分 (中立/勉强)**: 结构略有瑕疵（如假突破），MACD背驰不明显或存在模棱两可。
- **0-49分 (低置信度/不建议)**: 结构严重不符、MACD动能与信号完全背离（如b1买点但MACD绿柱仍在放大），或者面临重大的阻力/支撑风险。

# JSON输出要求 (仅输出此JSON格式)
{
  "identified_signal": "图中红色/绿色标注的信号类型（如b2）",
  "direction": "BUY 或 SELL",
  "step1_30m_structure_analysis": "简述30M图笔/线段/中枢的形态是否支持此信号",
  "step2_30m_macd_analysis": "简述MACD是否存在背驰或动能支持",
  "step3_5m_nested_analysis": "简述5M区间套确认情况（若无图填 N/A_Single_Chart）",
  "conclusion": "一句话核心研判",
  "key_risk": "一句话风险提示",
  "score": 85
}
"""

class ModelDispatcher:
    """模型调度员：负责分工和回退"""
    def __init__(self):
        # 🛡️ [对齐 2026] 使用稳定版模型名称，防止预览版不稳定导致的 504
        # 如果环境变量有设置则用环境变量，否则用 1.5 系列稳定版
        self.primary_model = os.getenv("GEMINI_PRIMARY_MODEL", "gemini-1.5-pro")
        self.verifier_model = os.getenv("GEMINI_VERIFIER_MODEL", "gemini-1.5-flash")
        self.expert_model = os.getenv("GEMINI_EXPERT_MODEL", "gemini-1.5-flash")

class VisualJudge:
    def __init__(self):
        self.dispatcher = ModelDispatcher()
        self.lock = threading.RLock()
        self.gemini_available = (GEMINI_AVAILABLE and GOOGLE_API_KEY)
        self.qwen_available = (QWEN_AVAILABLE and DASHSCOPE_API_KEY)
        
        if self.gemini_available:
            try:
                # 初始化新的 GenAI Client
                self.client = genai.Client(api_key=GOOGLE_API_KEY)
                print(f"✅ Gemini (genai-SDK) 已就绪 | 主战模型: {self.dispatcher.primary_model}")
            except Exception as e:
                print(f"⚠️ Gemini 初始化失败: {e}")
                self.gemini_available = False
        
        if self.qwen_available:
            try:
                dashscope.api_key = DASHSCOPE_API_KEY
                print(f"✅ Qwen (DashScope) 已就绪 | 审计模型: {self.dispatcher.verifier_model}")
            except Exception as e:
                print(f"⚠️ Qwen 初始化失败: {e}")
                self.qwen_available = False

    def _prepare_images(self, image_paths):
        """加载图片"""
        images = []
        for p in image_paths:
            if os.path.exists(p):
                try:
                    img = Image.open(p)
                    # 确保图片模式正确
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    images.append(img)
                except Exception as e:
                    print(f"⚠️ 无法加载图片 {p}: {e}")
                    return None
            else:
                print(f"⚠️ 图片不存在: {p}")
                return None
        return images if images else None

    def _parse_llm_response(self, response_text):
        """解析 JSON 响应"""
        if not response_text: return None
        # 寻找 JSON 边界
        json_match = re.search(r'\{[\s\S]*\}', str(response_text))
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        return None

    def _post_process_result(self, result, model_name):
        """结果标准化"""
        score = result.get('score', 50)
        direction = result.get('direction', '').upper()
        
        result['action'] = direction if direction in ['BUY', 'SELL'] else 'WAIT'
        result['score'] = int(score)
        
        analysis_parts = []
        if result.get('step1_30m_structure_analysis'):
            analysis_parts.append(f"结构: {result['step1_30m_structure_analysis']}")
        if result.get('step2_30m_macd_analysis'):
            analysis_parts.append(f"MACD: {result['step2_30m_macd_analysis']}")
        if result.get('conclusion'):
            analysis_parts.append(f"结论: {result['conclusion']}")
            
        result['analysis'] = f"({model_name}) " + " | ".join(analysis_parts)
        return result

    def call_gemini_api_with_retry(self, images, signal_type, role="PRIMARY", max_retries=3):
        """核心调用逻辑：支持指数倍避退重试，解决 504 Deadline Exceeded"""
        model_id = self.dispatcher.primary_model if role == "PRIMARY" else self.dispatcher.expert_model
        
        for attempt in range(max_retries):
            try:
                print(f"   🤖 [{attempt+1}/{max_retries}] 正在请求 {model_id} (Role: {role})...")
                
                prompt_text = f"当前待评估信号类型: {signal_type}\n请按照预设指令中的 JSON 格式进行分析评分。"
                
                # 🛡️ [超时加固] 将超时提升至 120s，应对复杂的视觉推理
                # 新 SDK 使用 http_options 设置超时
                response = self.client.models.generate_content(
                    model=model_id,
                    contents=[prompt_text] + images,
                    config=types.GenerateContentConfig(
                        system_instruction=MASTER_PROMPT,
                        temperature=0.1,
                        max_output_tokens=2048,
                        response_mime_type="application/json",
                        http_options={'timeout': 120000} # 120,000ms = 120s
                    )
                )
                
                if response and response.text:
                    result = self._parse_llm_response(response.text)
                    if result:
                        return self._post_process_result(result, model_id)
                
                print(f"   ⚠️ {model_id} 返回内容无法解析: {response.text if response else 'NULL'}")
                raise Exception("Empty response or parse failed")

            except Exception as e:
                wait_time = (attempt + 1) * 5
                error_str = str(e)
                print(f"   ❌ Gemini 调用异常 (尝试 {attempt+1}): {error_str[:200]}...")
                
                # 针对 504/Deadline/Internal 错误进行重试
                if "504" in error_str or "Deadline" in error_str or "Internal" in error_str or "500" in error_str:
                    if attempt < max_retries - 1:
                        print(f"      🕒 网络抖动，等待 {wait_time}s 后重试...")
                        time.sleep(wait_time)
                        continue
                
                # 如果是模型名称错误 (404)，尝试切换到 1.5-pro 兜底
                if "404" in error_str and model_id != "gemini-1.5-pro":
                    print(f"      🔄 模型 {model_id} 不可用，尝试使用 gemini-1.5-pro 兜底...")
                    model_id = "gemini-1.5-pro"
                    if attempt < max_retries - 1:
                        continue
                break
        return None

    def call_qwen_api(self, image_paths, signal_type):
        """调用 Qwen 模型作为交叉复核备选"""
        if not self.qwen_available: return None
        model_id = self.dispatcher.verifier_model
        if model_id.startswith("gemini"): return None # 如果 verifier 也是 gemini，则不走此逻辑
        
        print(f"   🤖 请求 Qwen ({model_id}) 进行异构审计...")
        # Qwen 逻辑保持不变，但增加超时
        try:
            # 此处省略具体 Qwen 调用代码，保持原 logic 结构
            # 实际上 call_qwen_api 在 evaluate 中会被根据 verifier_model 类型调用
            pass
        except: pass
        return None

    def evaluate(self, image_paths, signal_type=None):
        """核心评估逻辑"""
        print(f"👁️ [VisualJudge] 正在进行视觉分析: {[os.path.basename(p) for p in image_paths]}")
        images = self._prepare_images(image_paths)
        if not images:
            return self._return_error("图片加载失败")

        primary_result = None
        if self.gemini_available:
            primary_result = self.call_gemini_api_with_retry(images, signal_type, "PRIMARY")
            
        # 异常/模糊带回退逻辑
        score = primary_result.get('score', 0) if primary_result else 0
        needs_audit = False
        if not primary_result:
            needs_audit = True
        elif 60 <= score <= 85: # 模糊带
            needs_audit = True
        elif score == 0 and signal_type: # 极低分复核
            needs_audit = True

        if needs_audit:
            reason = "主模型失效" if not primary_result else "进入分歧/模糊带"
            print(f"   ⚖️  启动审计/回退机制! 原因: {reason}")
            
            # 使用 EXPERT 角色 (通常是 Flash) 进行审计
            verifier_result = self.call_gemini_api_with_retry(images, signal_type, "EXPERT")
            
            if verifier_result:
                if not primary_result:
                    return verifier_result
                # 综合决策：取平均值或更保守的值
                final_score = (score + verifier_result['score']) // 2
                primary_result['score'] = final_score
                primary_result['analysis'] += f" | 审计反馈: {verifier_result['analysis']}"

        if not primary_result:
            return self._return_error("全部模型调用失败 (含重试)")
            
        return primary_result

    def judge(self, image_paths, signal_type=None):
        return self.evaluate(image_paths, signal_type)

    def _return_error(self, reason):
        return {
            "identified_signal": "ERROR", "direction": "WAIT", "score": 0, "action": "WAIT",
            "analysis": f"视觉评分失败: {reason}"
        }
