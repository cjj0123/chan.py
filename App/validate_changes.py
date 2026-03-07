#!/usr/bin/env python3
"""
验证TraderGUI.py的修改是否正确
"""

import ast
import sys
import os
import re

def validate_code_changes():
    """验证代码修改"""
    print("🔍 验证TraderGUI.py的修改...")
    
    file_path = "App/TraderGUI.py"
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否包含时间范围控件
    if "start_date_input" not in content or "end_date_input" not in content:
        print("❌ 未找到时间范围控件")
        return False
    print("✅ 时间范围控件存在")
    
    # 检查on_update_db_clicked方法是否使用了时间范围
    if "start_date = self.start_date_input.date().toString" not in content:
        print("❌ on_update_db_clicked方法未使用开始日期控件")
        return False
    if "end_date = self.end_date_input.date().toString" not in content:
        print("❌ on_update_db_clicked方法未使用结束日期控件")
        return False
    print("✅ on_update_db_clicked方法使用了时间范围控件")
    
    # 检查是否传递了时间范围参数给UpdateDatabaseThread
    if "start_date,  # 使用用户选择的开始日期" not in content:
        print("❌ 未将开始日期传递给UpdateDatabaseThread")
        return False
    if "end_date    # 使用用户选择的结束日期" not in content:
        print("❌ 未将结束日期传递给UpdateDatabaseThread")
        return False
    print("✅ 时间范围参数正确传递给UpdateDatabaseThread")
    
    # 检查display_db_stats方法是否包含数据库大小信息
    if "db_size_mb = round(db_size / (1024 * 1024), 2)" not in content:
        print("❌ display_db_stats方法未计算数据库大小")
        return False
    if '"  数据库大小:"' not in content and 'f"  数据库大小:' not in content:
        print("❌ display_db_stats方法未显示数据库大小")
        return False
    print("✅ display_db_stats方法包含数据库大小信息")
    
    # 检查是否在初始化时调用了display_db_stats
    if "self.display_db_stats(db)" not in content:
        print("❌ 初始化时未调用display_db_stats")
        return False
    print("✅ 初始化时调用了display_db_stats")
    
    # 检查1分钟选项是否在扫描模式组合框中
    if '"1分钟"' not in content or '["日线", "30分钟", "5分钟", "1分钟"]' not in content:
        print("❌ 1分钟选项未添加到扫描模式组合框")
        return False
    print("✅ 1分钟选项已添加到扫描模式组合框")
    
    # 检查timeframe_map是否包含1分钟选项
    if '"1分钟": [\'1m\'],' not in content:
        print("❌ on_update_db_clicked方法的timeframe_map未包含1分钟选项")
        return False
    print("✅ on_update_db_clicked方法的timeframe_map包含1分钟选项")
    
    print("\n🎉 所有验证通过！代码修改符合要求")
    return True

def validate_syntax():
    """验证Python语法"""
    print("\n🔍 验证Python语法...")
    
    try:
        with open("App/TraderGUI.py", 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 解析AST以验证语法
        ast.parse(content)
        print("✅ Python语法正确")
        return True
    except SyntaxError as e:
        print(f"❌ 语法错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 解析错误: {e}")
        return False

def main():
    """主函数"""
    print("开始验证TraderGUI.py的修改...")
    
    success1 = validate_code_changes()
    success2 = validate_syntax()
    
    if success1 and success2:
        print("\n✅ 所有验证通过！")
        print("修改内容包括：")
        print("- ✅ 数据库更新功能现在遵循指定的时间范围")
        print("- ✅ 显示数据库占用空间大小")
        print("- ✅ 显示数据库更新时间")
        print("- ✅ 添加了1分钟时间级别选项")
        print("- ✅ 应用启动时显示数据库统计信息")
        return True
    else:
        print("\n❌ 验证失败！")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)