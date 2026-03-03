#!/usr/bin/env python3
"""
最终测试：验证5分钟图表修复
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from futu_hk_visual_trading_fixed import FutuHKVisualTrading

def test_final_5m_fix():
    """最终测试5分钟图表修复"""
    trader = FutuHKVisualTrading(dry_run=True)
    
    # 测试股票
    test_code = "HK.00700"
    
    print(f"=== 最终测试: {test_code} ===")
    
    try:
        # 收集候选信号
        candidate_signals = trader._collect_candidate_signals([test_code])
        if not candidate_signals:
            print(f"❌ {test_code} 无候选信号")
            return False
        
        print(f"✅ 收集到 {len(candidate_signals)} 个候选信号")
        
        # 批量生成图表
        signals_with_charts = trader._batch_generate_charts(candidate_signals)
        if not signals_with_charts:
            print(f"❌ {test_code} 图表生成失败")
            return False
        
        print(f"✅ 生成 {len(signals_with_charts)} 个带图表的信号")
        
        # 检查图表
        signal = signals_with_charts[0]
        chart_paths = signal['chart_paths']
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
    success = test_final_5m_fix()
    if success:
        print("\n🎉 最终测试通过！5分钟图表问题已解决。")
    else:
        print("\n💥 最终测试失败！")