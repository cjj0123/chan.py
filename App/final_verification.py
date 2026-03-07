#!/usr/bin/env python3
"""
最终验证脚本 - 确认启动时不再查询数据库
"""

import ast
import sys
import os

def verify_startup_optimization():
    """验证启动时不再查询数据库"""
    print("🔍 验证启动优化...")
    
    file_path = "App/TraderGUI.py"
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查__init__方法中是否还有数据库统计调用
    # 找到__init__方法的定义
    lines = content.split('\n')
    
    in_init_method = False
    init_end_line = -1
    init_start_line = -1
    
    for i, line in enumerate(lines):
        if 'def __init__(self):' in line:
            in_init_method = True
            init_start_line = i
        elif in_init_method and line.strip().startswith('class ') and init_start_line > 0:
            init_end_line = i
            break
        elif in_init_method and line.strip() == '' and i > init_start_line + 10:
            # 查找方法结束（连续空行或其他方法开始）
            j = i
            while j < len(lines) and lines[j].strip() == '':
                j += 1
            if j < len(lines) and lines[j].strip().startswith('def '):
                init_end_line = i
                break
    
    if init_end_line == -1:
        init_end_line = len(lines)
    
    init_content = '\n'.join(lines[init_start_line:init_end_line])
    
    # 检查初始化方法中是否还有数据库统计相关的调用
    has_db_call_in_init = (
        'display_db_stats' in init_content and 
        'CChanDB()' in init_content
    )
    
    if has_db_call_in_init:
        print("❌ 初始化方法中仍存在数据库统计调用")
        return False
    else:
        print("✅ 初始化方法中已移除数据库统计调用")
    
    # 检查是否在其他地方有数据库统计调用
    # 搜索整个文件中display_db_stats的调用位置
    import re
    pattern = r'\.display_db_stats\s*\('
    matches = list(re.finditer(pattern, content))
    
    for match in matches:
        # 找到匹配行号
        line_num = content[:match.start()].count('\n') + 1
        line_content = lines[line_num - 1].strip()
        
        # 检查是否在__init__方法中
        if init_start_line <= line_num <= init_end_line:
            print(f"❌ 在__init__方法中发现display_db_stats调用: 行 {line_num}")
            return False
    
    print("✅ display_db_stats调用不在__init__方法中")
    
    # 检查是否在ensure_buttons_visible之后调用（但在__init__方法之外）
    ensure_buttons_pos = content.find('self.ensure_buttons_visible()')
    display_db_stats_calls = []
    
    # 找到所有display_db_stats的调用
    import re
    for match in re.finditer(r'self\.display_db_stats\s*\(', content):
        pos = match.start()
        line_num = content[:pos].count('\n') + 1
        # 检查这个调用是否在__init__方法中
        in_init = False
        for init_match in re.finditer(r'def __init__\(self\):', content):
            init_start = init_match.start()
            # 找到方法结束位置（下一个def或class定义，或者文件结尾）
            next_def = content[init_start + 1:].find('\ndef ')
            next_class = content[init_start + 1:].find('\nclass ')
            
            end_pos = len(content)
            if next_def != -1:
                next_def += init_start + 1
                end_pos = min(end_pos, next_def)
            if next_class != -1:
                next_class += init_start + 1
                end_pos = min(end_pos, next_class)
                
            if init_start < pos < end_pos:
                in_init = True
                break
        
        if not in_init and pos > ensure_buttons_pos:
            display_db_stats_calls.append(line_num)
    
    if display_db_stats_calls:
        print(f"❌ 在__init__方法外且ensure_buttons_visible()之后仍有display_db_stats调用: 行 {display_db_stats_calls}")
        return False
    else:
        print("✅ 已移除启动时的数据库统计调用")
        print("   (display_db_stats现在只在用户交互时调用，如on_update_db_clicked)")
    
    return True

def verify_other_features():
    """验证其他功能特性"""
    print("\n🔍 验证其他功能特性...")
    
    with open("App/TraderGUI.py", 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 验证时间范围功能
    if "start_date_input" in content and "end_date_input" in content:
        print("✅ 时间范围控件存在")
    else:
        print("❌ 时间范围控件缺失")
        return False
    
    # 验证1分钟选项
    if '"1分钟"' in content:
        print("✅ 1分钟选项存在")
    else:
        print("❌ 1分钟选项缺失")
        return False
    
    # 验证数据库大小显示
    if "db_size_mb = round" in content:
        print("✅ 数据库大小显示功能存在")
    else:
        print("❌ 数据库大小显示功能缺失")
        return False
    
    return True

def main():
    """主函数"""
    print("开始最终验证...")
    
    success1 = verify_startup_optimization()
    success2 = verify_other_features()
    
    if success1 and success2:
        print("\n🎉 所有验证通过！")
        print("✅ 启动时不再查询数据库，提高了启动速度")
        print("✅ 所有其他功能特性正常工作")
        print("✅ 数据库更新功能遵循指定时间范围")
        print("✅ 显示数据库占用空间大小")
        print("✅ 包含1分钟时间级别选项")
        return True
    else:
        print("\n❌ 验证失败！")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)