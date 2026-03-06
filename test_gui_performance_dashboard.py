#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
性能仪表盘GUI测试脚本
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication
from App.PerformanceDashboard import PerformanceDashboard

def test_performance_dashboard():
    """测试性能仪表盘GUI组件"""
    print("🧪 测试性能仪表盘GUI组件...")
    
    app = QApplication(sys.argv)
    
    # 创建性能仪表盘
    dashboard = PerformanceDashboard()
    dashboard.setWindowTitle("性能仪表盘测试")
    dashboard.resize(400, 500)
    dashboard.show()
    
    print("✅ 性能仪表盘GUI组件创建成功！")
    print("请观察界面是否正常显示，按Ctrl+C退出测试。")
    
    try:
        app.exec()
    except KeyboardInterrupt:
        print("测试已终止")

if __name__ == "__main__":
    test_performance_dashboard()