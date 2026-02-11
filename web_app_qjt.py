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
        config = CChanConfig({
            "bi_strict": True,
            "zs_combine": True,
            "zs_algo": "normal",
            "cbsp_strategy": CCustomStrategy, 
            "strategy_para": {
                "use_qjt": True,         # 开启区间套
                "strict_open": True,     # 严格开仓
                
                # 【设置止损止盈】
                "max_sl_rate": 0.05,     # 最大止损率 (5%)
                "max_profit_rate": 0.10, # 最大止盈率 (10%)
                # 也可以扩展支持追踪止损
                # "trailing_stop": True 
            }
        })

        plot_config = {
            "plot_kline": True,
            "plot_bi": show_bi,
            "plot_seg": show_seg,
            "plot_zs": show_zs,
            "plot_bsp": show_bsp,
            "plot_macd": True,
        }
        
        plot_para = {
            "seg": {"width": 2, "color": "red"},
            "bi": {"show_num": False},
            "figure": {"w": 14, "h": 8}
        }

        chan = CChan(
            code=clean_code,
            begin_time=current_begin_time,
            end_time=current_end_time,
            data_src=current_src,
            lv_list=[lv_type], 
            config=config,
            autype=AUTYPE.QFQ
        )
        
        if not chan[lv_type]:
            return f"Error: {level_name} 数据为空。可能是代码错误或非交易日。"

        if len(chan[lv_type]) < 5:
             return f"Error: 数据量太少 ({len(chan[lv_type])}根)，无法作图。"

        CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)
        return plt.gcf()

    except Exception as e:
        err_msg = str(e)
        if "index out of range" in err_msg or "NoneType" in err_msg:
            return (f"❌ 数据获取失败 (IndexError)。\n"
                    f"建议：\n"
                    f"1. 确认代码 {clean_code} 是否正确。\n"
                    f"2. 如果是刚上市新股，可能无历史数据。\n"
                    f"3. 检查网络连接。")
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