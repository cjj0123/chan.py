import logging
# 🔇 屏蔽 Streamlit 刷屏警告
logging.getLogger('streamlit.runtime.scriptrunner.script_run_context').setLevel(logging.ERROR)
logging.getLogger('streamlit.runtime.state.session_state_proxy').setLevel(logging.ERROR)

import streamlit as st
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import datetime as dt  # 给模块起个别名 dt，防止和类名 datetime 冲突
from datetime import datetime, date, timedelta
import re
import os
import pandas as pd 
import time
import sys
from Common.CTime import CTime

st.set_page_config(page_title="缠论Futu终极修复版v3", layout="wide")

# ==========================================
# 1. 核心依赖
# ==========================================
try:
    from Common.CEnum import DATA_SRC
except ImportError:
    class DATA_SRC:
        FUTU = 99
        BAO_STOCK = 0
if not hasattr(DATA_SRC, 'FUTU'): setattr(DATA_SRC, 'FUTU', 99)

try:
    from Chan import CChan
    from ChanConfig import CChanConfig
    from Common.CEnum import AUTYPE, KL_TYPE
    from KLine.KLine_Unit import CKLine_Unit
    from Plot.PlotDriver import CPlotDriver
    try:
        from CustomBuySellPoint.CustomStrategy import CCustomStrategy
        HAS_STRATEGY = True
    except ImportError:
        HAS_STRATEGY = False
except ImportError:
    st.error("核心库缺失")
    st.stop()

try:
    from futu import OpenQuoteContext, RET_OK, SubType, AuType
    HAS_FUTU = True
except ImportError:
    HAS_FUTU = False

try:
    from Common.CEnum import DATA_FIELD
except ImportError:
    # Fallback if the enum is inaccessible
    class DATA_FIELD:
        FIELD_TIME = "time_key"
        FIELD_OPEN = "open"
        FIELD_HIGH = "high"
        FIELD_LOW = "low"
        FIELD_CLOSE = "close"
        FIELD_VOLUME = "volume"

# ==========================================
# 2. 驱动类 (纯离线模式：只读硬盘)
# ==========================================

class CFutuStockDriver_V3:
    def __init__(self, code, k_type=None, begin_date=None, end_date=None, autype=None):
        self.code = code
        self.k_type = k_type
        self.begin_date = begin_date
        self.klines = []
        
        lv_str = str(k_type).split('.')[-1]
        self.cache_file = f"stock_cache/{self.code}_{lv_str}.parquet"
        
        self._load_offline_data()

    def _load_offline_data(self):
        if os.path.exists(self.cache_file):
            df = pd.read_parquet(self.cache_file)
            self._convert_to_units(df)
        else:
            st.error(f"本地无数据，请先在左侧点击『同步数据』: {self.cache_file}")

    def _convert_to_units(self, df):
        # 确保时间戳是字符串方便对比
        start_ts = str(self.begin_date) if self.begin_date else ""
        
        # 缠论引擎要求的字段转换
        for _, row in df.iterrows():
            time_str = str(row['time_key'])
            # 过滤：只加载指定日期之后的数据
            if start_ts and time_str < start_ts:
                continue
                
            time_parts = [int(n) for n in re.findall(r'\d+', time_str)]
            while len(time_parts) < 5: time_parts.append(0)
            
            unit = CKLine_Unit({
                DATA_FIELD.FIELD_TIME: CTime(*(time_parts[:5])),
                DATA_FIELD.FIELD_OPEN: float(row['open']), 
                DATA_FIELD.FIELD_HIGH: float(row['high']), 
                DATA_FIELD.FIELD_LOW: float(row['low']),
                DATA_FIELD.FIELD_CLOSE: float(row['close']),
                DATA_FIELD.FIELD_VOLUME: float(row.get('volume', 0))
            })
            self.klines.append(unit)

    @classmethod
    def do_init(cls): pass
    @classmethod
    def do_close(cls): pass
    def get_kl_data(self): return self.klines

# ==========================================
# 3. 全局数据同步工具 (联网部分)
# ==========================================

def sync_data_from_futu(code, lv_list):
    """循环分页抓取并持久化"""
    if not HAS_FUTU:
        st.error("未安装 futu-api")
        return

    if not os.path.exists("stock_cache"):
        os.makedirs("stock_cache")

    f_ktype_map = {
        KL_TYPE.K_DAY: "K_DAY",
        KL_TYPE.K_60M: "K_60M",
        KL_TYPE.K_30M: "K_30M",
        KL_TYPE.K_5M: "K_5M",
        KL_TYPE.K_1M: "K_1M",
    }
    
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        for lv in lv_list:
            # ✅ 1. 获取对应的 Futu 字符串类型
            f_ktype = f_ktype_map.get(lv)
            if not f_ktype:
                st.warning(f"跳过不支持的级别: {lv}")
                continue

            lv_str = str(lv).split('.')[-1]
            cache_file = f"stock_cache/{code}_{lv_str}.parquet"
            
            fetch_start = "2023-01-01" 
            df_old = pd.DataFrame() # 预设旧数据为空
            
            if os.path.exists(cache_file):
                try:
                    df_old = pd.read_parquet(cache_file)
                    if not df_old.empty:
                        fetch_start = df_old['time_key'].max().split(' ')[0]
                except Exception as e:
                    st.warning(f"读取旧缓存失败: {e}")
            
            fetch_end = date.today().strftime("%Y-%m-%d")

            # ✅ 2. 初始化本次抓取的容器
            all_new_dfs = []
            page_req_key = None
            
            st.write(f"正在同步 {lv_str} ({fetch_start} -> {fetch_end})...")

            # --- 分页抓取循环 ---
            while True:
                ret, df_new, page_req_key = ctx.request_history_kline(
                    code, 
                    start=fetch_start,
                    end=fetch_end, 
                    ktype=f_ktype,  # ✅ 现在这里有值了
                    autype=AuType.QFQ, 
                    max_count=1000, 
                    page_req_key=page_req_key
                )
                
                if ret == RET_OK:
                    if not df_new.empty:
                        all_new_dfs.append(df_new)
                    # ✅ 3. 必须判断如果没有下一页了，跳出 while 循环
                    if page_req_key is None:
                        break
                else:
                    st.error(f"Futu 接口报错: {df_new}")
                    break
            
            # ✅ 4. 合并与保存逻辑
            if all_new_dfs:
                df_new_total = pd.concat(all_new_dfs, ignore_index=True)
                df_new_total['time_key'] = df_new_total['time_key'].astype(str)
                
                # 合并旧数据并去重
                df_final = pd.concat([df_old, df_new_total], ignore_index=True)
                df_final.drop_duplicates('time_key', keep='last', inplace=True)
                df_final.sort_values('time_key', inplace=True)
                
                df_final.to_parquet(cache_file, engine='pyarrow')
                st.success(f"✅ {lv_str} 同步成功，总计 {len(df_final)} 根")
            else:
                st.info(f"ℹ️ {lv_str} 已经是最新，无需更新。")

    finally:
        ctx.close()
    st.balloons()
# ==========================================
# 4. 分析引擎包装
# ==========================================

def run_analysis(code, lv, start_date, end_date):
    # 标准区间套对应关系
    LV_HIERARCHY = {
        KL_TYPE.K_DAY: [KL_TYPE.K_DAY, KL_TYPE.K_30M],   # 日线下级是 30分
        KL_TYPE.K_30M: [KL_TYPE.K_30M, KL_TYPE.K_5M],    # 30线下级是 5分
        KL_TYPE.K_5M:  [KL_TYPE.K_5M,  KL_TYPE.K_1M],    # 5线下级是 1分
        KL_TYPE.K_1M:  [KL_TYPE.K_1M],                   # 1分没有下级
    }
    config = CChanConfig() # 可根据需要调整配置
    # ✅ 核心修复：根据当前级别获取标准的区间套层级
    target_lv_list = LV_HIERARCHY.get(lv, [lv])
    try:
        chan = CChan(
            code=code,
            begin_time=start_date.strftime("%Y-%m-%d"),
            end_time=end_date.strftime("%Y-%m-%d"),
            data_src=DATA_SRC.FUTU, # 补丁会将其指向离线驱动
            lv_list=target_lv_list,  # ✅ 使用动态层级
            config=config,
            autype=AUTYPE.QFQ
        )
        
        plot_driver = CPlotDriver(chan, plot_config={"plot_kline": True, "plot_bi": True, "plot_zs": True, "plot_bsp": True}, 
                                 plot_para={"figure": {"w": 14, "h": 8}, "max_kl_count": 400})
        return plot_driver.figure
    except Exception as e:
        return f"分析出错: {str(e)}"

# ==========================================
# 5. UI 布局
# ==========================================

# 强力注入补丁
CChan.GetStockAPI = lambda self: CFutuStockDriver_V3 if self.data_src == DATA_SRC.FUTU else _original_get_stock_api(self)

with st.sidebar:
    st.header("⚙️ 数据中心")
    code_input = st.text_input("股票代码", value="HK.00700")
    if st.button("🔄 同步云端数据", use_container_width=True):
        sync_data_from_futu(code_input, [KL_TYPE.K_DAY, KL_TYPE.K_30M, KL_TYPE.K_5M, KL_TYPE.K_1M])
    
    st.divider()
    st.header("📅 时间范围")
    start_d = st.date_input("开始日期", value=date.today() - timedelta(days=120))
    end_d = st.date_input("结束日期", value=date.today())

# 主界面 Tabs
tabs = st.tabs(["日线", "30分钟", "5分钟", "1分钟"])
types = [KL_TYPE.K_DAY, KL_TYPE.K_30M, KL_TYPE.K_5M, KL_TYPE.K_1M]

for i, tab in enumerate(tabs):
    with tab:
        if st.button(f"运行 {tab.label} 分析", key=f"btn_{i}"):
            with st.spinner("正在离线计算缠论数据..."):
                fig = run_analysis(code_input, types[i], start_d, end_d)
                if isinstance(fig, str): st.error(fig)
                else: st.pyplot(fig)