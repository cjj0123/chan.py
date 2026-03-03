#!/usr/bin/env python3
"""
暗黑版图表生成功能 - 黑色背景优化视觉对比度
优化点：
1. 主图背景改为黑色
2. 最后一笔虚线改为亮黄色
3. 买卖点箭头和文字改为紫色(买)/橙色(卖)并加粗
4. 添加中枢上下轨价格标注
5. K线颜色调整为适合黑色背景
"""
import sys
sys.path.insert(0, '/Users/jijunchen/.openclaw/workspace/chan.py')

import os
from datetime import datetime, timedelta
from Chan import CChan, CChanConfig, KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib
matplotlib.use('Agg')

plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

chan_config = CChanConfig({
    "bi_strict": False,
    "one_bi_zs": True,
    "bs_type": '1,1p,2,2s,3a,3b',
    "macd": {"fast": 12, "slow": 26, "signal": 9}
})

def customize_chart_dark(plot_driver, chan_obj):
    """
    暗黑主题自定义图表样式
    """
    try:
        axes = plot_driver.figure.axes
        if not axes:
            return
        
        main_ax = axes[0]
        
        # ====== 1. 设置黑色背景 ======
        main_ax.set_facecolor('#0d0d0d')  # 深黑背景
        
        # 修改所有文本颜色为白色
        for text in main_ax.texts:
            text.set_color('white')
        
        # 修改刻度颜色
        main_ax.tick_params(colors='white')
        main_ax.xaxis.label.set_color('white')
        main_ax.yaxis.label.set_color('white')
        
        # 修改边框颜色
        for spine in main_ax.spines.values():
            spine.set_color('#444444')
        
        # ====== 2. 修改买卖点样式（紫色买/橙色卖） ======
        for child in main_ax.get_children():
            if isinstance(child, plt.Text):
                text = child.get_text()
                if 'b' in text.lower() or '买' in text or 'B' in text:
                    child.set_color('#9400D3')  # 深紫
                    child.set_fontweight('bold')
                    child.set_fontsize(14)
                    child.set_bbox(dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7))
                elif 's' in text.lower() or '卖' in text or 'S' in text:
                    child.set_color('#FF8C00')  # 深橙
                    child.set_fontweight('bold')
                    child.set_fontsize(14)
                    child.set_bbox(dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7))
            
            elif isinstance(child, mpatches.FancyArrowPatch):
                try:
                    pos = child.get_positions()
                    if pos and len(pos) == 2:
                        start, end = pos
                        if end[1] > start[1]:  # 向上箭头 - 买
                            child.set_color('#9400D3')
                            child.set_linewidth(3)
                        else:  # 向下箭头 - 卖
                            child.set_color('#FF8C00')
                            child.set_linewidth(3)
                except:
                    pass
        
        # ====== 3. 修改最后一笔为亮黄色虚线 ======
        bi_lines = []
        for line in main_ax.lines:
            color = line.get_color()
            if color in ['#FFFF00', 'yellow', '#FFD700', '#FFA500', '#CCCC00']:
                bi_lines.append(line)
        
        if bi_lines:
            last_bi = bi_lines[-1]
            last_bi.set_color('#FFFF00')  # 亮黄
            last_bi.set_linewidth(3)
            last_bi.set_linestyle('--')
            last_bi.set_alpha(1.0)
        
        # ====== 4. 添加中枢上下轨价格标注 ======
        try:
            zs_list = chan_obj.get_zs_lst()
            if zs_list:
                for i, zs in enumerate(zs_list[-3:]):  # 只显示最近3个中枢
                    if hasattr(zs, 'high') and hasattr(zs, 'low'):
                        high = zs.high
                        low = zs.low
                        
                        # 在图表右侧添加价格标注
                        x_pos = main_ax.get_xlim()[1] * 0.98
                        
                        # 上轨价格
                        main_ax.annotate(
                            f'ZS{i+1}↑:{high:.2f}',
                            xy=(x_pos, high),
                            fontsize=9,
                            color='#4169E1',
                            fontweight='bold',
                            ha='right',
                            va='bottom',
                            bbox=dict(boxstyle='round,pad=0.2', facecolor='black', edgecolor='#4169E1', alpha=0.8)
                        )
                        
                        # 下轨价格
                        main_ax.annotate(
                            f'ZS{i+1}↓:{low:.2f}',
                            xy=(x_pos, low),
                            fontsize=9,
                            color='#4169E1',
                            fontweight='bold',
                            ha='right',
                            va='top',
                            bbox=dict(boxstyle='round,pad=0.2', facecolor='black', edgecolor='#4169E1', alpha=0.8)
                        )
        except Exception as e:
            print(f"添加中枢价格标注失败: {e}")
        
        # ====== 5. MACD区域黑色背景优化 ======
        if len(axes) > 1:
            macd_ax = axes[1]
            macd_ax.set_facecolor('#1a1a1a')
            macd_ax.tick_params(colors='white')
            
            for container in macd_ax.containers:
                if hasattr(container, '__iter__'):
                    for bar in container:
                        if hasattr(bar, 'get_height'):
                            if bar.get_height() >= 0:
                                bar.set_color('#FF4444')  # 亮红
                                bar.set_edgecolor('#CC0000')
                            else:
                                bar.set_color('#44FF44')  # 亮绿
                                bar.set_edgecolor('#00CC00')
                            bar.set_alpha(0.85)
            
            for line in macd_ax.lines:
                label = str(line.get_label()).lower() if line.get_label() else ''
                if 'dif' in label:
                    line.set_color('#FFFFFF')
                    line.set_linewidth(2.5)
                elif 'dea' in label:
                    line.set_color('#FFFF00')
                    line.set_linewidth(2.5)
    
    except Exception as e:
        print(f"自定义图表失败: {e}")
        import traceback
        traceback.print_exc()

def generate_charts_dark(code: str) -> list:
    """生成暗黑主题30分钟和5分钟图表"""
    chart_paths = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_code = code.replace('.', '_')
    charts_dir = "./charts_test"
    os.makedirs(charts_dir, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"正在生成 {code} 的暗黑主题图表...")
    print(f"优化项：")
    print(f"  • 主图背景：黑色 (#0d0d0d)")
    print(f"  • 买卖点：紫色(买)/橙色(卖) + 加粗")
    print(f"  • 最后一笔：亮黄色虚线")
    print(f"  • 中枢：添加上下轨价格标注")
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
                "color": "#4169E1"
            },
            "bsp": {
                "fontsize": 14,
                "buy_color": "#9400D3",   # 紫色买
                "sell_color": "#FF8C00"   # 橙色卖
            },
            "macd": {
                "width": 0.6
            }
        }
    )
    
    customize_chart_dark(plot_30m, chan_30m)
    
    chart_30m_path = f"{charts_dir}/{safe_code}_{timestamp}_30M_dark.png"
    plt.savefig(chart_30m_path, bbox_inches='tight', dpi=120, facecolor='black')
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
                "color": "#4169E1"
            },
            "bsp": {
                "fontsize": 14,
                "buy_color": "#9400D3",
                "sell_color": "#FF8C00"
            },
            "macd": {
                "width": 0.6
            }
        }
    )
    
    customize_chart_dark(plot_5m, chan_5m)
    
    chart_5m_path = f"{charts_dir}/{safe_code}_{timestamp}_5M_dark.png"
    plt.savefig(chart_5m_path, bbox_inches='tight', dpi=120, facecolor='black')
    plt.close('all')
    chart_paths.append(chart_5m_path)
    print(f"   ✅ 5分钟图: {chart_5m_path}")
    
    print(f"\n{'='*60}")
    print(f"✅ 所有暗黑主题图表生成完成！")
    print(f"{'='*60}")
    
    return chart_paths

if __name__ == "__main__":
    code = "HK.00700"
    try:
        paths = generate_charts_dark(code)
        print(f"\n📁 生成的文件:")
        for p in paths:
            size = os.path.getsize(p) / 1024
            print(f"   • {p} ({size:.1f} KB)")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
