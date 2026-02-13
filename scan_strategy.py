import os
import glob
import pandas as pd
from datetime import datetime
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE
from web_app_qjtFUTU import CFutuStockDriver_V3 

def run_offline_scanner():
    # --- 1. 时间窗口设置 ---
    SEARCH_START = "2026-02-01 09:30:00" 
    SEARCH_END   = "2026-02-12 16:00:00"
    start_dt = datetime.strptime(SEARCH_START, "%Y-%m-%d %H:%M:%S")
    end_dt   = datetime.strptime(SEARCH_END, "%Y-%m-%d %H:%M:%S")

    SCAN_LEVEL = KL_TYPE.K_5M
    # ⚠️ 请确保这个路径相对于你运行脚本的位置是正确的
    CACHE_DIR = os.path.join(os.getcwd(), "stock_cache") 
    VALID_STOCKS = []
    
    print(f"🚀 扫描器启动...")
    print(f"当前工作目录: {os.getcwd()}")
    print(f"检查缓存目录: {CACHE_DIR} (是否存在: {os.path.exists(CACHE_DIR)})")

    # --- 2. 这里的匹配逻辑要非常鲁棒 ---
    # 尝试匹配所有包含 K_5M 的 parquet 文件
    search_pattern = os.path.join(CACHE_DIR, "*.parquet")
    all_files = glob.glob(search_pattern)
    
    # 过滤出符合级别的标的
    cache_files = [f for f in all_files if SCAN_LEVEL.name in f]
    
    print(f"📂 目录内文件总数: {len(all_files)} | 匹配 {SCAN_LEVEL.name} 级别的标的数: {len(cache_files)}")

    if not cache_files:
        print("❌ 错误：未找到任何可扫描的缓存文件！请检查 stock_cache 文件夹内的文件名。")
        return
    
    # --- 🔥 核心配置修正：必须在这里打开开关 ---
    config = CChanConfig()
    config.bs_type = '1,2,3a,3b'    # 必须明确指定
    config.zs_algo = 'normal'       # 笔中枢，确保 5M 级别有足够的信号源
    config.bi_strict = True         # 保持默认的笔严谨度
    
    # 🌟 关键：指定计算哪些买卖点
    # 1=一买, 2=二买, 3a=中枢破坏三买, 3b=中枢回踩三买
    config.bs_type = '1,1p,2,2s,3a,3b' 
    
    # 🌟 关键：中枢算法
    # 'normal' = 标准笔中枢 (建议5分钟级别用这个，信号多)
    # 'segment' = 线段中枢 (如果你想看大级别的三买，用这个，但信号会少)
    config.zs_algo = 'normal'  
    
    # 笔的严格程度
    config.bi_strict = True # 也可以设为 False 试试，False 信号更多

    # ... 进入循环 ...
    for file_path in cache_files:
        filename = os.path.basename(file_path)
        code = filename.split(f"_{SCAN_LEVEL.name}")[0]
        
        try:
            chan = CChan(
                code=code,
                begin_time="2024-01-01", 
                data_src=DATA_SRC.FUTU,
                lv_list=[SCAN_LEVEL],
                config=config,
                autype=AUTYPE.QFQ
            )

            mg_data = chan[SCAN_LEVEL]
            
            # --- 1. 强制触发全量计算 (包含买卖点) ---
            if hasattr(mg_data, 'cal_seg_and_zs'):
                mg_data.cal_seg_and_zs()
            if hasattr(mg_data, 'cal_bs_point'):
                mg_data.cal_bs_point()

            # --- 2. 信号提取：全量属性扫描 ---
            bsp_obj = mg_data.bs_point_lst
            actual_list = []
            
            # 自动探测真正存放信号的列表
            for attr in ['items', 'lst', 'points', 'bsp_list']:
                if hasattr(bsp_obj, attr):
                    val = getattr(bsp_obj, attr)
                    actual_list = val() if callable(val) else val
                    if actual_list: break
            
            # 如果还是空，尝试从对象的内部字典暴力翻找第一个 list
            if not actual_list:
                for v in bsp_obj.__dict__.values():
                    if isinstance(v, list) and len(v) > 0:
                        actual_list = v
                        break

            # --- 3. 结果打印 ---
            bi_cnt = len(mg_data.bi_list)
            zs_cnt = len(mg_data.zs_list)
            print(f"[{code}] ✅ 加载:K线={len(mg_data.lst):<5} | 笔={bi_cnt:<3} | 中枢={zs_cnt:<2} | 信号={len(actual_list)}")
            
            latest_signals = actual_list[-5:]  # 只看最近的几个信号，避免过多历史干扰
            # --- 4. 终极修正判定 (解决 CKLine 属性报错) ---
            last_kl = mg_data.lst[-1]
            # 探测最后一根K线的时间
            now_time = getattr(last_kl, 'date', getattr(last_kl, 'time', "Unknown"))
            
            # --- 实验：暂时放宽条件，看能不能抓到二买或一买 ---
            for bsp in latest_signals:
                bsp_type = bsp.type2str()
                dist = abs(len(mg_data.lst) - bsp.klu.idx)
                
                # 判定：将 "3" 改为 "2" 或 "1"，看看能不能出结果
                if bsp.is_buy and ("1" in bsp_type or "2" in bsp_type):
                    if dist < 500: # 搜索最近 3 天
                        bsp_time = getattr(bsp.klu, 'date', "N/A")
                        print(f" 🔥【命中信号】{code} | 类型:{bsp_type:<3} | 距今:{dist}线")
                        VALID_STOCKS.append({"code": code, "type": bsp_type})
                        break
            

        except Exception as e:
            print(f" ❌ {code} 运行出错: {e}")

    print(f"🚀 扫描完成！共发现 {len(VALID_STOCKS)} 个符合条件的标的。")

if __name__ == "__main__":
    run_offline_scanner() 