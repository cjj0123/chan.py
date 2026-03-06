#!/usr/bin/env python3
"""
最终测试：验证x_range设置是否正确
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Common.CEnum import KL_TYPE
from Chan import CChan
from ChanConfig import CChanConfig
from Plot.PlotDriver import CPlotDriver
import matplotlib.pyplot as plt

def test_xrange_correctness():
    """测试x_range设置的正确性"""
    # 使用有完整数据的股票
    test_code = "HK.00700"
    
    # 测试30分钟级别（数据完整）
    print("测试30分钟级别...")
    try:
        chan_config = CChanConfig({
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
        
        chan = CChan(
            code=test_code,
            begin_time="2023-01-01",
            end_time=None,
            data_src="custom:SQLiteAPI.SQLiteAPI",
            lv_list=[KL_TYPE.K_30M],
            config=chan_config
        )
        
        total_klines = len(chan[0])
        print(f"总K线数: {total_klines}")
        print(f"最新日期: {chan[0][-1].time.to_str()}")
        
        # 测试x_range=150
        plot_para = {
            "figure": {
                "x_range": 150,
                "w": 12,
                "h": 6,
            }
        }
        
        plot_driver = CPlotDriver(chan, plot_config="kline", plot_para=plot_para)
        ax = plot_driver.figure.axes[0]
        x_limits = ax.get_xlim()
        actual_xrange = int(x_limits[1] - x_limits[0])
        
        print(f"实际显示范围: {actual_xrange} 根K线")
        print(f"显示的最新日期: {chan[0][int(x_limits[1])].time.to_str()}")
        
        if actual_xrange <= 160 and actual_xrange >= 140:  # 允许一些误差
            print("✓ 30分钟级别测试通过！")
        else:
            print("✗ 30分钟级别测试失败！")
            
        plt.close(plot_driver.figure)
        
    except Exception as e:
        print(f"✗ 30分钟级别测试失败: {e}")

if __name__ == "__main__":
    test_xrange_correctness()