#!/usr/bin/env python3
"""
调试TraderGUI启动问题
"""

import sys
import traceback
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

print("🔍 开始调试TraderGUI启动问题...")

try:
    print("1. 导入必要模块...")
    from PyQt6.QtWidgets import QApplication
    print("   ✅ PyQt6导入成功")
    
    print("2. 导入TraderGUI...")
    from App.TraderGUI import TraderGUI
    print("   ✅ TraderGUI导入成功")
    
    print("3. 创建QApplication...")
    app = QApplication(sys.argv)
    print("   ✅ QApplication创建成功")
    
    print("4. 设置样式...")
    app.setStyle("Fusion")
    print("   ✅ 样式设置成功")
    
    print("5. 创建TraderGUI实例...")
    window = TraderGUI()
    print("   ✅ TraderGUI实例创建成功")
    
    print("6. 显示窗口...")
    window.show()
    print("   ✅ 窗口显示成功")
    
    print("7. 确保按钮可见...")
    window.ensure_buttons_visible()
    print("   ✅ 按钮可见性设置成功")
    
    print("\n🎉 所有步骤成功完成！GUI应该已启动。")
    print("   现在运行app.exec()...")
    
    # 运行应用程序
    sys.exit(app.exec())
    
except Exception as e:
    print(f"\n❌ 启动过程中出现错误: {str(e)}")
    print("\n详细错误信息:")
    traceback.print_exc()
    sys.exit(1)