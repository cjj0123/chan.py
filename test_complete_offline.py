#!/usr/bin/env python3
"""
完整测试离线模式功能 - 测试所有17只股票
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import SQLiteAPI
from Common.CEnum import AUTYPE, KL_TYPE, DATA_SRC
from Chan import CChan
from ChanConfig import CChanConfig
from Trade.db_util import CChanDB
import pandas as pd

def test_all_stocks():
    """测试所有数据库中的股票"""
    print("=== 完整离线模式测试 ===")
    
    # 获取所有有数据的股票
    db = CChanDB()
    df = db.execute_query('SELECT DISTINCT code FROM kline_day')
    stock_codes = df['code'].tolist()
    
    print(f"发现 {len(stock_codes)} 只股票有K线数据")
    
    success_count = 0
    fail_count = 0
    
    for i, code in enumerate(stock_codes, 1):
        print(f"\n[{i}/{len(stock_codes)}] 测试股票 {code}...")
        
        try:
            # 测试 SQLiteAPI
            api = SQLiteAPI(code, k_type=KL_TYPE.K_DAY, begin_date="2025-01-01", end_date="2026-12-31", autype=AUTYPE.QFQ)
            kl_data = list(api.get_kl_data())
            if len(kl_data) == 0:
                print(f"  ⚠️  {code}: SQLiteAPI 返回0根K线")
                fail_count += 1
                continue
            
            # 测试 CChan 集成
            chan_config = CChanConfig()
            chan = CChan(
                code=code,
                begin_time="2025-01-01",
                end_time="2026-12-31",
                data_src="custom:SQLiteAPI.SQLiteAPI",
                lv_list=[KL_TYPE.K_DAY],
                config=chan_config,
                autype=AUTYPE.QFQ,
            )
            
            kline_count = len(chan[0]) if len(chan.lv_list) > 0 else 0
            print(f"  ✅ {code}: 成功创建 CChan 对象，包含 {kline_count} 个K线 (原始 {len(kl_data)} 根)")
            success_count += 1
            
        except Exception as e:
            print(f"  ❌ {code}: 创建 CChan 失败 - {e}")
            fail_count += 1
    
    print(f"\n=== 测试结果 ===")
    print(f"成功: {success_count} 只股票")
    print(f"失败: {fail_count} 只股票")
    print(f"总计: {len(stock_codes)} 只股票")
    
    if fail_count == 0:
        print("\n🎉 所有股票离线模式测试通过！")
        return True
    else:
        print(f"\n⚠️  有 {fail_count} 只股票测试失败，请检查")
        return False

if __name__ == "__main__":
    success = test_all_stocks()
    sys.exit(0 if success else 1)