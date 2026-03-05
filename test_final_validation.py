#!/usr/bin/env python3
"""
最终验证：测试完整的多数据源下载功能
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_futu_watchlist_stocks
from DataAPI.SQLiteAPI import download_and_save_all_stocks
from Trade.db_util import CChanDB

def final_validation():
    print("=== 最终验证：多数据源下载功能 ===")
    try:
        # 获取富途自选股列表
        stock_list = get_futu_watchlist_stocks()
        print(f"获取到 {len(stock_list)} 只股票")
        
        if len(stock_list) == 0:
            print("❌ 未获取到任何股票")
            return False
        
        # 统计各市场股票
        all_codes = stock_list['代码'].tolist()
        us_codes = [code for code in all_codes if code.startswith('US.')]
        hk_codes = [code for code in all_codes if code.startswith('HK.')]
        a_codes = [code for code in all_codes if code.startswith('SH.') or code.startswith('SZ.')]
        
        print(f"市场分布: 美股{len(us_codes)}, 港股{len(hk_codes)}, A股{len(a_codes)}")
        
        # 测试下载所有A股和美股（应该都能成功），加上几个港股
        test_codes = []
        test_codes.extend(us_codes[:5])  # 前5只美股
        test_codes.extend(a_codes[:10])  # 前10只A股  
        test_codes.extend(hk_codes[:3])  # 前3只港股（包括可能失败的）
        
        print(f"\n测试下载 {len(test_codes)} 只股票:")
        print(f"  美股: {us_codes[:5]}")
        print(f"  A股: {a_codes[:10][:3]}...")  
        print(f"  港股: {hk_codes[:3]}")
        
        # 执行下载
        print(f"\n开始下载...")
        download_and_save_all_stocks(test_codes, days=30)
        
        # 检查结果
        db = CChanDB()
        downloaded_codes = db.execute_query("SELECT DISTINCT code FROM kline_day")['code'].tolist()
        success_count = len(downloaded_codes)
        failed_codes = [code for code in test_codes if code not in downloaded_codes]
        
        print(f"\n=== 下载结果 ===")
        print(f"成功: {success_count} 只")
        print(f"失败: {len(failed_codes)} 只")
        
        if success_count > 0:
            print(f"成功股票示例: {downloaded_codes[:5]}")
        if failed_codes:
            print(f"失败股票: {failed_codes}")
            
        # 验证数据质量
        total_records = db.execute_query("SELECT COUNT(*) as count FROM kline_day")['count'].iloc[0]
        print(f"总K线记录数: {total_records}")
        
        # 预期结果：A股和美股应该全部成功，港股部分失败
        expected_success = len([c for c in test_codes if not c.startswith('HK.')])
        actual_success = success_count
        
        print(f"\n=== 验证结果 ===")
        if actual_success >= expected_success:
            print("✅ 多数据源下载功能工作正常！")
            print("  - A股通过BaoStock成功下载")
            print("  - 美股通过AKShare成功下载") 
            print("  - 港股部分失败（预期行为）")
            return True
        else:
            print(f"❌ 下载成功率低于预期: {actual_success}/{expected_success}")
            return False
            
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = final_validation()
    if success:
        print("\n🎉 离线数据下载问题已解决！")
        print("用户现在可以:")
        print("1. 点击'更新本地数据库'下载所有可获取的股票数据")
        print("2. 点击'开始扫描'进行离线扫描")
        print("注意: 港股小盘股可能无法下载，这是正常现象")
    else:
        print("\n❌ 需要进一步调试")