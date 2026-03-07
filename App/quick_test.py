#!/usr/bin/env python3
"""
快速测试GUI是否可以启动
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use('Qt5Agg', force=True)

from PyQt6.QtWidgets import QApplication
from TraderGUI import TraderGUI

def quick_test():
    print("正在启动GUI...")
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        window = TraderGUI()
        print("窗口创建成功")
        window.show()
        print("窗口显示成功")
        print("GUI启动成功！")
        # 不调用app.exec()，因为我们只是验证能否启动
        return True
    except Exception as e:
        print(f"GUI启动失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    quick_test()