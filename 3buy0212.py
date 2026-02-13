import os
import glob
import pandas as pd
from datetime import datetime
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import DATA_SRC, KL_TYPE, AUTYPE
from web_app_qjtFUTU import CFutuStockDriver_V3 

def run_offline_scanner():
    # --- 配置区 ---
    SCAN_LEVEL = KL_TYPE.K_5M
    CACHE_DIR = os.path.join(os.getcwd(), "stock_cache")
    MAX_DIST = 4000  # 只看最近 400 根线（约 2-3 个交易日）内的信号
    
    # 核心缠论配置：更灵敏的信号捕获
    config = CChanConfig()
    config.bs_type = '1,1p,2,2s,3a,3b' 
    config.zs_algo = 'normal'  # 笔中枢
    config.bi_strict = False   # 适度放宽笔的要求，增加信号产出
    
    print(f"{"="*60}\n🚀 缠论雷达启动 | 目标级别: {SCAN_LEVEL.name} | 模式: 离线扫描\n{"="*60}")

    search_pattern = os.path.join(CACHE_DIR, f"*{SCAN_LEVEL.name}*.parquet")
    cache_files = glob.glob(search_pattern)
    
    if not cache_files:
        print(f"❌ 错误：在 {CACHE_DIR} 未找到缓存文件！")
        return

    print(f"🔍 正在扫描 {len(cache_files)} 个标的...\n")
    print(f"{"代码":<10} | {"状态":<6} | {"最近信号":<6} | {"距今(线)":<8} | {"触发时间"}")
    print("-" * 70)

    results = []

    for file_path in cache_files:
        code = os.path.basename(file_path).split(f"_{SCAN_LEVEL.name}")[0]
        
        try:
            # 1. 实例化引擎
            chan = CChan(
                code=code, begin_time="2024-01-01", 
                data_src=DATA_SRC.FUTU, 
                lv_list=[SCAN_LEVEL],
                config=config, autype=AUTYPE.QFQ
            )
            mg_data = chan[SCAN_LEVEL]
            
            # 2. 提取信号列表
            bsp_obj = mg_data.bs_point_lst
            actual_list = []
            for attr in ['items', 'lst', 'points']:
                if hasattr(bsp_obj, attr):
                    val = getattr(bsp_obj, attr)
                    actual_list = val() if callable(val) else val
                    if actual_list: break
            
            if not actual_list:
                print(f"{code:<10} | ✅ OK   | {"无":<8} | {"-":<9} | -")
                continue

            # 3. 信号按时间倒序排（优先看最新的）
            latest_signals = sorted(actual_list, key=lambda x: x.klu.idx, reverse=True)
            
            found_target = None
            for bsp in latest_signals:
                bsp_type = bsp.type2str()
                dist = len(mg_data.lst) - bsp.klu.idx
                
                # 时间戳兼容性提取
                target_klu = bsp.klu
                bsp_time = getattr(target_klu, 'date', getattr(target_klu, 'time', "N/A"))
                if bsp_time == "N/A" and hasattr(target_klu, 'klu_list'):
                    bsp_time = target_klu.klu_list[-1].time

                # 4. 判定逻辑：优先找三买，其次二买
                if bsp.is_buy and dist <= MAX_DIST:
                    if "3" in bsp_type: # 完美目标
                        found_target = (bsp_type, dist, bsp_time, "🔥")
                        break 
                    elif "2" in bsp_type and not found_target: # 次优目标
                        found_target = (bsp_type, dist, bsp_time, "✨")
                    elif "1" in bsp_type and not found_target: # 底部信号
                        found_target = (bsp_type, dist, bsp_time, "🔍")

            if found_target:
                tag, d, t, icon = found_target
                print(f"{code:<10} | {icon} 发现 | {tag:<8} | {d:<9} | {t}")
                results.append({"code": code, "type": tag, "dist": d, "time": t})
            else:
                print(f"{code:<10} | ✅ OK   | {"过期":<8} | {"-":<9} | -")

        except Exception as e:
            # 优化报错显示，只看关键信息
            err_msg = str(e).split('\n')[0]
            print(f"{code:<10} | ❌ 出错 | {err_msg[:30]}")

    print(f"\n{"="*60}")
    print(f"✅ 扫描结束！命中总数: {len(results)}")
    if results:
        print(f"建议重点关注: {[r['code'] for r in results if '3' in r['type']]}")
    print(f"{"="*60}")

if __name__ == "__main__":
    run_offline_scanner()