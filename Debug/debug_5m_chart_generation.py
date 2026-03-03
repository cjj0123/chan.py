#!/usr/bin/env python3
"""
诊断脚本：验证5分钟图表生成
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from futu_hk_visual_trading_fixed import FutuHKVisualTrading
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
import datetime

def test_5m_chart_generation():
    """测试5分钟图表生成"""
    trader = FutuHKVisualTrading(dry_run=True)
    
    # 测试股票
    test_code = "HK.00700"
    
    print(f"测试股票: {test_code}")
    
    # 获取30M和5M数据
    end_time = datetime.datetime.now()
    start_time = end_time - datetime.timedelta(days=30)
    
    try:
        # 尝试获取多级别数据
        chan_multi_level = CChan(
            code=test_code,
            begin_time=start_time.strftime("%Y-%m-%d"),
            end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
            data_src=DATA_SRC.FUTU,
            lv_list=[KL_TYPE.K_30M, KL_TYPE.K_5M],
            config=CChanConfig({})
        )
        
        print(f"原始级别列表: {[lv.name for lv in chan_multi_level.lv_list]}")
        
        # 检查每个级别的K线数量
        for lv in chan_multi_level.lv_list:
            kline_count = 0
            for _ in chan_multi_level[lv].klu_iter():
                kline_count += 1
            print(f"{lv.name}: {kline_count} 根K线")
        
        # 尝试生成图表
        chart_paths = trader.generate_charts(test_code, chan_multi_level)
        print(f"生成的图表路径: {chart_paths}")
        
        # 检查是否包含5M图表
        has_5m_chart = any('5M' in path for path in chart_paths)
        has_30m_chart = any('30M' in path for path in chart_paths)
        
        print(f"包含5M图表: {has_5m_chart}")
        print(f"包含30M图表: {has_30m_chart}")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        trader.close_connections()

if __name__ == "__main__":
    test_5m_chart_generation()