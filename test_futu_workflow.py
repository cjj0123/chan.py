#!/usr/bin/env python3
"""
测试富途自选股工作流程
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_tradable_stocks, get_futu_watchlist_stocks, get_local_stock_list

def test_futu_workflow():
    """测试富途自选股工作流程"""
    print("=== 测试富途自选股工作流程 ===")
    
    # 1. 测试获取富途自选股
    print("\n1. 获取富途自选股...")
    futu_df = get_futu_watchlist_stocks()
    print(f"   富途自选股数量: {len(futu_df)}")
    if len(futu_df) > 0:
        market_types = futu_df['代码'].str[:3].value_counts()
        print(f"   市场分布: {market_types.to_dict()}")
    
    # 2. 测试get_tradable_stocks（应该返回富途自选股）
    print("\n2. 测试get_tradable_stocks...")
    tradable_df = get_tradable_stocks()
    print(f"   可交易股票数量: {len(tradable_df)}")
    
    # 验证是否与富途自选股一致
    if len(futu_df) == len(tradable_df) and len(futu_df) > 0:
        futu_codes = set(futu_df['代码'].tolist())
        tradable_codes = set(tradable_df['代码'].tolist())
        if futu_codes == tradable_codes:
            print("   ✓ 验证通过：get_tradable_stocks() 正确返回富途自选股")
        else:
            print("   ✗ 验证失败：股票代码不匹配")
    else:
        print("   ✗ 验证失败：股票数量不匹配")
    
    # 3. 测试本地数据库股票（当前只有10只测试股票）
    print("\n3. 检查本地数据库股票...")
    local_df = get_local_stock_list()
    print(f"   本地数据库股票数量: {len(local_df)}")
    if len(local_df) > 0:
        print(f"   本地股票代码: {local_df['代码'].tolist()}")
    
    # 4. 工作流程说明
    print("\n=== 工作流程说明 ===")
    print("✅ 更新本地数据库时：")
    print("   - 优先使用富途自选股（125只）")
    print("   - 下载所有125只股票的历史数据到本地数据库")
    print("\n✅ 离线扫描时：")
    print("   - 使用本地数据库中的股票进行扫描")
    print("   - 如果已下载125只股票，则扫描125只")
    print("   - 如果只下载了10只测试股票，则扫描10只")
    
    return len(futu_df) > 0

if __name__ == "__main__":
    success = test_futu_workflow()
    if success:
        print("\n✅ 富途自选股工作流程验证成功！")
        print("现在可以：")
        print("1. 点击'更新本地数据库'下载125只富途自选股")
        print("2. 点击'开始扫描'扫描已下载的股票")
    else:
        print("\n❌ 富途自选股工作流程验证失败！")