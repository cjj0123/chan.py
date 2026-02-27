#!/usr/bin/env python3
"""
增强版图表生成功能 - 优化视觉显示供Gemini评分
优化点：
1. 最后一笔虚线改为黄色
2. 买卖点箭头和文字改为紫色/橙色并加粗
3. 添加中枢上下轨价格标注
"""
import sys
sys.path.insert(0, '/Users/jijunchen/.openclaw/workspace/chan.py')

import os
from datetime import datetime, timedelta
from Chan import CChan, CChanConfig, KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
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

def customize_chart(plot_driver, chan_obj):
    """
    自定义图表样式
    1. MACD颜色优化
    2. 买卖点样式优化（紫色买/橙色卖，加粗）
    3. 最后一笔虚线改黄色
    4. 添加中枢上下轨价格标注
    """
    try:
        axes = plot_driver.figure.axes
        if not axes:
            return
        
        # 主图通常是第一个axes
        main_ax = axes[0]
        
        # ====== 1. 修改买卖点样式 ======
        # 查找所有文本和箭头，修改买卖点标记
        for child in main_ax.get_children():
            # 修改买卖点文本
            if isinstance(child, plt.Text):
                text = child.get_text()
                if 'b' in text.lower() or '买' in text:
                    # 买点：紫色 + 加粗
                    child.set_color('#9400D3')  # 深紫
                    child.set_fontweight('bold')
                    child.set_fontsize(14)
                elif 's' in text.lower() or '卖' in text:
                    # 卖点：橙色 + 加粗
                    child.set_color('#FF8C00')  # 深橙
                    child.set_fontweight('bold')
                    child.set_fontsize(14)
            
            # 修改箭头颜色
            elif isinstance(child, mpatches.FancyArrowPatch):
                # 根据箭头方向判断买卖
                # 买入箭头通常向上，卖出箭头向下
                arrow_style = child.get_arrowstyle()
                if arrow_style:
                    # 尝试获取箭头端点判断方向
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
        
        # ====== 2. 修改最后一笔为黄色虚线 ======
        # 遍历所有线条，找到笔线并修改最后一笔
        bi_lines = []
        for line in main_ax.lines:
            # 检查是否是笔线（根据颜色或样式判断）
            if hasattr(line, '_color') or hasattr(line, 'get_color'):
                color = line.get_color()
                # 如果是笔线（黄色或默认颜色）
                if color in ['#FFFF00', 'yellow', '#FFD700', '#FFA500']:
                    bi_lines.append(line)
        
        # 如果有笔线，将最后一笔改为黄色虚线
        if bi_lines:
            last_bi = bi_lines[-1]
            last_bi.set_color('#FFFF00')  # 亮黄
            last_bi.set_linewidth(3)
            last_bi.set_linestyle('--')   # 虚线
            last_bi.set_alpha(1.0)
        
        # ====== 3. 添加中枢上下轨价格标注 ======
        # 从chan对象获取中枢信息
        try:
            zs_list = chan_obj.get_zs_lst()
            if zs_list:
                for zs in zs_list:
                    if hasattr(zs, 'begin') and hasattr(zs, 'end'):
                        # 获取中枢高低点
                        high = zs.high if hasattr(zs, 'high') else None
                        low = zs.low if hasattr(zs, 'low') else None
                        
                        if high is not None and low is not None:
                            # 在图表右侧添加价格标注
                            x_pos = main_ax.get_xlim()[1] * 0.98
                            
                            # 上轨价格
                            main_ax.annotate(
                                f'ZS↑:{high:.2f}',
                                xy=(x_pos, high),
                                fontsize=10,
                                color='#4169E1',
                                fontweight='bold',
                                ha='right',
                                va='bottom',
                                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8)
                            )
                            
                            # 下轨价格
                            main_ax.annotate(
                                f'ZS↓:{low:.2f}',
                                xy=(x_pos, low),
                                fontsize=10,
                                color='#4169E1',
                                fontweight='bold',
                                ha='right',
                                va='top',
                                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8)
                            )
        except Exception as e:
            print(f"添加中枢价格标注失败: {e}")
        
        # ====== 4. MACD颜色优化 ======
        if len(axes) > 1:
            macd_ax = axes[1]
            for container in macd_ax.containers:
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
            
            for line in macd_ax.lines:
                label = str(line.get_label()).lower() if line.get_label() else ''
                if 'dif' in label:
                    line.set_color('#FFFFFF')
                    line.set_linewidth(2.5)
                elif 'dea' in label:
                    line.set_color('#FFFF00')
                    line.set_linewidth(2.5)
            
            macd_ax.set_facecolor('#1a1a1a')
            macd_ax.tick_params(colors='white')
    
    except Exception as e:
        print(f"自定义图表失败: {e}")
        import traceback
        traceback.print_exc()

def generate_charts(code: str) -> list:
    """生成30分钟和5分钟图表（增强版）"""
    chart_paths = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_code = code.replace('.', '_')
    charts_dir = "./charts_test"
    os.makedirs(charts_dir, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"正在生成 {code} 的增强版图表...")
    print(f"优化项：")
    print(f"  • 买卖点：紫色(买)/橙色(卖) + 加粗")
    print(f"  • 最后一笔：黄色虚线")
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
                "show_num": False,
                
            },
            "zs": {
                "color": "#4169E1",
                
                
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
    
    # 应用自定义样式
    customize_chart(plot_30m, chan_30m)
    
    chart_30m_path = f"{charts_dir}/{safe_code}_{timestamp}_30M_enhanced.png"
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
                "show_num": False,
                
            },
            "zs": {
                "color": "#4169E1",
                
                
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
    
    # 应用自定义样式
    customize_chart(plot_5m, chan_5m)
    
    chart_5m_path = f"{charts_dir}/{safe_code}_{timestamp}_5M_enhanced.png"
    plt.savefig(chart_5m_path, bbox_inches='tight', dpi=120, facecolor='white')
    plt.close('all')
    chart_paths.append(chart_5m_path)
    print(f"   ✅ 5分钟图: {chart_5m_path}")
    
    print(f"\n{'='*60}")
    print(f"✅ 所有增强版图表生成完成！")
    print(f"{'='*60}")
    
    return chart_paths

if __name__ == "__main__":
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
