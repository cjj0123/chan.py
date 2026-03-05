"""
视觉评分模块 - 支持 Gemini 和 Qwen 双模型, 具备回退机制
"""
import os
import json
import base64
from PIL import Image
import re
from dotenv import load_dotenv

# 加载环境变量 - 确保从项目根目录加载 .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'email_config.env'))

# 尝试导入 google.genai (Gemini)
try:
    import google.generativeai as genai
    from google.generativeai.types import GenerationConfig
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️ google-genai 未安装，Gemini 模型不可用。")
    print("   安装命令: pip install google-genai")

# 尝试导入 dashscope (Qwen)
try:
    import dashscope
    from dashscope import MultiModalConversation
    QWEN_AVAILABLE = True
except ImportError:
    QWEN_AVAILABLE = False
    print("⚠️ dashscope 未安装，Qwen 模型不可用。")
    print("   安装命令: pip install dashscope")

# API 密钥配置 - 从 .env 文件强制加载，忽略系统环境变量
env_path = os.path.join(os.path.dirname(__file__), '.env')
GOOGLE_API_KEY = None
DASHSCOPE_API_KEY = None

if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                # 移除可能存在的引号和前后空白
                value = value.strip().strip('"\'')
                
                if key == 'GOOGLE_API_KEY':
                    if value and value != "YOUR_GOOGLE_API_KEY_HERE":
                        GOOGLE_API_KEY = value
                    else:
                        print("⚠️ 警告: .env 文件中的 GOOGLE_API_KEY 仍为默认占位符，请替换为有效的API密钥。")
                elif key == 'DASHSCOPE_API_KEY':
                    if value and value != "YOUR_DASHSCOPE_API_KEY_HERE":
                        DASHSCOPE_API_KEY = value
                    else:
                        print("⚠️ 警告: .env 文件中的 DASHSCOPE_API_KEY 仍为默认占位符，请替换为有效的API密钥。")
else:
    print(f"⚠️ 警告: 未找到配置文件 {env_path}，请确保已创建并配置API密钥。")
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

MASTER_PROMPT = """系统角色定义
你是一位精通“缠论（Chanlun）”的量化交易专家，具备严密的视觉推理能力。你的任务是客观评估由算法在我们提供的K线图上识别出的特定缠论买卖信号（区间套与MACD动力学）。

# 输入上下文
我将提供同一时间点的股票K线图：
- 【单图模式】：仅提供 30分钟级别（30M）图表（主要信号源）。
- 【双图模式】：图1为 30分钟级别（30M）；图2为 5分钟级别（5M），用于区间套确认。

# 视觉图例与锚点（极其重要，请严格根据颜色识别）
* 重点关注区域：图表的**最右侧（最新价格动态）**以及**洋红色文字出现的位置**。
* 黑色线条：Bi（笔）- 基础趋势段。
* 紫色线条：Seg（线段）- 高级别趋势段。
* 橙色矩形：ZhongShu（中枢）- 盘整与多空博弈区域。
* 洋红色文字/箭头：BUY信号（b1, b2, b3a, b3b等）或 SELL信号（s1, s2, s3a, s3b等）。算法已在图中标出。
* 虚线黑色/紫色：最新未完成、正在延伸的笔/线段。
* 副图MACD：柱状图（面积/高度）和黄白线（DIF/DEA），用于判断动力衰竭（背驰）。

# 信号代码字典
[买入看涨信号 - BUY]
* b1p/b1 (一买)：趋势背驰点。视觉特征：价格创新低，但对应MACD绿柱面积/黄白线未创新低（底背驰）。
* b2/b2s (二买)：趋势回撤不创新低。视觉特征：底部抬高。
* b3a/b3b (三买)：中枢突破与回踩。视觉特征：向上脱离橙色中枢，随后向下的Bi/Seg未跌破中枢上沿。

[卖出看跌信号 - SELL]
* s1p/s1 (一卖)：趋势背驰点。视觉特征：价格创新高，但对应MACD红柱面积/黄白线未创新高（顶背驰）。
* s2/s2s (二卖)：趋势反弹不创新高。视觉特征：顶部降低。
* s3a/s3b (三卖)：中枢跌破与回抽。视觉特征：向下脱离橙色中枢，随后向上的Bi/Seg未突破中枢下沿。

# 你的评估任务（逐步推理）
算法已在图上标记了信号。你不需要重新寻找信号，你的任务是**评估该信号的置信度/质量（0-100分）**。
1. 定位：在30M图上找到洋红色标注的信号。
2. 结构质检（30M）：判断该信号所处的Bi、Seg与ZhongShu的相对位置是否符合上述“信号字典”的定义。
3. 动力学质检（30M）：观察MACD副图，对比进出中枢的力度，是否存在支持该信号的动能或背驰。
4. 区间套质检（5M）：如果提供了5M图表，寻找5M图表最右侧是否形成了支持30M方向的内部结构（如30M的b1，在5M上是否呈现完整的下跌趋势背驰）。

# JSON输出要求
必须严格按照以下JSON格式输出，严禁包含任何JSON区块之外的文字。请务必**先输出分析过程，最后输出分数**：
{
  "identified_signal": "提取图中的洋红色信号，如 b2",
  "direction": "BUY 或 SELL",
  "step1_30m_structure_analysis": "描述信号在30M图上的视觉位置：笔/线段的形态，以及与最近橙色中枢的关系是否标准。",
  "step2_30m_macd_analysis": "描述30M副图MACD的状态：说明价格极值与MACD柱状图/黄白线的关系，是否存在背驰或动能支持。",
  "step3_5m_nested_analysis": "如果提供了5M图，描述其是否确认了30M的信号（例如寻找次级别背驰或突破）；如果仅提供单图，请填 'N/A_Single_Chart'。",
  "conclusion": "综合以上步骤，总结该信号的可靠性。",
  "key_risk": "指出潜在风险，如：MACD死叉向下、面临强阻力、5M级别结构矛盾等。",
  "score": 85
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
                self.gemini_client = genai.GenerativeModel('gemini-2.5-pro')
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
        
        if len(images) < 1:
            print("⚠️ 需要至少1张图片")
            return None
        elif len(images) < 2:
            print("⚠️ 只有1张图片，将使用单图模式进行分析")
        return images

    def _parse_llm_response(self, response_content):
        """从LLM返回的内容中提取并解析JSON"""
        # 处理Qwen API返回的列表格式
        if isinstance(response_content, list):
            # Qwen多模态API返回的是内容块列表，我们需要找到文本块
            text_parts = []
            for item in response_content:
                if isinstance(item, dict) and 'text' in item:
                    text_parts.append(item['text'])
                elif isinstance(item, str):
                    text_parts.append(item)
            response_text = ''.join(text_parts)
        else:
            # Gemini或其他API返回的字符串格式
            response_text = response_content
        
        if not isinstance(response_text, str):
            print(f"⚠️ 响应内容不是字符串类型: {type(response_text)}")
            return None
            
        response_text = response_text.strip()
        
        # 移除Markdown代码块标记
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            response_text = json_match.group(0)
        else:
            # 如果没有花括号，可能整个字符串就是json，或者格式错误
            print("⚠️ 在响应中未找到有效的JSON结构")
            print(f"   原始响应类型: {type(response_content)}")
            print(f"   原始响应内容: {str(response_content)[:200]}...")
            return None
            
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON 解析失败: {e}")
            print(f"   原始响应: {response_text[:200]}...")
            return None

    def _post_process_result(self, result, model_name):
        """对解析后的JSON结果进行标准化处理，保持完整的JSON结构"""
        print(f"   📊 {model_name} 原始返回:")
        print(f"      - identified_signal: {result.get('identified_signal')}")
        print(f"      - direction: {result.get('direction')}")
        print(f"      - score: {result.get('score')}")
        print(f"      - conclusion: {result.get('conclusion', '')[:60]}...")

        # 确保必要的字段存在
        score = result.get('score', 50)
        direction = result.get('direction', '').upper()
        
        # 添加action字段用于交易决策
        if direction == 'BUY':
            result['action'] = 'BUY'
        elif direction == 'SELL':
            result['action'] = 'SELL'
        else:
            result['action'] = 'WAIT'
            
        # 确保score是整数
        result['score'] = int(score)
        
        # 为兼容性添加analysis字段，组合所有分析步骤
        analysis_parts = []
        if result.get('step1_30m_structure_analysis'):
            analysis_parts.append(f"结构分析: {result['step1_30m_structure_analysis']}")
        if result.get('step2_30m_macd_analysis'):
            analysis_parts.append(f"MACD分析: {result['step2_30m_macd_analysis']}")
        if result.get('step3_5m_nested_analysis') and result['step3_5m_nested_analysis'] != 'N/A_Single_Chart':
            analysis_parts.append(f"区间套分析: {result['step3_5m_nested_analysis']}")
        if result.get('conclusion'):
            analysis_parts.append(f"结论: {result['conclusion']}")
        if result.get('key_risk'):
            analysis_parts.append(f"风险: {result['key_risk']}")
            
        result['analysis'] = f"({model_name}) " + " | ".join(analysis_parts) if analysis_parts else f"({model_name}) 分析数据不完整"
        
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
        print("   🤖 调用 Qwen3.5-Plus (备用)...")
        
        prompt = f"已知信号类型: {signal_type}\n\n{MASTER_PROMPT}" if signal_type else MASTER_PROMPT
        
        messages = [{'role': 'user', 'content': []}]
        messages[0]['content'].append({'text': prompt})
        for path in image_paths:
            messages[0]['content'].append({'image': f'file://{os.path.abspath(path)}'})

        try:
            response = MultiModalConversation.call(
                model='qwen3.5-plus',
                messages=messages,
                temperature=0.1,
            )
            
            if response and response.status_code == 200:
                content = response.output.choices[0].message.content
                result = self._parse_llm_response(content)
                if result:
                    return self._post_process_result(result, "Qwen")
            else:
                error_msg = f"{response.code if response else 'No response'} - {response.message if response else 'N/A'}"
                print(f"⚠️ Qwen API 调用失败: {error_msg}")
                
                # 如果是API密钥问题，禁用Qwen客户端
                if "InvalidApiKey" in error_msg or "Invalid API-key" in error_msg:
                    print("🔒 检测到API密钥无效，将禁用Qwen服务")
                    self.qwen_client = False
                
                if hasattr(response, 'request_id'):
                    print(f"   请求ID: {response.request_id}")
        except Exception as e:
            error_str = str(e)
            print(f"⚠️ Qwen API 调用异常: {e}")
            
            # 如果是API密钥问题，禁用Qwen客户端
            if "InvalidApiKey" in error_str or "Invalid API-key" in error_str:
                print("🔒 检测到API密钥无效，将禁用Qwen服务")
                self.qwen_client = False
            
            import traceback
            print(f"详细错误信息: {traceback.format_exc()}")
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
                    print(f"-> Gemini 返回结果: {result}")
                    return result
                else:
                    print("-> Gemini 未返回有效结果")
            except Exception as e:
                print(f"⚠️ Gemini API 调用异常: {e}")
                import traceback
                print(f"详细错误信息: {traceback.format_exc()}")
        else:
            print("-> Gemini 不可用，跳过。")

        # 2. 尝试 Qwen (如果 Gemini 失败)
        if self.qwen_client:
            try:
                print("-> 降级至 Qwen 模型...")
                result = self.call_qwen_api(images, signal_type)
                if result:
                    print(f"-> Qwen 返回结果: {result}")
                    return result
                else:
                    print("-> Qwen 未返回有效结果")
            except Exception as e:
                print(f"⚠️ Qwen API 调用异常: {e}")
                import traceback
                print(f"详细错误信息: {traceback.format_exc()}")
        else:
            print("-> Qwen 不可用，跳过。")
            
        # 3. 如果全部失败
        print("❌ 所有视觉评分模型均调用失败。")
        return self._return_error("所有模型均调用失败")
        
    def _return_error(self, reason):
        """返回一个表示错误的标准化字典，符合JSON输出格式要求"""
        return {
            "identified_signal": "ERROR",
            "direction": "WAIT",
            "step1_30m_structure_analysis": "视觉评分失败",
            "step2_30m_macd_analysis": "视觉评分失败",
            "step3_5m_nested_analysis": "N/A_Single_Chart",
            "conclusion": f"评分失败: {reason}",
            "key_risk": "模型调用失败，无法进行风险评估",
            "score": 0,
            "action": "WAIT"
        }
