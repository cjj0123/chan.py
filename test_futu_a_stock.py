#!/usr/bin/env python3
"""
测试 Futu A股数据源
"""

import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datetime import datetime, timedelta
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE

def test_futu_a_stock():
    """测试 Futu A股数据源"""
    print("🧪 测试 Futu A股数据源...")
    
    # 测试股票代码（平安银行）
    code = "000001"
    name = "平安银行"
    
    # 设置时间范围
    begin_time = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    end_time = datetime.now().strftime("%Y-%m-%d")
    
    # 配置缠论参数
    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": "1,1p,2,2s,3a,3b",
        "print_warning": False,
        "zs_algo": "normal",
    })
    
    try:
        print(f"🔍 正在获取 {code} {name} 的日线数据...")
        chan = CChan(
            code=code,
            begin_time=begin_time,
            end_time=end_time,
            data_src=DATA_SRC.FUTU,
            lv_list=[KL_TYPE.K_DAY],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        if len(chan[0]) > 0 and len(chan[0][-1]) > 0:
            print(f"✅ 日线数据获取成功！共 {len(chan[0][-1])} 根K线")
            last_klu = chan[0][-1][-1]
            print(f"   最新K线时间: {last_klu.time}")
            print(f"   最新收盘价: {last_klu.close}")
        else:
            print("❌ 日线数据为空")
            return False
            
        # 测试5分钟数据
        print(f"🔍 正在获取 {code} {name} 的5分钟数据...")
        chan_5m = CChan(
            code=code,
            begin_time=begin_time,
            end_time=end_time,
            data_src=DATA_SRC.FUTU,
            lv_list=[KL_TYPE.K_5M],
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        if len(chan_5m[0]) > 0 and len(chan_5m[0][-1]) > 0:
            print(f"✅ 5分钟数据获取成功！共 {len(chan_5m[0][-1])} 根K线")
            last_klu_5m = chan_5m[0][-1][-1]
            print(f"   最新5分钟K线时间: {last_klu_5m.time}")
            print(f"   最新5分钟收盘价: {last_klu_5m.close}")
        else:
            print("⚠️ 5分钟数据为空（可能是非交易时间）")
            
        print("🎉 Futu A股数据源测试完成！")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_futu_a_stock()
    if not success:
        sys.exit(1)