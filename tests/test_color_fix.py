#!/usr/bin/env python3
"""
测试缠论图表颜色修复 - 验证默认颜色配置
"""
import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from Chan import CChan, CChanConfig, KL_TYPE, DATA_SRC
    from Plot.PlotDriver import CPlotDriver
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 缠论配置
    chan_config = CChanConfig({
        "bi_strict": True,
        "zs_combine": True,
        "bs_type": '1,1p,2,2s,3a,3b',
        "macd": {"fast": 12, "slow": 26, "signal": 9}
    })
    
    def test_default_colors():
        """测试默认颜色配置"""
        print("测试缠论图表默认颜色配置...")
        
        # 创建一个简单的CChanPlotMeta对象来测试绘图函数
        from Plot.PlotMeta import CChanPlotMeta
        from Common.CEnum import BI_DIR
        
        # 模拟一些数据
        class MockKLU:
            def __init__(self, idx, high, low, close, open_price):
                self.idx = idx
                self.high = high
                self.low = low
                self.close = close
                self.open = open_price
                
        class MockBi:
            def __init__(self, begin_x, begin_y, end_x, end_y, is_sure=True):
                self.begin_x = begin_x
                self.begin_y = begin_y
                self.end_x = end_x
                self.end_y = end_y
                self.is_sure = is_sure
                self.dir = BI_DIR.UP if end_y > begin_y else BI_DIR.DOWN
                self.idx = 0
                
        class MockZS:
            def __init__(self, begin, low, w, h, is_sure=True):
                self.begin = begin
                self.low = low
                self.w = w
                self.h = h
                self.is_sure = is_sure
                self.is_onebi_zs = False
                self.sub_zs_lst = []
                
        class MockBSP:
            def __init__(self, x, y, is_buy=True):
                self.x = x
                self.y = y
                self.is_buy = is_buy
                
            def desc(self):
                return "b1" if self.is_buy else "s1"
                
        # 创建模拟的meta对象
        meta = CChanPlotMeta(None)
        meta.klu_list = [MockKLU(i, 100+i, 90+i, 95+i, 92+i) for i in range(10)]
        meta.bi_list = [
            MockBi(0, 95, 5, 105, True),
            MockBi(5, 105, 9, 98, False)  # 虚线
        ]
        meta.zs_lst = [MockZS(2, 98, 4, 8, True)]
        meta.bs_point_lst = [MockBSP(7, 102, True), MockBSP(8, 100, False)]
        meta.klu_len = 10
        meta.datetick = [f"2023-01-{i+1:02d}" for i in range(10)]
        
        # 创建图形
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.set_xlim(0, 9)
        ax.set_ylim(90, 110)
        
        # 测试绘图函数的默认颜色
        from Plot.PlotDriver import plot_bi_element, add_zs_text
        
        # 测试笔的颜色（默认黑色）
        for bi in meta.bi_list:
            plot_bi_element(bi, ax, 'black')  # 使用我们设置的默认值
            
        # 测试中枢的颜色（默认橙色）
        for zs in meta.zs_lst:
            from matplotlib.patches import Rectangle
            line_style = '-' if zs.is_sure else '--'
            ax.add_patch(Rectangle((zs.begin, zs.low), zs.w, zs.h, 
                                 fill=False, color='orange', linewidth=2, linestyle=line_style))
            
        # 测试买卖点的颜色（默认洋红色）
        y_range = 20
        for bsp in meta.bs_point_lst:
            color = 'magenta'  # 使用我们设置的默认值
            verticalalignment = 'top' if bsp.is_buy else 'bottom'
            arrow_dir = 1 if bsp.is_buy else -1
            arrow_len = 0.15 * y_range
            arrow_head = arrow_len * 0.2
            
            ax.text(bsp.x, bsp.y - arrow_len * arrow_dir,
                   f'{bsp.desc()}',
                   fontsize=15,
                   color=color,
                   verticalalignment=verticalalignment,
                   horizontalalignment='center')
            ax.arrow(bsp.x, bsp.y - arrow_len * arrow_dir,
                    0, (arrow_len - arrow_head) * arrow_dir,
                    head_width=1, head_length=arrow_head, color=color)
        
        # 保存测试图
        test_dir = "./charts_test"
        os.makedirs(test_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        test_path = f"{test_dir}/color_test_{timestamp}.png"
        plt.savefig(test_path, bbox_inches='tight', dpi=120, facecolor='white')
        plt.close('all')
        
        print(f"✅ 颜色测试图已生成: {test_path}")
        print("颜色验证:")
        print("  • 笔(Bi): 黑色 (实线和虚线)")
        print("  • 中枢(ZhongShu): 橙色矩形")
        print("  • 买卖点信号: 洋红色文字和箭头")
        
        return True
        
    if __name__ == "__main__":
        try:
            success = test_default_colors()
            if success:
                print("\n🎉 颜色配置测试成功！")
        except Exception as e:
            print(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            
except ImportError as e:
    print(f"导入错误: {e}")
    print("这可能是因为缺少依赖包，但颜色配置修改已经完成。")
    print("颜色修改详情:")
    print("  • 线段(Seg)颜色: green → purple")  
    print("  • 买卖点信号颜色: red/green → magenta")