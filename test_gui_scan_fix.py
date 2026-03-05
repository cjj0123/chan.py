#!/usr/bin/env python3
"""
测试GUI扫描修复后的功能
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_tradable_stocks, get_local_stock_list

def test_stock_list_priority():
    """测试股票列表获取优先级"""
    print("=== 测试股票列表获取优先级 ===")
    
    # 测试本地数据库获取
    local_df = get_local_stock_list()
    print(f"本地数据库股票数量: {len(local_df)}")
    if len(local_df) > 0:
        print(f"前5只股票: {local_df['代码'].tolist()[:5]}")
    
    # 测试可交易股票获取（应该优先使用本地数据库）
    tradable_df = get_tradable_stocks()
    print(f"可交易股票数量: {len(tradable_df)}")
    if len(tradable_df) > 0:
        print(f"前5只股票: {tradable_df['代码'].tolist()[:5]}")
    
    # 验证两者是否相同（说明优先使用了本地数据库）
    if len(local_df) == len(tradable_df) and len(local_df) > 0:
        local_codes = set(local_df['代码'].tolist())
        tradable_codes = set(tradable_df['代码'].tolist())
        if local_codes == tradable_codes:
            print("✓ 验证通过：get_tradable_stocks() 正确优先使用本地数据库")
            return True
        else:
            print("✗ 验证失败：股票代码不匹配")
            return False
    else:
        print("✗ 验证失败：股票数量不匹配")
        return False

if __name__ == "__main__":
    success = test_stock_list_priority()
    if success:
        print("\n✅ GUI扫描修复验证成功！")
        print("现在点击'开始扫描'按钮将使用本地数据库中的股票进行扫描，而不是测试股票。")
    else:
        print("\n❌ GUI扫描修复验证失败！")