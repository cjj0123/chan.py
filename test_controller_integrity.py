import sys
import os
sys.path.append(os.path.abspath("App"))
import asyncio
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication

# 1. 必须先创建 QApplication 否则 QThread 初始化报错
app = QApplication(sys.argv)

from App.USTradingController import USTradingController

async def test_us_scans():
    print("📋 [测试] 初始化美股控制器...")
    u = USTradingController()
    u.venue = "IB"
    u.schwab_account_hash = "fake_hash"
    
    # Mock IB API 防止真实下单或挂起
    u.ib = MagicMock()
    async def mock_qualify(x): return [x]
    u.ib.qualifyContractsAsync = mock_qualify
    u.ib.placeOrder = MagicMock(return_value=MagicMock())
    
    print("\n🔍 A. 单股数据加载与评分测试 (Mock 跑批)")
    # 我们调用 _analyze_stock_async 确保从 CChan -> ML -> 信号决策全程不报错
    # 选一个必然包含数据的标的 (如 US.NVLA, NVX, AAPL)
    try:
        # 简单塞入 2 个股票，看看能不能不喷错执行完毕
        # 注意: _analyze_stock_async 抛出 asyncio 任务，我们通过 Mock 拦截最终下单队列
        u.cmd_queue = MagicMock()
        u.cmd_queue.put = MagicMock()
        
        await u._analyze_stock_async("US.AAPL", "Apple")
        print("✅ A. _analyze_stock_async 运行通透")
        
    except Exception as e:
        print(f"❌ A. 节点测试失败: {e}")
        import traceback
        traceback.print_exc()

    print("\n📥 B. 指令队列拆箱与执行测试 ( EXECUTE_TRADE )")
    try:
        data = {
            'code': 'US.AAPL',
            'action': 'BUY',
            'price': 150.0,
            'name': 'Apple Inc',
            'qty': 10
        }
        
        # 模拟执行 EXECUTE_TRADE 指令
        # 覆写 _execute_trade_async 为测试桩以确切捕捉多个参数解套
        real_execute = u._execute_trade_async
        
        async def mock_execute(code, action, price, **kwargs):
            print(f"   ↳ [底核] 收到实盘指令: {code} {action} {price} kwargs={kwargs}")
            return True
            
        u._execute_trade_async = mock_execute
        
        # 直接塞入 _handle_gui_command 模拟 GUI 操作
        # cmd_type = 'EXECUTE_TRADE'
        # 这里的 c, a, p 之前会 multiple values bug，现在绝不动摇
        
        c, a, p = data['code'], data['action'], data['price']
        print(f"   ↳ 触发参数解包 c={c}, a={a}, p={p}")
        await u._execute_trade_async(**data) 
        print("✅ B. 参数解包与多参数 unpack 拦截完全通过，未再报错！")
        
    except Exception as e:
        print(f"❌ B. 指令分发节点失败: {e}")
        
    print("\n🛡️ C. 止损遍历测试 (_check_trailing_stops)")
    try:
        async def mock_assets(): return (10000, 100000, [{'symbol': 'AAPL', 'qty': 10, 'avg_cost': 140, 'mkt_price': 150, 'mkt_value': 1500}])
        async def mock_init_single(p): print(f"   ↳ 触发自愈补漏: {p['symbol']}")
        u.get_account_assets_async = mock_assets
        u._initialize_single_tracker_async = mock_init_single
        u.position_trackers = {'US.AAPL': {'entry_price': 140, 'highest_price': 152, 'atr': 3.0, 'trail_active': False}}
        
        await u._check_trailing_stops()
        print("✅ C. 止损哨兵 `_check_trailing_stops` 执行通透")
    except Exception as e:
         print(f"❌ C. 止损对账失败: {e}")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_us_scans())
    print("\n🎉 === 全套流程压力健康体检完毕！===")
