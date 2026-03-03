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
    SEARCH_END   = "2026-02-13 11:30:00"
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
    #config.bs_type = '1,2,3a,3b'    # 必须明确指定
    config.zs_algo = 'normal'       # 笔中枢，确保 5M 级别有足够的信号源
    config.bi_strict = True         # 保持默认的笔严谨度
    
    # 🌟 关键：指定计算哪些买卖点
    # 1=一买, 2=二买, 3a=中枢破坏三买, 3b=中枢回踩三买
    config.bs_type = '1,1p,2,2s,3a,3b' 
    
    # 🌟 关键：中枢算法
    # 'normal' = 标准笔中枢 (建议5分钟级别用这个，信号多)
    # 'segment' = 线段中枢 (如果你想看大级别的三买，用这个，但信号会少)
    # config.zs_algo = 'normal'  
    
    # 笔的严格程度
    #config.bi_strict = True # 也可以设为 False 试试，False 信号更多

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
            # print(f"[{code}] ✅ 加载:K线={len(mg_data.lst):<5} | 笔={bi_cnt:<3} | 中枢={zs_cnt:<2} | 信号={len(actual_list)}")
            
            # === 🛠️ 最终修正版：使用索引计算距离 (修复 CKLine 属性错误) ===
            
            if not actual_list:
                continue

            # 获取当前最后一根原始K线 (这是修正报错的关键)
            # mg_data[-1] 是合并K线(CKLine)，它包含了一个原始K线列表 .lst
            # 我们取 .lst[-1] 拿到真正的最后一根原始K线(CKLine_Unit)
            try:
                last_klu = mg_data[-1].lst[-1]
            except AttributeError:
                # 兼容性处理：如果 .lst 属性不对，尝试打印属性帮助调试
                print(f"⚠️ 无法读取K线内部列表，对象属性: {dir(mg_data[-1])}")
                continue

            # 倒序遍历最后 3 个信号
            for bsp in reversed(actual_list[-3:]):
                # 1. 计算距离 (用最新K线的索引 - 信号K线的索引)
                # 这样得到的 dist 就是“信号发生在多少根K线之前”
                current_idx = last_klu.idx
                signal_idx = bsp.klu.idx
                dist = current_idx - signal_idx
                
                # 2. 获取时间用于显示 (手动解析 CTime)
                t = bsp.klu.time
                bsp_time_str = f"{t.year}-{t.month:02d}-{t.day:02d} {t.hour:02d}:{t.minute:02d}"
                
                bsp_type = bsp.type2str()
                
                # 3. 判定条件：
                # (1) 必须是买点
                # (2) 允许 1类/2类/3类
                # (3) 必须是最近 100 根K线内的
                if bsp.is_buy and dist <= 1000: 
                    
                    print(f" 🔥🔥🔥【命中信号】{code} | 类型:{bsp_type} | 时间:{bsp_time_str}")
                    
                    VALID_STOCKS.append({
                        "code": code,
                        "name": code, 
                        "type": bsp_type,
                        # 🛠️ 修复点：改用 bsp.klu.close 获取信号当根K线的收盘价
                        "price": bsp.klu.close, 
                        "time": bsp_time_str
                    })
                    break # 找到一个就退出，避免重复
        except Exception as e:
            print(f" ❌ {code} 运行出错: {e}")
            
    print("-" * 30)
    print(f"🚀 扫描完成！共发现 {len(VALID_STOCKS)} 个符合条件的标的。")

    if len(VALID_STOCKS) > 0:
        try:
            # 1. 将结果列表转换为 DataFrame
            df_result = pd.DataFrame(VALID_STOCKS)

            # 2. 整理列顺序 (确保 code, type, time 在前，price/name 在后)
            # 自动匹配您之前 append 进去的 key
            desired_order = ['code', 'type', 'time', 'price']
            # 过滤出实际存在的列，防止 key 不匹配报错
            final_cols = [c for c in desired_order if c in df_result.columns]
            df_result = df_result[final_cols]

            # 3. 构造文件名 (包含时间戳，避免覆盖)
            # 格式: scan_result_YYYYMMDD_HHMMSS.parquet
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"scan_result_{timestamp}.parquet"
            
            # 确保保存到 stock_cache 目录 (复用您脚本开头的 cache_dir 变量，或者硬编码)
            save_dir = "stock_cache"
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
            
            file_path = os.path.join(save_dir, file_name)

            # 4. 保存为 Parquet 文件
            # engine='auto' 会自动选择 pyarrow 或 fastparquet
            df_result.to_parquet(file_path, engine='auto', index=False)

            print(f"💾 结果已保存至: {file_path}")
            print(f"📄 数据预览:\n{df_result.head(3).to_string(index=False)}")

        except ImportError:
            print("❌ 保存失败: 缺少依赖库。请运行 pip install pyarrow 或 pip install fastparquet")
        except Exception as e:
            print(f"❌ 保存文件时发生错误: {e}")
    else:
        print("⚠️ 结果列表为空，未生成文件。")

if __name__ == "__main__":
    run_offline_scanner() 