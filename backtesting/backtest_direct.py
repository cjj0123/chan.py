import os
import glob
import pandas as pd
from datetime import datetime
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

# ==============================================================================
# 1. 强力数据加载器 (修复了 AttributeError)
# ==============================================================================
def force_load_data(code, kl_type: KL_TYPE):
    """
    不管三七二十一，直接从 stock_cache 读文件
    """
    # 1. 构造可能的路径 (兼容不同的命名习惯)
    kl_type_str = kl_type.name.lower() # 例如 K_30M -> k_30m (确保包含 'k_')
    possible_paths = [
        f"stock_cache/{code}_{kl_type_str}.parquet",
        f"stock_cache/{code.replace('.', '')}_{kl_type_str}.parquet", 
        f"stock_cache/{code}_{kl_type_str}.csv" 
    ]
    
    file_path = None
    for p in possible_paths:
        if os.path.exists(p):
            file_path = p
            break
            
    if not file_path:
        print(f"   ❌ [严重] 找不到行情文件! 请检查 stock_cache 下是否有 {code} 的数据")
        print(f"      尝试过的路径: {possible_paths}")
        return None

    print(f"   ✅ [1/4] 找到文件: {file_path}")

    # 2. 读取数据
    try:
        df = pd.read_parquet(file_path)
    except:
        print("      parquet读取失败，尝试csv...")
        try:
            df = pd.read_csv(file_path)
        except:
            print("      ❌ 文件无法读取")
            return None

    # 3. 格式化列名
    df.columns = [c.lower() for c in df.columns]
    col_map = {'time_key': 'time', 'code': 'code', 'vol': 'volume', 'amount': 'turnover'}
    df.rename(columns=col_map, inplace=True)
    df.sort_values("time", inplace=True)
    
    # 4. 转换为 CChan 需要的 K线对象
    klu_list = []
    for _, row in df.iterrows():
        raw_time = str(row['time'])
        try:
            if len(raw_time) > 16:
                dt = datetime.strptime(raw_time[:19], "%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M")
        except:
            dt = pd.to_datetime(raw_time).to_pydatetime()

        final_time = CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
        
        item_dict = {
            DATA_FIELD.FIELD_TIME: final_time,
            DATA_FIELD.FIELD_OPEN: float(row['open']),
            DATA_FIELD.FIELD_HIGH: float(row['high']),
            DATA_FIELD.FIELD_LOW: float(row['low']),
            DATA_FIELD.FIELD_CLOSE: float(row['close']),
            DATA_FIELD.FIELD_VOLUME: float(row.get('volume', 0.0)),
            DATA_FIELD.FIELD_TURNOVER: float(row.get('turnover', 0.0)),
            DATA_FIELD.FIELD_TURNRATE: 0.0
        }
        klu_list.append(CKLine_Unit(item_dict))
    
    if len(klu_list) > 0:
        print(f"   ✅ [2/4] 数据转换成功: 共 {len(klu_list)} 根K线")
        # 🛠️ 修复点：添加  来访问列表的第一个元素
        print(f"      数据范围: {klu_list[0].time} -> {klu_list[-1].time}")
    else:
        print("   ❌ [严重] 文件为空或转换失败")
        
    return klu_list


# ==============================================================================
# 2. 回测主程序
# ==============================================================================
def main():
    # 1. 找扫描结果文件
    files = glob.glob("stock_cache/scan_result_*.parquet")
    if not files:
        print("❌ 没找到 stock_cache/scan_result_xxxx.parquet 文件")
        return
    
    signal_file = max(files, key=os.path.getctime)
    print(f"🚀 读取扫描信号: {signal_file}")
    df_signals = pd.read_parquet(signal_file)
    print(f"📊 待回测信号数: {len(df_signals)}")

    # 2. 遍历回测
    for idx, row in df_signals.iterrows():
        code = row['code']
        # 统一去除毫秒/秒，确保格式一致 (如 2026-02-11 10:15)
        target_time = str(row['time'])[:16] 
        
        print("\n" + "="*60)
        print(f"⚡ 正在处理: {code} | 寻找买点时间: [{target_time}]")
        
        # --- 步骤A: 加载数据 ---
        kl_units = force_load_data(code)
        if not kl_units: continue

        # --- 步骤B: 启动缠论计算 (强力修复版) ---
        print("   ⏳ [3/4] 正在计算缠论结构 (请稍候)...")
        
        # 确保 config 里的参数不会过滤掉所有数据
        config = CChanConfig({
            "bi_strict": True,
            "trigger_step": False, 
            "skip_step": 0,
            "bs_type": '1,1p,2,2s,3a,3b',
            "print_warning": True, # 开启警告，看看控制台报错
        })

        try:
            chan = CChan(
                code=code,
                begin_time="",     # 尝试传空字符串或完全不传
                data_src="custom", # 这里的 data_src 有时必须匹配
                lv_list=[KL_TYPE.K_5M],
                config=config,
                ext_klu={KL_TYPE.K_5M: kl_units} # 确保 kl_units 是 list
            )
            
            # 立即检查计算结果
            if len(chan[0]) == 0:
                print("      ❌ 警告：CChan 计算结果为空！正在尝试强制重新加载...")
                # 备选方案：如果 ext_klu 不行，尝试用最原始的 data_src 逻辑
        except Exception as e:
            print(f"   ❌ CChan 初始化失败: {e}")
            continue
        # 显式指定从第一根 K 线开始算，确保 49623 索引被包含
        first_k_time = kl_units[0].time
        try:
            chan = CChan(
                code=code,
                begin_time=first_k_time, 
                end_time=None,
                data_src="custom:local", 
                lv_list=[KL_TYPE.K_5M],
                config=config,
                autype=AUTYPE.QFQ,
                # 🔥 核心：直接把洗好的数据塞进去
                # ext_klu={KL_TYPE.K_5M: kl_units} 
            )
        except Exception as e:
            print(f"   ❌ CChan 初始化失败: {e}")
            continue
        print(f"      DEBUG: chan[0] 类型: {type(chan[0])} | 长度: {len(chan[0])}")
        # --- 步骤C: 定位与分析 ---
        print(f"   ▶️  [4/4] 正在定位信号点...")
        
        target_dt = pd.to_datetime(target_time.replace("/", "-"))
        matched_idx = -1
        
        # 1. 在原始数据中快速定位索引
        for i, klu in enumerate(kl_units):
            klu_dt = pd.to_datetime(str(klu.time).replace("/", "-"))
            if klu_dt >= target_dt:
                if (klu_dt - target_dt).total_seconds() <= 600:
                    matched_idx = i
                    print(f"      ✅ 成功定位 K 线索引: {i} | 时间: {klu_dt} | 价格: {klu.close}")
                break
        
        if matched_idx == -1:
            print(f"      ❌ 在原始数据中未找到匹配时间点")
            continue

        # --- 步骤C: 定位与分析 ---
        # ... (之前的定位 matched_idx 代码保持不变) ...

        print(f"      ⏳ 正在扫描后续卖点 (索引锚定模式)...")
        try:
            level_obj = chan[0]
            buy_price = kl_units[matched_idx].close
            target_idx = matched_idx # 原始数据的索引 49623
            
            # 1. 寻找锚点：在缠论对象中找到原始索引为 target_idx 的位置
            start_search_idx = -1
            actual_len = len(level_obj)
            
            # 缠论 K 线通常有一个 klu 属性指向原始单元，或者本身有 idx 属性
            for i in range(actual_len - 1, -1, -1):
                # 探测 idx 属性，不同版本可能在不同位置
                curr_k = level_obj[i]
                curr_idx = getattr(curr_k, 'idx', -1)
                
                if curr_idx == target_idx:
                    start_search_idx = i
                    break
            
            # 如果没找到 idx 属性，退而求其次用“倒数”逻辑
            # 如果原始数据最后一条是 49938，信号是 49623，说明是倒数第 315 条
            if start_search_idx == -1:
                offset = len(kl_units) - 1 - target_idx
                start_search_idx = actual_len - 1 - offset
                if start_search_idx < 0: start_search_idx = -1

            if start_search_idx == -1 or start_search_idx >= actual_len:
                print(f"      ❌ 错误：缠论计算对象长度({actual_len})不足以覆盖信号点")
                continue

            print(f"      📍 锚定成功，从缠论序列位置 {start_search_idx} 开始回测...")

            # 2. 执行回测
            found_exit = False
            for i in range(start_search_idx, actual_len):
                klu = level_obj[i]
                profit = (klu.close - buy_price) / buy_price * 100
                
                # 检查卖点
                bsps = getattr(klu, 'bs_point', [])
                if bsps:
                    for bsp in bsps:
                        is_buy = bsp.is_buy() if callable(bsp.is_buy) else bsp.is_buy
                        if not is_buy:
                            print(f"      🟢 【缠论卖点出场】 类型: {bsp.type2str()} | 时间: {klu.time} | 盈亏: {profit:.2f}%")
                            found_exit = True
                            break
                if found_exit: break
                
                if profit < -5.0:
                    print(f"      🟢 【止损出场】 时间: {klu.time} | 盈亏: {profit:.2f}%")
                    found_exit = True
                    break

            if not found_exit:
                last_k = level_obj[-1]
                print(f"      ℹ️  提示: 持仓中。最新: {last_k.time} | 盈亏: {((last_k.close-buy_price)/buy_price*100):.2f}%")

        except Exception as e:
            print(f"      ❌ 提取分析失败: {e}")

if __name__ == "__main__":
    main()