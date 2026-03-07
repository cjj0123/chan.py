#!/usr/bin/env python3
"""
测试图表修复的脚本
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from App.TraderGUI import TraderGUI
from PyQt6.QtWidgets import QApplication
import sys

def test_backend_compatibility():
    """测试matplotlib后端兼容性"""
    import matplotlib
    print(f"当前matplotlib后端: {matplotlib.get_backend()}")
    
    # 测试是否能正确创建FigureCanvas
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    
    try:
        fig = Figure(figsize=(10, 6))
        canvas = FigureCanvas(fig)
        print("✅ FigureCanvas创建成功")
        return True
    except Exception as e:
        print(f"❌ FigureCanvas创建失败: {e}")
        return False

def main():
    """主测试函数"""
    print("=== 图表修复测试 ===")
    
    # 测试1: 后端兼容性
    print("\n1. 测试matplotlib后端兼容性...")
    if not test_backend_compatibility():
        print("测试失败！")
        return False
    
    # 测试2: 启动GUI（手动测试）
    print("\n2. 启动TraderGUI进行手动测试...")
    print("请在GUI中输入股票代码（如: 600000）并点击'加载图表'")
    print("如果图表正常显示，则修复成功！")
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = TraderGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()