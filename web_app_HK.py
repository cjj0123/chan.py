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
# 🛑 1. 环境与依赖检查
# ==========================================
st.set_page_config(page_title="缠论多周期分析", layout="wide")

# 修复 DATA_SRC
try:
    from Common.CEnum import DATA_SRC
    if not hasattr(DATA_SRC, 'FUTU'):
        setattr(DATA_SRC, 'FUTU', 99)
except ImportError:
    st.error("❌ 无法导入 Common.CEnum")

# 检查 Futu
try:
    from futu import OpenQuoteContext, RET_OK, SubType, AuType
    HAS_FUTU = True
except ImportError:
    HAS_FUTU = False

# 导入核心
try:
    from Chan import CChan
    from ChanConfig import CChanConfig
    from Common.CEnum import AUTYPE, KL_TYPE
    # 尝试导入 K线单元类，这是迭代器必须返回的对象类型
    from KLine.KLine_Unit import CKLine_Unit
except ImportError as e:
    st.error(f"❌ 核心库导入失败: {e}")
    st.stop()


# ==========================================
# 🧩 2. 重写富途驱动 (适配 Iterator 模式)
# ==========================================

class CFutuDriver:
    
    #适配 Chan.py 的 DataAPI 接口规范 (修正版)
    
    def __init__(self, code, k_type=None, begin_date=None, end_date=None, autype=None):
        self.code = code
        self.k_type = k_type
        self.begin_date = begin_date
        self.end_date = end_date
        self.autype = autype
        self.klines = [] 
        self.iter_index = 0
        
        # 在实例初始化时即抓取数据
        self._fetch_data()

    @classmethod
    def do_init(cls):
        #框架在类层面调用的初始化，无需修改
        pass

    @classmethod
    def do_close(cls):
        #"""框架在类层面调用的清理，无需修改"""
        pass

    def _fetch_data(self):
        """原 do_init 中的逻辑搬迁至此"""
        if not HAS_FUTU:
            return

        # 1. 代码格式化
        futu_code = self.code
        if not futu_code.startswith("HK.") and not futu_code.startswith("US."):
             digits = re.findall(r'\d+', futu_code)
             if digits and len(digits[0]) == 5:
                 futu_code = "HK." + digits[0]

        # 2. 周期映射
        type_map = {
            KL_TYPE.K_DAY: 'K_DAY',
            KL_TYPE.K_1M:  'K_1M',
            KL_TYPE.K_5M:  'K_5M',
            KL_TYPE.K_30M: 'K_30M',
            KL_TYPE.K_60M: 'K_60M',
        }
        futu_ktype = type_map.get(self.k_type, 'K_DAY')

        # 3. 连接 OpenD
        try:
            ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            
            if self.k_type == KL_TYPE.K_DAY:
                ret, df, _ = ctx.request_history_kline(
                    futu_code, start=self.begin_date, end=self.end_date, 
                    ktype=futu_ktype, autype=AuType.QFQ
                )
            else:
                ctx.subscribe([futu_code], [SubType.K_1M, SubType.K_5M, SubType.K_30M])
                time.sleep(0.5)
                ret, df = ctx.get_cur_kline(futu_code, 1000, ktype=futu_ktype, autype=AuType.QFQ)

            ctx.close()

            if ret == RET_OK and not df.empty:
                for _, row in df.iterrows():
                    kl_dict = {
                        'time': row['time_key'],
                        'open': float(row['open']),
                        'close': float(row['close']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'volume': float(row['volume'])
                    }
                    self.klines.append(CKLine_Unit(kl_dict))

        except Exception as e:
            st.error(f"Futu 获取数据失败: {e}")

    def __iter__(self):
        self.iter_index = 0
        return self

    def __next__(self):
        if self.iter_index < len(self.klines):
            kl = self.klines[self.iter_index]
            self.iter_index += 1
            return kl
        else:
            raise StopIteration

# ==========================================
# 💉 3. 注入补丁 (Fix TypeError)
# ==========================================

_original_get_stock_api = CChan.GetStockAPI

def patched_get_stock_api(self):
    if self.data_src == DATA_SRC.FUTU:
        # 核心修正：这里返回 类本身 (CFutuDriver)，不要加括号 ()
        # Chan.py 内部会执行 CFutuDriver(code=..., k_type=...)
        return CFutuDriver 
    return _original_get_stock_api(self)

CChan.GetStockAPI = patched_get_stock_api
print("✅ 成功注入 Futu 驱动类")

# ==========================================
# 🚀 4. Streamlit 界面
# ==========================================
from Plot.PlotDriver import CPlotDriver

st.title("📈 缠论分析 (OpenD直连版)")

# --- 侧边栏 ---
st.sidebar.header("1. 股票设置")
code_input = st.sidebar.text_input("股票代码 (如 HK.00700)", "HK.00700")
long_begin_time = st.sidebar.text_input("开始时间", "2023-01-01")

st.sidebar.header("2. 指标开关")
show_bi = st.sidebar.checkbox("显示笔", True)
show_seg = st.sidebar.checkbox("显示线段", True)
show_zs = st.sidebar.checkbox("显示中枢", True)
show_bsp = st.sidebar.checkbox("显示买卖点", True)

# --- 运行逻辑 ---
def run_analysis(raw_code, lv_type):
    plt.clf(); plt.close('all')
    raw_code = raw_code.strip().upper()
    current_begin = long_begin_time
    
    # 默认 A股
    if hasattr(DATA_SRC, 'BAO_STOCK'): current_src = DATA_SRC.BAO_STOCK
    else: current_src = 0 
    clean_code = raw_code

    # 识别港股
    if "HK." in raw_code or (raw_code.isdigit() and len(raw_code)==5):
        current_src = DATA_SRC.FUTU
        if not raw_code.startswith("HK."): clean_code = f"HK.{raw_code}"
        # 港股分钟线只取最近
        if lv_type != KL_TYPE.K_DAY: 
            current_begin = (datetime.datetime.now() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
        st.info(f"🇭🇰 港股: {clean_code} | 源: OpenD")
    else:
        # A股处理
        digits = re.findall(r'\d+', raw_code)
        if digits:
            num = digits[0]
            clean_code = f"sh.{num}" if num.startswith("6") else f"sz.{num}"
        st.info(f"🇨🇳 A股: {clean_code} | 源: BaoStock")

    try:
        config = CChanConfig({"bi_strict": True, "zs_combine": True, "zs_algo": "normal"})
        plot_config = {"plot_kline": True, "plot_bi": show_bi, "plot_seg": show_seg, 
                       "plot_zs": show_zs, "plot_bsp": show_bsp, "plot_macd": True}
        plot_para = {"seg": {"width": 2, "color": "red"}, "bi": {"show_num": False}, "figure": {"w": 14, "h": 8}}

        chan = CChan(
            code=clean_code,
            begin_time=current_begin,
            end_time=datetime.datetime.now().strftime("%Y-%m-%d"),
            data_src=current_src,
            lv_list=[lv_type],
            config=config,
            autype=AUTYPE.QFQ
        )

        if not chan[lv_type]: return "❌ 数据为空，请检查代码或 OpenD 状态。"
        CPlotDriver(chan, plot_config=plot_config, plot_para=plot_para)
        return plt.gcf()

    except Exception as e:
        import traceback
        return f"运行错误: {str(e)}\n{traceback.format_exc()}"

# --- Tabs ---
tabs = st.tabs(["日线", "30分钟", "5分钟", "1分钟"])
types = [KL_TYPE.K_DAY, KL_TYPE.K_30M, KL_TYPE.K_5M, KL_TYPE.K_1M]

for i, tab in enumerate(tabs):
    with tab:
        if st.button(f"生成图表", key=f"btn_{i}"):
            res = run_analysis(code_input, types[i])
            if isinstance(res, str): st.error(res)
            else: st.pyplot(res)