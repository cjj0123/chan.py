"""
视觉评分模块 - 支持 Gemini 和 Qwen 双模型, 具备智能分层调度与上下文缓存 (Context Caching)
"""
import os
import json
import base64
from PIL import Image
import re
import datetime
from urllib.parse import quote
from dotenv import load_dotenv

# 加载环境变量 - 确保从项目根目录加载 .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'email_config.env'))

# 尝试导入 google.generativeai (Gemini)
try:
    import google.generativeai as genai
    from google.generativeai import caching
    from google.generativeai.types import GenerationConfig
    import datetime
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️ google-generativeai 未安装，Gemini 模型不可用。")
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

# API 密钥配置 - 从 .env 文件强制加载
env_path = os.path.join(os.path.dirname(__file__), '.env')
GOOGLE_API_KEY = None
DASHSCOPE_API_KEY = None

if os.path.exists(env_path):
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    # Remove comments (everything after #)
                    line_no_comment = line.split('#', 1)[0].strip()
                    if not line_no_comment or '=' not in line_no_comment:
                        continue
                        
                    key, value = line_no_comment.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"\'')
                    
                    if key == 'GOOGLE_API_KEY':
                        if value and value != "YOUR_GOOGLE_API_KEY_HERE":
                            GOOGLE_API_KEY = value
                    elif key == 'DASHSCOPE_API_KEY':
                        if value and value != "YOUR_DASHSCOPE_API_KEY_HERE":
                            DASHSCOPE_API_KEY = value
    except Exception as e:
        print(f"⚠️ 读取 .env 文件失败: {e}")

# 如果 .env 中没有，尝试环境变量
if not GOOGLE_API_KEY:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not DASHSCOPE_API_KEY:
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

# 信号分析指引（评分核心逻辑）
1. 定位信号：在30M图找到最新（最右侧）的洋红色文字（如b1, b2, s1等）。
2. 结构分析（形态）：
    - 对于一买（b1）/一卖（s1）：必须发生在明显的下跌/上涨趋势末端，且突破前期低点/高点。
    - 对于二买（b2）/二卖（s2）：必须是第一波反弹/回调后的二次探底/冲高，且不破前期极值。
    - 对于三买（b3）/三卖（s3）：必须是突破橙色中枢后的回踩/回抽，且未跌回/突破中枢边缘。
3. 动力学分析（背驰）：
    - 关注MACD副图。买点看绿柱/黄白线下跌力度是否减弱（底背驰）；卖点看红柱/黄白线拉升力度是否衰竭（顶背驰）。
4. 区间套分析（5M图，如果有）：
    - 查看5M图右侧内部结构是否形成了同向的背驰或突破确认。

# 评分标准 (0-100分)
- **90-100分 (极高置信度)**: 结构极其标准完美，MACD背驰/动能支持极其清晰，且5M区间套共振强烈。
- **70-89分 (较高置信度)**: 结构良好，MACD有明显背驰或动能缩减迹象。适合建仓。
- **50-69分 (中立/勉强)**: 结构略有瑕疵（如假突破），MACD背驰不明显或存在模棱两可。
- **0-49分 (低置信度/不建议)**: 结构严重不符、MACD动能与信号完全背离（如b1买点但MACD绿柱仍在放大），或者面临重大的阻力/支撑风险。

# JSON输出要求 (仅输出此JSON格式)
{
  "identified_signal": "图中洋红色标注的信号类型（如b2）",
  "direction": "BUY 或 SELL",
  "step1_30m_structure_analysis": "简述30M图笔/线段/中枢的形态是否支持此信号",
  "step2_30m_macd_analysis": "简述MACD是否存在背驰或动能支持",
  "step3_5m_nested_analysis": "简述5M区间套确认情况（若无图填 N/A_Single_Chart）",
  "conclusion": "一句话核心研判",
  "key_risk": "一句话风险提示",
  "score": 85
}
"""


ENGLISH_MASTER_PROMPT = """System Role Definition
You are a quantitative trading expert proficient in "Chanlun (Chan Theory)", with rigorous visual reasoning capabilities. Your task is to objectively evaluate specific Chanlun buy/sell signals (interval nesting and MACD dynamics) identified by algorithms on the provided K-line charts.

# Input Context
I will provide stock K-line charts at the same time point:
- [Single Chart Mode]: Only 30-minute level (30M) chart provided (main signal source).
- [Dual Chart Mode]: Chart 1 is 30-minute level (30M); Chart 2 is 5-minute level (5M), used for interval nesting confirmation.

# Visual Legend and Anchors (Extremely Important - Identify strictly by colors)
* Focus Area: **Rightmost side of the chart (latest price dynamics)** and **magenta text positions**.
* Black lines: Bi (Strokes) - Basic trend segments.
* Purple lines: Seg (Segments) - Higher-level trend segments.
* Orange rectangles: ZhongShu (Central Pivots) - Consolidation and multi-party battle zones.
* Magenta text/arrows: BUY signals (b1, b2, b3a, b3b, etc.) or SELL signals (s1, s2, s3a, s3b, etc.). Algorithm has marked these on the chart.
* Dashed black/purple lines: Latest incomplete, extending Bi/Seg.
* Sub-chart MACD: Histogram (area/height) and yellow-white lines (DIF/DEA), used to judge momentum exhaustion (divergence).

# Signal Analysis Guide (Scoring Core Logic)
1. Locate Signal: Find the latest (rightmost) magenta text on the 30M chart (e.g., b1, b2, s1, etc.).
2. Structure Analysis (Morphology):
   - For First Buy (b1) / First Sell (s1): Must occur at the end of a clear downtrend/uptrend, breaking previous low/high.
   - For Second Buy (b2) / Second Sell (s2): Must be a secondary test after the initial rebound/pullback, without breaking the extreme.
   - For Third Buy (b3) / Third Sell (s3): Must clearly break out of the orange central pivot and the pullback must not re-enter/cross the pivot edge.
3. Dynamics Analysis (Divergence):
   - Focus on MACD sub-chart. For buys, check if green histogram/yellow-white lines momentum has weakened (bottom divergence); for sells, check if red histogram/yellow-white lines momentum is exhausted (top divergence).
4. Interval Nesting (if 5M chart exists):
   - Check if the 5M chart's rightmost structure confirms the 30M direction via divergence or breakout.

# Scoring Criteria (0-100 points)
- **90-100 pts (Extremely High Confidence)**: Flawless structural setup, obvious MACD divergence/momentum support, strong 5M nested confirmation.
- **70-89 pts (High Confidence)**: Good structure, clear MACD divergence or momentum reduction. Suitable for taking position.
- **50-69 pts (Neutral/Marginal)**: Flawed structure (e.g. false breakout), or ambiguous MACD divergence.
- **0-49 pts (Low Confidence/Reject)**: Structure completely contradicts signal, MACD momentum completely opposite to signal (e.g., b1 buy but green MACD columns are still expanding), or facing major resistance/support risks.

# JSON Output Requirements (ONLY output this JSON format)
{
  "identified_signal": "Extracted magenta signal, e.g., b2",
  "direction": "BUY or SELL",
  "step1_30m_structure_analysis": "Briefly describe if 30M structure supports this signal",
  "step2_30m_macd_analysis": "Briefly describe if MACD divergence or momentum supports it",
  "step3_5m_nested_analysis": "Briefly describe 5M nested confirmation (if none, fill N/A_Single_Chart)",
  "conclusion": "One sentence core judgment",
  "key_risk": "One sentence risk warning",
  "score": 85
}
"""

class GeminiCacheManager:
    """管理 Gemini Context Caching"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.cache = None
        self.cache_name = "chanlun_master_prompt_v1"
        self.last_created = None
        
    def get_cached_model(self, model_id):
        """获取带有缓存内容的模型实例"""
        if not GEMINI_AVAILABLE or not self.api_key:
            return None
            
        try:
            # 检查现有存活的缓存 (TTL假定为最少60分钟，我们设50分钟过期重建)
            now = datetime.datetime.now()
            if self.cache and self.last_created and (now - self.last_created).total_seconds() < 3000:
                # 缓存依然有效
                return genai.GenerativeModel.from_cached_content(cached_content=self.cache)
            
            # 清理旧缓存
            try:
                for c in caching.CachedContent.list():
                    c.delete()
            except Exception as e:
                pass

            # 创建新缓存
            print(f"   ❄️  [GeminiCache] 正在云端创建指令缓存 (TTL: 60分钟)...")
            self.cache = caching.CachedContent.create(
                model=f'models/{model_id}',
                display_name=self.cache_name,
                system_instruction=MASTER_PROMPT,
                ttl=datetime.timedelta(minutes=60),
            )
            self.last_created = now
            print(f"   ✅  [GeminiCache] 上下文缓存创建成功，大幅降低后续请求 Token 消耗！")
            return genai.GenerativeModel.from_cached_content(cached_content=self.cache)
        except Exception as e:
            print(f"⚠️ Gemini Caching 失败 (自动降级到无缓存模式): {e}")
            return genai.GenerativeModel(model_name=model_id, system_instruction=MASTER_PROMPT)

class ModelDispatcher:
    """模型调度员：负责分工、频率控制和回退"""
    def __init__(self):
        # 模型角色配置
        self.primary_model = "gemini-2.5-flash"        # 主攻手：快且便宜，支持缓存
        self.verifier_model = "qwen3.5-plus-2026-02-15"  # 复核员：不同厂家的视角
        self.expert_model = "gemini-2.5-pro"           # 终审专家：逻辑最强
        
        # 初始化组件
        self.cache_mgr = GeminiCacheManager(GOOGLE_API_KEY) if GOOGLE_API_KEY else None

class VisualJudge:
    def __init__(self):
        self.dispatcher = ModelDispatcher()
        self.gemini_available = (GEMINI_AVAILABLE and GOOGLE_API_KEY)
        self.qwen_available = (QWEN_AVAILABLE and DASHSCOPE_API_KEY)
        
        if self.gemini_available:
            try:
                genai.configure(api_key=GOOGLE_API_KEY)
                print(f"✅ Gemini 调度器已就绪 (主战模型: {self.dispatcher.primary_model})")
            except Exception as e:
                print(f"⚠️ Gemini 初始化失败: {e}")
                self.gemini_available = False
        else:
            print("⚠️ Gemini 缺失环境或密钥。")
            
        if self.qwen_available:
            try:
                dashscope.api_key = DASHSCOPE_API_KEY
                print(f"✅ Qwen 调度器已就绪 (交叉复核模型: {self.dispatcher.verifier_model})")
            except Exception as e:
                print(f"⚠️ Qwen 初始化失败: {e}")
                self.qwen_available = False
        else:
            print("⚠️ Qwen 缺失环境或密钥。")
            
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
        if isinstance(response_content, list):
            text_parts = []
            for item in response_content:
                if isinstance(item, dict) and 'text' in item:
                    text_parts.append(item['text'])
                elif isinstance(item, str):
                    text_parts.append(item)
            response_text = ''.join(text_parts)
        else:
            response_text = response_content
        
        if not isinstance(response_text, str):
            print(f"⚠️ 响应内容不是字符串类型: {type(response_text)}")
            return None
            
        response_text = response_text.strip()
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            response_text = json_match.group(0)
        else:
            print("⚠️ 在响应中未找到有效的JSON结构")
            return None
            
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON 解析失败: {e}")
            return None

    def _post_process_result(self, result, model_name):
        """对解析后的JSON结果进行标准化处理"""
        score = result.get('score', 50)
        direction = result.get('direction', '').upper()
        
        if direction == 'BUY':
            result['action'] = 'BUY'
        elif direction == 'SELL':
            result['action'] = 'SELL'
        else:
            result['action'] = 'WAIT'
            
        result['score'] = int(score)
        
        analysis_parts = []
        if result.get('step1_30m_structure_analysis'):
            analysis_parts.append(f"结构: {result['step1_30m_structure_analysis']}")
        if result.get('step2_30m_macd_analysis'):
            analysis_parts.append(f"MACD: {result['step2_30m_macd_analysis']}")
        if result.get('conclusion'):
            analysis_parts.append(f"结论: {result['conclusion']}")
            
        result['analysis'] = f"({model_name}) " + " | ".join(analysis_parts) if analysis_parts else f"({model_name}) 分析不完整"
        
        print(f"   ✅ {model_name} 评分: {result['score']}/100 | {result['action']}")
        return result

    def call_gemini_api(self, image_paths, signal_type, role="PRIMARY"):
        """调用 Gemini 主力模型或专家模型，使用 Context Caching"""
        model_id = self.dispatcher.primary_model if role == "PRIMARY" else self.dispatcher.expert_model
        print(f"   🤖 请求 {model_id} 中...")
        
        try:
            images = [Image.open(p) for p in image_paths]
            model = self.dispatcher.cache_mgr.get_cached_model(model_id)
            
            prompt = f"当前待评估信号类型: {signal_type}\n请按照系统预设指令中的 JSON 格式进行分析评分。"
            contents = [prompt] + images

            generation_config = GenerationConfig(
                temperature=0.1, max_output_tokens=2048, response_mime_type="application/json"
            )
            response = model.generate_content(contents, generation_config=generation_config)
            
            result = self._parse_llm_response(response.text)
            if result:
                return self._post_process_result(result, model_id)
        except Exception as e:
            print(f"⚠️ Gemini API 调用异常: {e}")
            import traceback
            print(traceback.format_exc())
        return None

    def call_qwen_api(self, image_paths, signal_type):
        """调用 Qwen 模型作为交叉复核与备选"""
        import tempfile
        import shutil
        model_id = self.dispatcher.verifier_model
        print(f"   🤖 请求 {model_id} 进行无幻觉交叉复核...")
        
        prompt = f"Known signal type: {signal_type}\n\n{ENGLISH_MASTER_PROMPT}" if signal_type else ENGLISH_MASTER_PROMPT
        temp_files = []
        try:
            messages = [{'role': 'user', 'content': [{'text': prompt}]}]
            for path in image_paths:
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    shutil.copy2(path, tmp.name)
                    messages[0]['content'].append({'image': f'file://{tmp.name}'})
                    temp_files.append(tmp.name)
                    
            response = MultiModalConversation.call(model=model_id, messages=messages, temperature=0.1)
            if response and response.status_code == 200:
                result = self._parse_llm_response(response.output.choices[0].message.content)
                if result: return self._post_process_result(result, model_id)
            else:
                error_msg = f"{response.code if response else 'No response'} - {response.message if response else 'N/A'}"
                print(f"⚠️ Qwen API 调用失败: {error_msg}")
                if "InvalidApiKey" in error_msg or "Invalid API-key" in error_msg:
                    print("🔒 检测到API密钥无效，将禁用Qwen服务")
                    self.qwen_available = False
        except Exception as e:
            print(f"⚠️ Qwen 调用异常: {e}")
            if "InvalidApiKey" in str(e) or "Invalid API-key" in str(e):
                self.qwen_available = False
        finally:
            for tf in temp_files:
                try: os.unlink(tf)
                except: pass
        return None

    def evaluate(self, image_paths, signal_type=None):
        """
        基于智能调度的核心视觉评价入口:
        1. 优先调用基础便宜款模型 (Primary - Gemini Flash Cached)
        2. 若评分处于模棱两可阶段(60-85分)，触发异构模型交叉验收 (Verifier - Qwen)
        3. 若完全挂掉，提供安全后备。
        """
        print(f"👁️ [VisualJudge] 正在视觉分析：{[os.path.basename(p) for p in image_paths]}")
        images = self._prepare_images(image_paths)
        if not images:
            return self._return_error("图片缺失")

        primary_result = None
        # 【阶段一：主考官粗筛】
        if self.gemini_available:
            primary_result = self.call_gemini_api(images, signal_type, "PRIMARY")
            
        # 【阶段二：异构大模型交叉验收审计】
        if primary_result and self.qwen_available:
            score = primary_result.get('score', 0)
            is_critical = signal_type in ['b1', 's1', '1']
            
            # 若处于模棱两可区间，或者重大买卖点结构，呼叫另一个大厂的模型审阅防幻觉！
            if (60 <= score <= 85) or is_critical:
                print(f"   ⚖️  启动审计机制! 信号 {signal_type} 主裁判得分 {score}，存在不确定性，呼唤异构模型审计...")
                verifier_result = self.call_qwen_api(images, signal_type)
                if verifier_result:
                    verifier_score = verifier_result.get('score', 0)
                    # 综合裁定：当意见分歧超过定界，取最小安全分，或者直接均值
                    if abs(score - verifier_score) > 30:
                        final_score = min(score, verifier_score)
                        print(f"   🚨  审计爆出严重分歧！Flash: {score}, Qwen: {verifier_score}。出于风控考虑，取最低分 {final_score}")
                    else:
                        final_score = (score + verifier_score) // 2
                    
                    primary_result['score'] = final_score
                    primary_result['analysis'] = f"【综合决策】原判定:{primary_result['analysis']} \n 【复核意见】:{verifier_result['analysis']}"
            return primary_result

        # 【阶段三：回退保底】若 Gemini 挂了而 Qwen 活着
        if not primary_result and self.qwen_available:
            print("-> Gemini 不可用或返回为空，全量回退至备用模型...")
            return self.call_qwen_api(images, signal_type)
            
        if not primary_result:
            return self._return_error("全部模型调用失败")
        return primary_result

    def _return_error(self, reason):
        return {
            "identified_signal": "ERROR", "direction": "WAIT", "score": 0, "action": "WAIT",
            "analysis": f"视觉评分失败: {reason}"
        }
