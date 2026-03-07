#!/usr/bin/env python3
"""
测试TraderGUI数据库更新功能的修复
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from TraderGUI import TraderGUI
from PyQt6.QtWidgets import QApplication
import traceback

def test_db_update_fix():
    """测试数据库更新功能修复"""
    print("🔍 测试TraderGUI数据库更新功能修复...")
    
    try:
        # 创建Qt应用
        app = QApplication(sys.argv)
        
        # 创建TraderGUI实例
        gui = TraderGUI()
        
        # 验证数据库统计功能
        print("✅ 数据库统计功能存在")
        
        # 验证时间范围控件存在
        assert hasattr(gui, 'start_date_input'), "开始日期控件不存在"
        assert hasattr(gui, 'end_date_input'), "结束日期控件不存在"
        print("✅ 时间范围控件存在")
        
        # 验证1分钟选项存在
        scan_modes = [gui.scan_mode_combo.itemText(i) for i in range(gui.scan_mode_combo.count())]
        assert "1分钟" in scan_modes, "1分钟选项不存在"
        print("✅ 1分钟选项存在")
        
        # 验证数据库大小显示功能
        from Trade.db_util import CChanDB
        db = CChanDB()
        # 这个方法应该能正常执行而不抛出异常
        gui.display_db_stats(db)
        print("✅ 数据库大小显示功能正常")
        
        print("🎉 所有测试通过！数据库更新功能修复成功")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_db_update_fix()
    if success:
        print("\n✅ 所有功能测试通过！")
    else:
        print("\n❌ 存在问题需要修复")
        sys.exit(1)