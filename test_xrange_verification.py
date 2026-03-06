#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 x_range 设置是否正确的测试脚本
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC, AUTYPE
from Plot.PlotDriver import CPlotDriver
import matplotlib.pyplot as plt

def test_xrange_with_hk_00700():
    """测试 HK.00700 在不同时间级别的 x_range 设置"""
    
    code = "HK.00700"
    begin_time = "2025-01-01"
    end_time = "2026-03-05"
    
    # 测试不同的时间级别
    test_cases = [
        (KL_TYPE.K_DAY, 250, "日线"),
        (KL_TYPE.K_30M, 150, "30分钟"),
        (KL_TYPE.K_5M, 80, "5分钟"), 
        (KL_TYPE.K_1M, 40, "1分钟")
    ]
    
    for kl_type, expected_xrange, name in test_cases:
        print(f"\n=== 测试 {name} ===")
        
        try:
            # 创建缠论分析对象
            chan = CChan(
                code=code,
                begin_time=begin_time,
                end_time=end_time,
                data_src="custom:SQLiteAPI.SQLiteAPI",
                lv_list=[kl_type],
                config=CChanConfig(),
                autype=AUTYPE.QFQ,
            )
            
            print(f"成功加载 {len(chan[0])} 根K线数据")
            
            # 创建图表驱动器
            plot_para = {
                "figure": {
                    "x_range": expected_xrange,
                    "w": 12,
                    "h": 8,
                }
            }
            
            plot_driver = CPlotDriver(chan, plot_config="", plot_para=plot_para)
            
            # 检查实际的 x 范围
            ax = plot_driver.figure.axes[0]
            xlim = ax.get_xlim()
            actual_range = xlim[1] - xlim[0]
            
            print(f"期望 x_range: {expected_xrange}")
            print(f"实际 x_range: {actual_range:.1f}")
            print(f"x轴范围: [{xlim[0]:.1f}, {xlim[1]:.1f}]")
            
            # 验证最右侧是否是最新数据
            latest_kline_idx = len(chan[0]) - 1
            if xlim[1] >= latest_kline_idx - 5:  # 允许一些误差
                print("✅ 最右侧显示最新数据")
            else:
                print("❌ 最右侧不是最新数据")
                
            # 保存图表用于验证
            plt.savefig(f"test_{name.replace(' ', '_')}_chart.png", dpi=150, bbox_inches='tight')
            plt.close()
            
        except Exception as e:
            print(f"❌ 测试失败: {e}")
            continue

if __name__ == "__main__":
    test_xrange_with_hk_00700()
    print("\n测试完成！请检查生成的图表文件。")