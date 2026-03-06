#!/usr/bin/env python3
"""
测试不同时间级别图表的x_range设置（使用数据完整的股票）
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Common.CEnum import KL_TYPE
from Chan import CChan
from ChanConfig import CChanConfig
from Plot.PlotDriver import CPlotDriver
import matplotlib.pyplot as plt

def test_chart_xrange():
    """测试不同时间级别图表的x_range设置"""
    # 测试股票代码 - 使用数据完整的股票
    test_code = "HK.00100"
    
    # 不同时间级别和对应的预期x_range
    test_cases = [
        (KL_TYPE.K_DAY, 250),
        (KL_TYPE.K_30M, 150), 
        (KL_TYPE.K_5M, 80),
        (KL_TYPE.K_1M, 40)
    ]
    
    for kl_type, expected_xrange in test_cases:
        print(f"测试 {kl_type.name} 时间级别，预期x_range: {expected_xrange}")
        
        try:
            # 创建缠论配置
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
            
            # 创建缠论分析对象 - 使用离线SQLite模式
            chan = CChan(
                code=test_code,
                begin_time="2023-01-01",
                end_time=None,
                data_src="custom:SQLiteAPI.SQLiteAPI",  # 使用自定义SQLite数据源
                lv_list=[kl_type],
                config=chan_config
            )
            
            if len(chan[0]) == 0:
                print(f"  警告: {kl_type.name} 没有数据")
                continue
                
            # 创建plot参数
            plot_para = {
                "figure": {
                    "x_range": expected_xrange,
                    "w": 12,
                    "h": 6,
                }
            }
            
            # 创建CPlotDriver
            plot_driver = CPlotDriver(chan, plot_config="kline,buy", plot_para=plot_para)
            
            # 检查实际的x_limits
            ax = plot_driver.figure.axes[0]
            x_limits = ax.get_xlim()
            actual_xrange = int(x_limits[1] - x_limits[0])
            
            print(f"  实际显示范围: {actual_xrange} 根K线")
            print(f"  总数据量: {len(chan[0])} 根K线")
            
            if actual_xrange <= expected_xrange + 10:  # 允许一些误差
                print(f"  ✓ 测试通过")
            else:
                print(f"  ✗ 测试失败: 实际范围 {actual_xrange} 超过预期 {expected_xrange}")
                
            plt.close(plot_driver.figure)
            
        except Exception as e:
            print(f"  ✗ 测试失败: {e}")
            continue
    
    print("测试完成")

if __name__ == "__main__":
    test_chart_xrange()