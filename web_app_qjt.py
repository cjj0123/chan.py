import streamlit as st
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import datetime
import re 

# 引入核心库
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
from CustomBuySellPoint.CustomStrategy import CCustomStrategy

st.set_page_config(page_title="缠论多周期分析", layout="wide")
st.title("📈 缠论多周期联立分析 (稳健版)")

# --- 侧边栏 ---
st.sidebar.header("1. 股票设置")
# 建议输入纯数字，代码会自动适配
code_input = st.sidebar.text_input("股票代码 (如 600000)", "600000")

default_long_start = "2023-01-01"
# 这个时间主要给日线用
long_begin_time = st.sidebar.text_input("日线开始时间", default_long_start)

st.sidebar.header("2. 指标开关")
show_bi = st.sidebar.checkbox("显示笔 (Bi)", True)
show_seg = st.sidebar.checkbox("显示线段 (Seg)", True)
show_zs = st.sidebar.checkbox("显示中枢 (ZS)", True)
show_bsp = st.sidebar.checkbox("显示买卖点 (BSP)", True)

# --- 辅助函数：智能清洗代码 ---
def get_clean_code(code_str, use_baostock=False):
    code_str = code_str.strip().lower()
    digits = re.findall(r'\d+', code_str)
    if not digits: return code_str 
    number_code = digits[0]
    
    if use_baostock:
        # BaoStock 必须带 sh./sz. 前缀
        if "." in code_str and ("sh" in code_str or "sz" in code_str):
            return code_str
        else:
            if number_code.startswith("6"): return f"sh.{number_code}"
            elif number_code.startswith("8") or number_code.startswith("4"): return f"bj.{number_code}"
            else: return f"sz.{number_code}"
    else:
        # AkShare 只要纯数字
        return number_code

# --- 核心计算函数 ---
def plot_chan_level(raw_code, lv_type, level_name):
    plt.clf()
    plt.close('all')
    
    current_end_time = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # === 策略调整区 ===
    # 1. 日线 -> BaoStock (最稳)
    if lv_type == KL_TYPE.K_DAY:
        current_src = DATA_SRC.BAO_STOCK
        current_begin_time = long_begin_time
        clean_code = get_clean_code(raw_code, use_baostock=True)
        st.info(f"ℹ️ {level_name}: 使用 BaoStock 源 (代码: {clean_code})")

    # 2. 30分钟 / 5分钟 -> 强制改用 BaoStock 
    #    (原 AkShare 报错，改用 BaoStock 修复 IndexError)
    elif lv_type in [KL_TYPE.K_30M, KL_TYPE.K_5M]:
        current_src = DATA_SRC.BAO_STOCK
        clean_code = get_clean_code(raw_code, use_baostock=True)
        
        # 自动限制时间，防止 BaoStock 下载太久
        days_back = 120 if lv_type == KL_TYPE.K_30M else 60 # 30分看4个月，5分看2个月
        new_start = datetime.datetime.now() - datetime.timedelta(days=days_back)
        current_begin_time = new_start.strftime("%Y-%m-%d")
        
        st.info(f"ℹ️ {level_name}: 切换至 BaoStock 源 (代码: {clean_code})")
        st.caption(f"⚡ 为防超时，自动截取最近 {days_back} 天数据: {current_begin_time} 起")

    # 3. 1分钟 -> 保持 AkShare (速度快且已测试通过)
    elif lv_type == KL_TYPE.K_1M:
        current_src = DATA_SRC.AKSHARE
        clean_code = get_clean_code(raw_code, use_baostock=False)
        
        new_start = datetime.datetime.now() - datetime.timedelta(days=5) # 1分钟只看5天
        current_begin_time = new_start.strftime("%Y-%m-%d")
        st.caption(f"⚡ 1分钟线: 使用 AkShare (代码: {clean_code})，最近5天")

    try:
        # 1. 定义配置 (保持不变)
        config = CChanConfig({
            "bi_strict": True,
            "zs_combine": True,
            "zs_algo": "normal",
            "cbsp_strategy": CCustomStrategy, 
            "strategy_para": {
                "use_qjt": True,         # 开启区间套
                "strict_open": True,     # 严格开仓
                "max_sl_rate": 0.05,     # 止损
                "max_profit_rate": 0.10, # 止盈
            }
        })

        # ==========================================
        # 【修正步骤 A】: 先初始化 CChan 获取数据
        # ==========================================
        
        # ⚠️ 关键：区间套(QJT)必须至少有两个级别。
        # 如果您选择的是30分钟(K_30M)，必须同时传入5分钟(K_5M)作为次级别
        # 这里做一个简单的自动判断逻辑示例：
        req_lv_list = [lv_type]
        if lv_type == KL_TYPE.K_30M:
            req_lv_list.append(KL_TYPE.K_5M)
        elif lv_type == KL_TYPE.K_DAY:
            req_lv_list.append(KL_TYPE.K_30M)
        # 如果是其他级别，建议手动指定，否则区间套无法计算(只会返回None)

        chan = CChan(
            code=clean_code,
            begin_time=current_begin_time,
            end_time=current_end_time,
            data_src=current_src, # 确保这里是 DATA_SRC.FUTU
            lv_list=req_lv_list,  # 使用包含次级别的列表
            config=config,
            autype=AUTYPE.QFQ
        )
        
        # 数据基础校验
        if not chan[lv_type]:
            return f"Error: {clean_code} 数据为空。可能是代码错误或非交易日。"
        # CKLine_List 本身表现得就像一个列表，直接计算长度即可
        if len(chan[lv_type]) < 5: 
             return f"Error: 数据量太少 ({len(chan[lv_type] )}根)，无法作图。"

        # ==========================================
        # 【修正步骤 B】: 数据有了之后，再定义绘图
        # ==========================================
        plot_config = {
            "plot_kline": True,
            "plot_bi": show_bi,
            "plot_seg": show_seg,
            "plot_zs": show_zs,
            "plot_bsp": show_bsp,     # 基础买卖点
            "plot_macd": True,
            "plot_cbsp": True,        # 【关键】显示区间套虚线箭头
        }
        
        plot_para = {
            "figure": {"width": 20, "h": 10},
            "cbsp": {
                "plot_cover": True,   # 显示平仓信号
                "fontsize": 14,
                "buy_color": 'r',
                "sell_color": 'g',
            }
        }

        # 3. 启动绘图 (此时 chan 已有值，不会报错)
        plot_driver = CPlotDriver(
            chan, 
            plot_config=plot_config, 
            plot_para=plot_para
        )

        # 4. 返回图表对象给 Streamlit
        # 如果是在 web_app.py 中，通常返回 figure 对象
        return plot_driver.figure

    except Exception as e:
        import traceback
        traceback.print_exc() # 在后台打印详细错误堆栈
        
        err_msg = str(e)
        if "index out of range" in err_msg or "NoneType" in err_msg:
            return (f"❌ 数据获取失败 (IndexError/NoneType)。\n"
                    f"建议检查：\n"
                    f"1. 股票代码 {clean_code} 是否支持富途获取。\n"
                    f"2. 富途 OpenD 是否已开启并登录。\n"
                    f"3. 对应级别的K线数据是否已下载或订阅。")
        return f"系统错误: {err_msg}"

# --- 主界面 Tabs ---
tab_day, tab_30m, tab_5m, tab_1m = st.tabs(["日线 (Day)", "30分钟 (30M)", "5分钟 (5M)", "1分钟 (1M)"])

with tab_day:
    if st.button("生成日线图", key="btn_day"):
        with st.spinner("BaoStock 下载日线中..."):
            fig = plot_chan_level(code_input, KL_TYPE.K_DAY, "日线")
            if isinstance(fig, str): st.error(fig)
            else: st.pyplot(fig)

with tab_30m:
    if st.button("生成30分钟图", key="btn_30m"):
        with st.spinner("BaoStock 下载30分钟数据 (稍慢请耐心)..."):
            fig = plot_chan_level(code_input, KL_TYPE.K_30M, "30分钟")
            if isinstance(fig, str): st.error(fig)
            else: st.pyplot(fig)

with tab_5m:
    if st.button("生成5分钟图", key="btn_5m"):
        with st.spinner("BaoStock 下载5分钟数据 (需10-20秒)..."):
            fig = plot_chan_level(code_input, KL_TYPE.K_5M, "5分钟")
            if isinstance(fig, str): st.error(fig)
            else: st.pyplot(fig)

with tab_1m:
    st.info("ℹ️ 1分钟线继续使用 AkShare，速度较快。")
    if st.button("生成1分钟图", key="btn_1m"):
        with st.spinner("AkShare 下载1分钟数据..."):
            fig = plot_chan_level(code_input, KL_TYPE.K_1M, "1分钟")
            if isinstance(fig, str): st.error(fig)
            else: st.pyplot(fig)