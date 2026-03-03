#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的港股5分钟K线获取功能
"""

import os
import sys
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_fixed_analyze_with_chan():
    """测试修复后的analyze_with_chan函数"""
    print("=== 测试修复后的analyze_with_chan函数 ===")
    
    try:
        from futu_hk_visual_trading_fixed import FutuHKVisualTrading
        
        # 创建交易系统实例（模拟模式）
        trader = FutuHKVisualTrading(dry_run=True)
        
        # 测试单个股票
        test_code = "HK.00700"
        print(f"测试股票: {test_code}")
        
        result = trader.analyze_with_chan(test_code)
        
        if result:
            print(f"✅ 分析成功！")
            print(f"   信号类型: {result.get('bsp_type', 'N/A')}")
            print(f"   是否买入: {result.get('is_buy_signal', 'N/A')}")
            print(f"   信号价格: {result.get('bsp_price', 'N/A')}")
            print(f"   信号时间: {result.get('bsp_datetime_str', 'N/A')}")
            
            # 检查是否包含chan_analysis
            if 'chan_analysis' in result:
                print(f"   ✅ 包含chan_analysis数据")
            else:
                print(f"   ❌ 缺少chan_analysis数据")
                
            return True
        else:
            print(f"❌ 分析失败或无信号")
            return False
            
    except Exception as e:
        print(f"🔥 异常: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_fixed_analyze_with_chan()
    print(f"\n📊 最终测试结果: {'✅ 成功' if success else '❌ 失败'}")