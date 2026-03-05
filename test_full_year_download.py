#!/usr/bin/env python3
"""
测试完整1年数据下载和扫描
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_futu_watchlist_stocks
from DataAPI.SQLiteAPI import download_and_save_all_stocks
from Trade.db_util import CChanDB

def test_full_year():
    print("=== 测试1年完整数据下载 ===")
    try:
        # 获取富途自选股列表
        stock_list = get_futu_watchlist_stocks()
        print(f"获取到 {len(stock_list)} 只股票")
        
        if len(stock_list) == 0:
            print("❌ 未获取到任何股票")
            return False
        
        # 测试下载前20只股票（包含各市场）
        all_codes = stock_list['代码'].tolist()
        test_codes = all_codes[:20]
        
        print(f"测试下载前20只股票: {test_codes}")
        
        # 执行1年数据下载
        print(f"\n开始下载1年数据 (365天)...")
        download_and_save_all_stocks(test_codes, days=365)
        
        # 检查下载结果
        db = CChanDB()
        downloaded_codes = db.execute_query("SELECT DISTINCT code FROM kline_day")['code'].tolist()
        success_count = len(downloaded_codes)
        
        # 检查每只股票的K线数量
        print(f"\n=== K线数据统计 ===")
        total_records = 0
        for code in downloaded_codes:
            count = db.execute_query(f"SELECT COUNT(*) as count FROM kline_day WHERE code = '{code}'")['count'].iloc[0]
            total_records += count
            print(f"{code}: {count} 条K线")
        
        print(f"\n总K线记录数: {total_records}")
        print(f"成功下载: {success_count}/20 只股票")
        
        # 验证是否足够进行缠论分析
        # 通常需要至少50-100条K线才能形成有效的缠论结构
        sufficient_data = 0
        for code in downloaded_codes:
            count = db.execute_query(f"SELECT COUNT(*) as count FROM kline_day WHERE code = '{code}'")['count'].iloc[0]
            if count >= 50:
                sufficient_data += 1
        
        print(f"\n=== 缠论分析可行性 ===")
        print(f"有足够数据的股票 (>50条K线): {sufficient_data}/{success_count}")
        
        if sufficient_data > 0:
            print("✅ 1年数据足以支持缠论分析！")
            return True
        else:
            print("❌ K线数据仍然不足，可能需要更长时间的历史数据")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_full_year()
    if success:
        print("\n🎉 1年数据下载成功，可以进行完整的缠论扫描！")
    else:
        print("\n❌ 需要进一步调试")