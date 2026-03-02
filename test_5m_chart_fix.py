#!/usr/bin/env python3
"""
测试5分钟图表修复版本
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from futu_hk_visual_trading_fixed_5m_chart_fix import FutuHKVisualTrading

def test_5m_chart_fix():
    """测试5分钟图表修复版本"""
    trader = FutuHKVisualTrading(dry_run=True)
    
    # 测试股票
    test_code = "HK.00700"
    
    print(f"测试股票: {test_code}")
    
    try:
        # 缠论分析
        chan_result = trader.analyze_with_chan(test_code)
        if not chan_result:
            print(f"{test_code} 无缠论信号，跳过")
            return
        
        print(f"分析结果: {chan_result['bsp_type']}, 价格: {chan_result['bsp_price']}")
        
        # 生成图表
        chart_paths = trader.generate_charts(test_code, chan_result['chan_analysis'])
        print(f"生成的图表路径: {chart_paths}")
        
        # 检查是否包含5M图表
        has_5m_chart = any('5M' in path for path in chart_paths)
        has_30m_chart = any('30M' in path for path in chart_paths)
        
        print(f"包含5M图表: {has_5m_chart}")
        print(f"包含30M图表: {has_30m_chart}")
        
        if has_5m_chart and has_30m_chart:
            print("✅ 5M和30M图表都成功生成！")
        elif has_30m_chart:
            print("⚠️ 仅生成30M图表，5M数据可能不足")
        else:
            print("❌ 图表生成失败")
            
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        trader.close_connections()

if __name__ == "__main__":
    test_5m_chart_fix()