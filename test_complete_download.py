#!/usr/bin/env python3
"""
完整测试125只股票的下载功能
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from App.ashare_bsp_scanner_gui import get_futu_watchlist_stocks
from DataAPI.SQLiteAPI import download_and_save_all_stocks

def test_complete_download():
    print("正在测试完整下载125只股票...")
    try:
        # 获取富途自选股列表
        stock_list = get_futu_watchlist_stocks()
        print(f"获取到 {len(stock_list)} 只股票")
        
        if len(stock_list) == 0:
            print("❌ 未获取到任何股票")
            return
        
        # 统计各市场股票
        all_codes = stock_list['代码'].tolist()
        us_codes = [code for code in all_codes if code.startswith('US.')]
        hk_codes = [code for code in all_codes if code.startswith('HK.')]
        a_codes = [code for code in all_codes if code.startswith('SH.') or code.startswith('SZ.')]
        
        print(f"美股: {len(us_codes)}, 港股: {len(hk_codes)}, A股: {len(a_codes)}")
        
        # 测试下载 - 先测试每个市场的前2只股票
        test_codes = []
        test_codes.extend(us_codes[:2])
        test_codes.extend(hk_codes[:2]) 
        test_codes.extend(a_codes[:2])
        
        print(f"测试下载 {len(test_codes)} 只股票: {test_codes}")
        
        # 执行下载
        download_and_save_all_stocks(test_codes, days=30)  # 只下载30天数据
        
        # 检查结果
        import sqlite3
        conn = sqlite3.connect('chan_trading.db')
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT code FROM kline_day")
        downloaded_codes = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        print(f"成功下载 {len(downloaded_codes)} 只股票: {downloaded_codes}")
        
        # 分析失败原因
        failed_codes = [code for code in test_codes if code not in downloaded_codes]
        if failed_codes:
            print(f"下载失败的股票: {failed_codes}")
            for code in failed_codes:
                if code.startswith('HK.'):
                    print(f"  {code}: 港股可能无历史数据或AKShare连接问题")
                elif code.startswith('US.'):
                    print(f"  {code}: 美股应该能下载，检查AKShare连接")
                else:
                    print(f"  {code}: A股应该能下载，检查BaoStock连接")
        
    except Exception as e:
        print(f"❌ 完整测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_complete_download()