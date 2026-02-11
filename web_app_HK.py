import streamlit as st
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import datetime
import re 
import pandas as pd
import time
import sys
import os

# ==========================================
# 🛑 1. 环境与核心依赖检查
# ==========================================
st.set_page_config(page_title="缠论多周期分析-本地版", layout="wide")

# web_app_hk.py 顶部
try:
    from DataAPI.FutuAPI import CFutuAPI
except ImportError as e:
    st.error(f"❌ 导入失败: {e}")

# 1. 必须先从核心库导入 DATA_SRC
try:
    from Common.CEnum import DATA_SRC
except ImportError:
    # 如果核心库路径有问题导致导入失败，定义一个伪类防止崩溃
    class DATA_SRC:
        FUTU = 99
        BAO_STOCK = 0

# 2. 动态注入 FUTU 属性（如果原始枚举里没有）
if not hasattr(DATA_SRC, 'FUTU'):
    setattr(DATA_SRC, 'FUTU', 99)

# 导入 Chan 核心组件
try:
    from Chan import CChan
    from ChanConfig import CChanConfig
    from Common.CEnum import AUTYPE, KL_TYPE
    from KLine.KLine_Unit import CKLine_Unit
    from Plot.PlotDriver import CPlotDriver
    from ChanConfig import CChanConfig
    from CustomBuySellPoint.CustomStrategy import CCustomStrategy  # 必须导入自带策略类
    from Common.CEnum import KL_TYPE
except ImportError as e:
    st.error(f"❌ 核心库组件丢失: {e}")
    st.stop()


# ==========================================
# 🧩 2. 重写富途驱动
# ==========================================

class CFutuDriver:
    def __init__(self, code, k_type=None, begin_date=None, end_date=None, autype=None):
        self.code = code
        self.k_type = k_type
        self.begin_date = begin_date
        self.end_date = end_date
        self.autype = autype
        self.klines = [] 
        self.iter_index = 0
        self._fetch_data()

    @classmethod
    def do_init(cls): pass

    @classmethod
    def do_close(cls): pass

    def _fetch_data(self):
        if not HAS_FUTU: return
        futu_code = self.code
        if not (futu_code.startswith("HK.") or futu_code.startswith("US.")):
             digits = re.findall(r'\d+', futu_code)
             if digits and len(digits[0]) == 5: futu_code = "HK." + digits[0]

        type_map = {
            KL_TYPE.K_DAY: 'K_DAY', KL_TYPE.K_1M: 'K_1M',
            KL_TYPE.K_5M: 'K_5M', KL_TYPE.K_30M: 'K_30M', KL_TYPE.K_60M: 'K_60M',
        }
        futu_ktype = type_map.get(self.k_type, 'K_DAY')

        try:
            ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            if self.k_type == KL_TYPE.K_DAY:
                ret, df, _ = ctx.request_history_kline(futu_code, start=self.begin_date, end=self.end_date, ktype=futu_ktype, autype=AuType.QFQ)
            else:
                ctx.subscribe([futu_code], [SubType.K_1M, SubType.K_5M, SubType.K_30M])
                time.sleep(0.5)
                ret, df = ctx.get_cur_kline(futu_code, 1000, ktype=futu_ktype, autype=AuType.QFQ)
            ctx.close()

            if ret == RET_OK and not df.empty:
                # 兼容所有可能的时间字段名
                time_col = next((c for c in ['time_key', 'time', 'last_time'] if c in df.columns), None)
                for _, row in df.iterrows():
                    self.klines.append(CKLine_Unit({
                        'time': str(row[time_col]),
                        'open': float(row['open']), 'close': float(row['close']),
                        'high': float(row['high']), 'low': float(row['low']),
                        'volume': float(row.get('volume', 0))
                    }))
        except Exception as e:
            st.error(f"Futu 内部抓取错误: {e}")

    def __iter__(self):
        self.iter_index = 0
        return self

    def __next__(self):
        if self.iter_index < len(self.klines):
            kl = self.klines[self.iter_index]
            self.iter_index += 1
            return kl
        raise StopIteration

# ==========================================
# 💉 3. 终极暴力补丁：直接向类原型注入方法
# ==========================================

# 强行给类添加方法，确保万无一失
def force_get_kl_data(self):
    return self

def force_next(self):
    return self.__next__()

CFutuDriver.get_kl_data = force_get_kl_data
CFutuDriver.next = force_next

# web_app_hk.py 中的注入部分
_original_get_stock_api = CChan.GetStockAPI

def patched_get_stock_api(self):
    if self.data_src == DATA_SRC.FUTU:
        return CFutuAPI  # 确保这里返回的是你刚导入的那个类名
    return _original_get_stock_api(self)

CChan.GetStockAPI = patched_get_stock_api

# ==========================================
# 🚀 4. Streamlit 界面逻辑
# ==========================================

st.title("📈 缠论多周期分析 (富途本地直连版)")

# --- 侧边栏 ---
st.sidebar.header("1. 证券参数")
code_input = st.sidebar.text_input("代码 (如 HK.00700 或 00700)", "HK.00700")
long_begin_time = st.sidebar.text_input("日线起始日期", "2023-01-01")

st.sidebar.header("2. 缠论指标")
show_bi = st.sidebar.checkbox("笔 (Bi)", True)
show_seg = st.sidebar.checkbox("线段 (Seg)", True)
show_zs = st.sidebar.checkbox("中枢 (ZS)", True)
show_bsp = st.sidebar.checkbox("买卖点 (BSP)", True)

def run_analysis(raw_code, lv_type):
    plt.clf(); plt.close('all')
    raw_code = raw_code.strip().upper()
    current_begin = long_begin_time
    
    # 自动识别市场
    if "HK." in raw_code or (raw_code.isdigit() and len(raw_code)==5):
        current_src = DATA_SRC.FUTU
        clean_code = f"HK.{raw_code}" if not raw_code.startswith("HK.") else raw_code
        if lv_type != KL_TYPE.K_DAY: 
            current_begin = (datetime.datetime.now() - datetime.timedelta(days=15)).strftime("%Y-%m-%d")
        st.info(f"🔍 模式：港股 | 代码：{clean_code}")
    else:
        # A股使用 BaoStock (本地需 pip install baostock)
        try:
            from Common.CEnum import DATA_SRC as DS
            #current_src = DS.BAO_STOCK
            digits = re.findall(r'\d+', raw_code)[0]
            clean_code = f"sh.{digits}" if digits.startswith("6") else f"sz.{digits}"
            st.info(f"🔍 模式：A股 | 代码：{clean_code}")
        except:
            return "❌ 系统无法处理此代码，请使用 HK.XXXXX 格式"

    try:
        config = CChanConfig({"bi_strict": True, "zs_combine": True, "zs_algo": "normal"})
        plot_config = {"plot_kline": True, "plot_bi": show_bi, "plot_seg": show_seg, 
                       "plot_zs": show_zs, "plot_bsp": show_bsp, "plot_macd": True}
        plot_para = {"seg": {"width": 2, "color": "red"}, "bi": {"show_num": False}, "figure": {"w": 12, "h": 7}}

        chan = CChan(
            code=clean_code,
            begin_time=current_begin,
            end_time=datetime.datetime.now().strftime("%Y-%m-%d"),
            data_src=DATA_SRC.FUTU,
            lv_list=[lv_type],
            config=config,
            autype=AUTYPE.QFQ
        )

        if not chan[lv_type] or len(chan[lv_type]) == 0:
            return "❌ 获取数据为空。请检查：1. OpenD 是否登录 2. 该品种是否有权限 3. 此时段是否停牌。"

        CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)
        return plt.gcf()

    except Exception as e:
        import traceback
        return f"运行崩溃: {str(e)}\n{traceback.format_exc()}"

# --- 标签页渲染 ---
tabs = st.tabs(["日线", "30分钟", "5分钟", "1分钟"])
types = [KL_TYPE.K_DAY, KL_TYPE.K_30M, KL_TYPE.K_5M, KL_TYPE.K_1M]

for i, tab in enumerate(tabs):
    with tab:
        if st.button(f"点击分析 {tab.label}", key=f"btn_{i}"):
            with st.spinner(f"正在从富途提取 {tab.label} 数据..."):
                res = run_analysis(code_input, types[i])
                if isinstance(res, str): st.error(res)
                else: st.pyplot(res)