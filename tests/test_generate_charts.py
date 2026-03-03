#!/usr/bin/env python3
"""
测试图表生成功能 - 生成30分钟图和5分钟图供Gemini视觉评分使用
"""
import sys
sys.path.insert(0, '/Users/jijunchen/.openclaw/workspace/chan.py')

import os
from datetime import datetime, timedelta
from Chan import CChan, CChanConfig, KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 非交互式后端

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 缠论配置
chan_config = CChanConfig({
    "bi_strict": False,
    "one_bi_zs": True,
    "bs_type": '1,1p,2,2s,3a,3b',
    "macd": {"fast": 12, "slow": 26, "signal": 9}
})

def customize_macd_colors(plot_driver):
    """自定义MACD颜色 - AI视觉优化版"""
    try:
        for ax in plot_driver.figure.axes:
            # 设置MACD柱状图颜色
            for container in ax.containers:
                if hasattr(container, '__iter__'):
                    for bar in container:
                        if hasattr(bar, 'get_height'):
                            if bar.get_height() >= 0:
                                bar.set_color('#FF0000')
                                bar.set_edgecolor('#8B0000')
                            else:
                                bar.set_color('#00FF00')
                                bar.set_edgecolor('#006400')
                            bar.set_alpha(0.85)
            
            # 修改DIF和DEA线颜色
            for line in ax.lines:
                label = str(line.get_label()).lower() if line.get_label() else ''
                if 'dif' in label:
                    line.set_color('#FFFFFF')
                    line.set_linewidth(2.0)
                    line.set_alpha(0.9)
                elif 'dea' in label:
                    line.set_color('#FFFF00')
                    line.set_linewidth(2.0)
                    line.set_alpha(0.9)
            
            # 设置MACD图背景色
            ax.set_facecolor('#1a1a1a')
            ax.tick_params(colors='white')
            ax.xaxis.label.set_color('white')
            ax.yaxis.label.set_color('white')
    except Exception as e:
        print(f"自定义MACD颜色失败: {e}")

def generate_charts(code: str) -> list:
    """生成30分钟和5分钟图表"""
    chart_paths = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_code = code.replace('.', '_')
    charts_dir = "./charts_test"
    os.makedirs(charts_dir, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"正在生成 {code} 的图表...")
    print(f"{'='*60}")
    
    # ====== 生成30分钟图 ======
    print("\n📊 [1/2] 生成30分钟图...")
    end_time = datetime.now()
    start_time = end_time - timedelta(days=30)
    
    chan_30m = CChan(
        code=code,
        begin_time=start_time.strftime("%Y-%m-%d"),
        end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
        data_src=DATA_SRC.FUTU,
        lv_list=[KL_TYPE.K_30M],
        config=chan_config
    )
    
    plot_30m = CPlotDriver(
        chan_30m,
        plot_config={
            "plot_kline": True,
            "plot_bi": True,
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
                "color": "#FFFF00",
                "show_num": False
            },
            "zs": {
                "color": "#4169E1",
                "linewidth": 2
            },
            "bsp": {
                "fontsize": 12,
                "buy_color": "red",
                "sell_color": "green"
            },
            "macd": {
                "width": 0.6
            }
        }
    )
    
    customize_macd_colors(plot_30m)
    
    chart_30m_path = f"{charts_dir}/{safe_code}_{timestamp}_30M.png"
    plt.savefig(chart_30m_path, bbox_inches='tight', dpi=120, facecolor='white')
    plt.close('all')
    chart_paths.append(chart_30m_path)
    print(f"   ✅ 30分钟图: {chart_30m_path}")
    
    # ====== 生成5分钟图 ======
    print("\n📊 [2/2] 生成5分钟图...")
    end_time = datetime.now()
    start_time = end_time - timedelta(days=7)
    
    chan_5m = CChan(
        code=code,
        begin_time=start_time.strftime("%Y-%m-%d"),
        end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
        data_src=DATA_SRC.FUTU,
        lv_list=[KL_TYPE.K_5M],
        config=chan_config
    )
    
    plot_5m = CPlotDriver(
        chan_5m,
        plot_config={
            "plot_kline": True,
            "plot_bi": True,
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
                "color": "#FFFF00",
                "show_num": False
            },
            "zs": {
                "color": "#4169E1",
                "linewidth": 2
            },
            "bsp": {
                "fontsize": 12,
                "buy_color": "red",
                "sell_color": "green"
            },
            "macd": {
                "width": 0.6
            }
        }
    )
    
    customize_macd_colors(plot_5m)
    
    chart_5m_path = f"{charts_dir}/{safe_code}_{timestamp}_5M.png"
    plt.savefig(chart_5m_path, bbox_inches='tight', dpi=120, facecolor='white')
    plt.close('all')
    chart_paths.append(chart_5m_path)
    print(f"   ✅ 5分钟图: {chart_5m_path}")
    
    print(f"\n{'='*60}")
    print(f"✅ 所有图表生成完成！")
    print(f"{'='*60}")
    
    return chart_paths

if __name__ == "__main__":
    # 测试生成腾讯(HK.00700)的图表
    code = "HK.00700"
    try:
        paths = generate_charts(code)
        print(f"\n📁 生成的文件:")
        for p in paths:
            size = os.path.getsize(p) / 1024
            print(f"   • {p} ({size:.1f} KB)")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
