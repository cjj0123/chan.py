#!/usr/bin/env python3
"""
全流程扫描测试 - 单次执行
"""
import sys
sys.path.insert(0, '/Users/jijunchen/.openclaw/workspace/chan.py')

from futu_hk_visual_trading_fixed import FutuHKVisualTrading
import logging

# 设置日志级别为DEBUG以查看详细信息
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

def test_full_scan():
    """执行一次完整的扫描测试"""
    print("=" * 70)
    print("🚀 启动全流程扫描测试")
    print("=" * 70)
    
    try:
        # 初始化交易系统 (模拟盘模式)
        trader = FutuHKVisualTrading(
            hk_watchlist_group="港股",
            min_visual_score=70,
            max_position_ratio=0.2,
            dry_run=True  # 模拟盘模式
        )
        
        print("\n✅ 交易系统初始化完成")
        print(f"   - 自选股组: 港股")
        print(f"   - 视觉评分阈值: 70分")
        print(f"   - 最大仓位比例: 20%")
        print(f"   - 交易模式: 模拟盘 (DRY_RUN)")
        
        # 执行单次扫描
        print("\n" + "=" * 70)
        print("📊 开始执行扫描...")
        print("=" * 70 + "\n")
        
        trader.scan_and_trade()
        
        print("\n" + "=" * 70)
        print("✅ 扫描测试完成")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            trader.close_connections()
            print("\n🔌 已关闭富途连接")
        except:
            pass

if __name__ == "__main__":
    test_full_scan()
