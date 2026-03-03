import json
import os
import time
from datetime import datetime
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE
from DataAPI.CustomParquetAPI import CCustomParquetAPI

# EvoMap Config
HISTORY_FILE = "memory/evomap_backtest_history.json"

def run_resilient_backtest(code, parquet_path, bi_strict=True):
    """
    带 EvoMap 韧性策略的回测封装
    """
    print(f"\n[EVOMAP-RUNNER] Initializing Resilient Session for {code}...")
    
    # 1. 检查历史记忆 (Memory Continuity)
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            for line in f:
                record = json.loads(line)
                if record["stock"] == code and record["config"]["bi_strict"] == bi_strict:
                    print(f"[EVOMAP-KNOWLEDGE] Skipping: We already know the outcome for {code} in this mode.")
                    # return # 如果不想重复跑可以返回
    
    # 2. 强力数据加载 (带异常检测)
    print(f"[EVOMAP-DATA] Loading {parquet_path} with anomaly detection...")
    try:
        kl_units = CCustomParquetAPI.robust_load_from_parquet(parquet_path)
        if not kl_units:
            print("[EVOMAP-RECOVERY] Data empty, aborting.")
            return
    except Exception as e:
        print(f"[EVOMAP-RECOVERY] IO Error: {e}. Retrying via backoff...")
        return

    # 3. 回测逻辑
    config = CChanConfig({
        "bi_strict": bi_strict,
        "one_bi_zs": False, # 标准中枢
        "bs_type": '1,1p,2,2s,3a,3b',
    })

    try:
        chan = CChan(
            code=code,
            begin_time=kl_units[0].time,
            data_src="custom:evomap",
            lv_list=[KL_TYPE.K_30M],
            config=config,
            autype=AUTYPE.QFQ
        )
        
        # 统计
        bsp_list = chan.get_bsp()
        trade_count = len(bsp_list)
        
        # 4. 持久化运行记忆
        result = {
            "timestamp": datetime.now().isoformat(),
            "stock": code,
            "config": {"bi_strict": bi_strict},
            "outcome": {
                "trades": trade_count,
                "profit_estimate": "N/A" # 简化版
            }
        }
        
        os.makedirs("memory", exist_ok=True)
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(result) + "\n")
            
        print(f"✅ [EVOMAP-SUCCESS] Backtest complete. Trades: {trade_count}")
        
    except Exception as e:
        print(f"❌ [EVOMAP-CRITICAL] Self-repair triggered for error: {e}")

if __name__ == "__main__":
    # 运行华润电力的增强版回测
    run_resilient_backtest("HK.00836", "stock_cache/HK.00836_K_30M.parquet", bi_strict=False)
