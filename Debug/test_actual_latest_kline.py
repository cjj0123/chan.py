#!/usr/bin/env python3
"""
测试实际的5分钟K线最新数据获取
"""

import sys
import os
# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from datetime import datetime
from DataAPI.FutuAPICached import CFutuAPICached
from Common.CEnum import KL_TYPE, AUTYPE

def test_actual_latest_5m_kline():
    """测试实际的5分钟K线最新数据"""
    print("=== 测试实际的5分钟K线最新数据 ===")
    
    # 获取当前时间
    from datetime import timedelta
    current_time = datetime.now()
    start_time = current_time - timedelta(days=1)
    
    start_str = start_time.strftime("%Y-%m-%d")
    end_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"请求时间范围: {start_str} 到 {end_str}")
    
    try:
        # 创建Futu API实例
        api = CFutuAPICached(
            code="HK.00700",
            k_type=KL_TYPE.K_5M,
            begin_date=start_str,
            end_date=end_str,
            autype=AUTYPE.QFQ
        )
        
        # 获取K线数据
        klines = list(api.get_kl_data())
        print(f"获取到 {len(klines)} 根5分钟K线")
        
        if klines:
            latest_kline = klines[-1]
            latest_time = latest_kline.time
            print(f"最新K线时间: {latest_time.year}-{latest_time.month:02d}-{latest_time.day:02d} {latest_time.hour:02d}:{latest_time.minute:02d}")
            print(f"最新K线价格: {latest_kline.close}")
            
            # 检查是否是真正的最新数据
            current_minute = current_time.minute
            current_hour = current_time.hour
            current_day = current_time.day
            
            # 5分钟K线的最新时间应该接近当前时间
            time_diff_minutes = (current_time.hour * 60 + current_time.minute) - (latest_time.hour * 60 + latest_time.minute)
            if time_diff_minutes <= 5:
                print("✅ 最新K线数据正常！")
                return True
            else:
                print(f"⚠️ 最新K线可能不是最新的，时间差: {time_diff_minutes} 分钟")
                return False
        else:
            print("❌ 没有获取到任何K线数据")
            return False
            
    except Exception as e:
        print(f"❌ 获取K线数据失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_actual_latest_5m_kline()
    if success:
        print("\n🎉 测试成功！5分钟K线最新数据问题已解决。")
    else:
        print("\n❌ 测试失败，请检查问题。")