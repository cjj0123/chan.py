#!/usr/bin/env python3
"""
测试线段配置的图表生成 - 修正版本
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def test_seg_chart_generation():
    """测试线段图表生成"""
    code = "HK.00700"  # 腾讯控股
    
    # 严格模式 + 线段配置
    chan_config = CChanConfig({
        "bi_strict": True,
        "one_bi_zs": False,
        "seg_algo": "chan",
        "bs_type": '1,1p,2,2s,3a,3b',
        "macd": {"fast": 12, "slow": 26, "signal": 9}
    })
    
    # 获取30分钟数据
    end_time = datetime.now()
    start_time = end_time - timedelta(days=30)
    
    print(f"正在获取 {code} 的30分钟数据...")
    chan_30m = CChan(
        code=code,
        begin_time=start_time.strftime("%Y-%m-%d"),
        end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
        data_src=DATA_SRC.FUTU,
        lv_list=[KL_TYPE.K_30M],
        config=chan_config
    )
    
    # 获取第一个KLine列表来访问笔和线段
    kl_list = chan_30m[0]  # 第一个级别的KLine列表
    
    print(f"缠论分析完成，检测到:")
    print(f"  笔数量: {len(kl_list.bi_list)}")
    print(f"  线段数量: {len(kl_list.seg_list)}")
    print(f"  中枢数量: {len(kl_list.zs_list)}")
    
    # 获取最新买卖点
    latest_bsp = chan_30m.get_latest_bsp(number=1)
    if latest_bsp:
        bsp = latest_bsp[0]
        print(f"  最新信号: {bsp.type2str()} @ {bsp.klu.close}")
    else:
        print("  无买卖点信号")
    
    # 生成图表
    plot_30m = CPlotDriver(
        chan_30m,
        plot_config={
            "plot_kline": True,
            "plot_bi": True,
            "plot_seg": True,     # 启用线段显示
            "plot_zs": True,
            "plot_bsp": True,
            "plot_macd": True
        },
        plot_para={
            "figure": {
                "w": 16,
                "h": 12,
                "macd_h": 0.25,
                "grid": None
            },
            "bi": {
                "color": "#FFFF00",  # 黄色笔
                "show_num": False
            },
            "seg": {
                "color": "#FF0000",  # 红色线段
                "linewidth": 2
            },
            "zs": {
                "color": "#4169E1",  # 皇家蓝中枢
                "linewidth": 2
            },
            "bsp": {
                "fontsize": 12,
                "buy_color": "red",
                "sell_color": "green"
            }
        }
    )
    
    # 保存图表
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chart_path = f"test_seg_{code}_{timestamp}_30M.png"
    plt.savefig(chart_path, bbox_inches='tight', dpi=120, facecolor='white')
    plt.close('all')
    
    print(f"图表已保存: {chart_path}")
    return chart_path

if __name__ == "__main__":
    try:
        chart_path = test_seg_chart_generation()
        print("✅ 线段图表生成测试成功！")
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()