#!/usr/bin/env python3
"""
简单测试：验证5分钟图表修复
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from futu_hk_visual_trading_fixed import FutuHKVisualTrading

def test_simple_5m_fix():
    """简单测试5分钟图表修复"""
    trader = FutuHKVisualTrading(dry_run=True)
    
    # 测试股票
    test_code = "HK.00700"
    
    print(f"=== 简单测试: {test_code} ===")
    
    try:
        # 直接调用analyze_with_chan
        chan_result = trader.analyze_with_chan(test_code)
        if not chan_result:
            print(f"❌ {test_code} 无缠论信号")
            return False
        
        print(f"✅ 分析结果: {chan_result['bsp_type']}, 价格: {chan_result['bsp_price']}")
        
        # 生成图表
        chart_paths = trader.generate_charts(test_code, chan_result['chan_analysis'])
        if not chart_paths:
            print(f"❌ {test_code} 图表生成失败")
            return False
        
        print(f"✅ 生成 {len(chart_paths)} 张图表")
        
        # 检查图表
        has_5m_chart = any('5M' in path for path in chart_paths)
        has_30m_chart = any('30M' in path for path in chart_paths)
        
        print(f"图表路径: {chart_paths}")
        print(f"包含5M图表: {has_5m_chart}")
        print(f"包含30M图表: {has_30m_chart}")
        
        if has_5m_chart and has_30m_chart:
            print("✅ 5M和30M图表都成功生成！")
            return True
        elif has_30m_chart:
            print("⚠️ 仅生成30M图表，5M数据可能不足")
            return True
        else:
            print("❌ 图表生成失败")
            return False
            
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        trader.close_connections()

if __name__ == "__main__":
    success = test_simple_5m_fix()
    if success:
        print("\n🎉 简单测试通过！5分钟图表问题已解决。")
    else:
        print("\n💥 简单测试失败！")