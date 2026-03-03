#!/usr/bin/env python3
"""调试脚本：诊断为什么回测系统无法生成 BSP 信号"""

import sys
import pandas as pd
sys.path.insert(0, '.')

from Common.CEnum import KL_TYPE
ORIGINAL_KL_TYPE = KL_TYPE  # 别名
from Chan import CChan
from ChanConfig import CChanConfig
from DataAPI.MockStockAPI import register_kline_data

# 导入 BacktestKLineUnit
from backtester import BacktestKLineUnit

def test_ctime():
    """测试 CTime 是否正常工作"""
    print("=" * 60)
    print("测试 1: CTime 类型")
    print("=" * 60)
    
    try:
        from Common.CTime import CTime
        ts = pd.Timestamp('2024-03-01 10:00:00')
        dt = ts.to_pydatetime()
        ctime = CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, auto=False)
        print(f"✅ CTime 创建成功：{ctime}")
        print(f"✅ CTime.to_str(): {ctime.to_str()}")
        return ctime
    except Exception as e:
        print(f"❌ CTime 测试失败：{e}")
        import traceback
        traceback.print_exc()
        return None

def test_backtest_klu():
    """测试 BacktestKLineUnit 的基本属性"""
    print("\n" + "=" * 60)
    print("测试 2: BacktestKLineUnit 属性")
    print("=" * 60)
    
    ts = pd.Timestamp('2024-03-01 10:00:00')
    klu = BacktestKLineUnit(
        timestamp=ts,
        open_p=300.0,
        high_p=310.0,
        low_p=295.0,
        close_p=305.0,
        volume=1000000,
        kl_type=ORIGINAL_KL_TYPE.K_30M
    )
    
    print(f"✅ BacktestKLineUnit 创建成功")
    print(f"   - timestamp: {klu.timestamp}")
    print(f"   - time: {klu.time}")
    print(f"   - time type: {type(klu.time)}")
    print(f"   - open: {klu.open}, high: {klu.high}, low: {klu.low}, close: {klu.close}")
    print(f"   - idx: {klu.idx}")
    print(f"   - pre_klu: {klu.pre_klu}")
    
    # 检查是否缺少关键属性
    missing_attrs = []
    for attr in ['pre', 'next', 'macd', 'boll', 'sub_kl_list', 'sup_kl']:
        if not hasattr(klu, attr):
            missing_attrs.append(attr)
    
    if missing_attrs:
        print(f"⚠️  缺少属性：{missing_attrs}")
    else:
        print(f"✅ 所有必需属性都存在")
    
    # 测试 set_idx
    klu.set_idx(0)
    print(f"✅ set_idx(0) 后 idx={klu.idx}")
    
    # 测试 set_pre_klu
    klu2 = BacktestKLineUnit(
        timestamp=pd.Timestamp('2024-03-01 10:30:00'),
        open_p=305.0,
        high_p=315.0,
        low_p=300.0,
        close_p=310.0,
        volume=1000000,
        kl_type=ORIGINAL_KL_TYPE.K_30M
    )
    klu2.set_idx(1)
    klu2.set_pre_klu(klu)
    print(f"✅ set_pre_klu 后：klu2.pre_klu={klu2.pre_klu is not None}")
    print(f"   - klu2.pre: {hasattr(klu2, 'pre') and klu2.pre is not None}")
    print(f"   - klu.next: {hasattr(klu, 'next') and klu.next is not None}")
    
    return klu

def test_mock_stock_api():
    """测试 MockStockAPI 是否能正确返回数据"""
    print("\n" + "=" * 60)
    print("测试 3: MockStockAPI 数据注册和获取")
    print("=" * 60)
    
    # 创建测试数据
    test_data = []
    for i in range(100):
        day = 1 + (i // 16)  # 每天 16 根 30M K 线（港股交易时间约 6.5 小时）
        hour = 9 + ((i % 16) // 2)
        minute = (i % 2) * 30
        if hour >= 12 and hour < 13:  # 跳过午休
            hour += 1
        ts = pd.Timestamp(f'2024-03-{day:02d} {hour:02d}:{minute:02d}:00')
        klu = BacktestKLineUnit(
            timestamp=ts,
            open_p=300 + i * 0.5,
            high_p=310 + i * 0.5,
            low_p=295 + i * 0.5,
            close_p=305 + i * 0.5,
            volume=1000000,
            kl_type=ORIGINAL_KL_TYPE.K_30M
        )
        klu.set_idx(i)
        if i > 0:
            klu.set_pre_klu(test_data[i-1])
        test_data.append(klu)
    
    # 注册数据
    register_kline_data("HK.00700", ORIGINAL_KL_TYPE.K_30M, test_data)
    print(f"✅ 注册了 {len(test_data)} 条 K 线数据")
    
    # 测试 MockStockAPI 是否能获取数据
    from DataAPI.MockStockAPI import MockStockAPI
    api = MockStockAPI("HK.00700", ORIGINAL_KL_TYPE.K_30M, "20240301", "20240302")
    data = list(api.get_kl_data())
    print(f"✅ MockStockAPI 返回了 {len(data)} 条数据")
    
    if len(data) > 0:
        first = data[0]
        print(f"   - 第一条数据时间：{first.time}")
        print(f"   - 第一条数据收盘价：{first.close}")
        print(f"   - time.to_str(): {first.time.to_str() if hasattr(first.time, 'to_str') else 'N/A'}")
    
    return test_data

def test_chan_step_load():
    """测试 CChan 的 step_load 是否能处理 BacktestKLineUnit"""
    print("\n" + "=" * 60)
    print("测试 4: CChan step_load 处理")
    print("=" * 60)
    
    # 创建测试数据 - 生成更真实的走势
    test_data = []
    base_price = 300
    import random
    
    for i in range(200):
        # 港股交易时间：9:30-12:00, 13:00-16:00，共 6.5 小时
        # 30M K 线：每天约 13 根
        day = 1 + (i // 13)
        slot = i % 13
        
        # 计算小时和分钟
        if slot < 5:  # 上午 9:30-11:30 (4 根 30M K 线：9:30, 10:00, 10:30, 11:00, 11:30)
            hour = 9 + (slot // 2)
            minute = 30 if slot % 2 == 0 else 0
            if slot == 0:
                hour, minute = 9, 30
            elif slot == 1:
                hour, minute = 10, 0
            elif slot == 2:
                hour, minute = 10, 30
            elif slot == 3:
                hour, minute = 11, 0
            elif slot == 4:
                hour, minute = 11, 30
        else:  # 下午 13:00-16:00 (8 根 30M K 线)
            afternoon_slot = slot - 5
            hour = 13 + (afternoon_slot // 2)
            minute = afternoon_slot % 2 * 30
        
        ts = pd.Timestamp(f'2024-03-{day:02d} {hour:02d}:{minute:02d}:00')
        
        # 生成有波动的价格，模拟真实走势（包含上下波动，便于形成笔和 BSP）
        random.seed(i)
        
        # 生成震荡走势，便于形成多个笔
        cycle = 15  # 每 15 根 K 线一个周期
        trend = (i // cycle) % 2  # 交替上升和下降
        price_change = random.uniform(-2, 2) + (3 if trend else -3)
        base_price += price_change
        
        open_p = base_price + random.uniform(-1, 1)
        close_p = base_price + random.uniform(-1, 1)
        high_p = max(open_p, close_p) + random.uniform(0, 1)
        low_p = min(open_p, close_p) - random.uniform(0, 1)
        
        klu = BacktestKLineUnit(
            timestamp=ts,
            open_p=open_p,
            high_p=high_p,
            low_p=low_p,
            close_p=close_p,
            volume=1000000,
            kl_type=ORIGINAL_KL_TYPE.K_30M
        )
        klu.set_idx(i)
        if i > 0:
            klu.set_pre_klu(test_data[i-1])
        test_data.append(klu)
    
    # 注册数据
    register_kline_data("HK.00700", ORIGINAL_KL_TYPE.K_30M, test_data)
    print(f"✅ 注册了 {len(test_data)} 条测试 K 线数据")
    
    # 创建 CChan 实例
    chan_config = CChanConfig()
    chan_config.trigger_step = True
    chan_config.skip_step = 0
    
    try:
        chan = CChan(
            code="HK.00700",
            data_src="custom:MockStockAPI.MockStockAPI",
            lv_list=[ORIGINAL_KL_TYPE.K_30M],
            config=chan_config,
            autype=0,
            begin_time=None,
            end_time=None
        )
        print("✅ CChan 实例创建成功")
        
        # 执行 step_load
        print("开始执行 step_load...")
        step_count = 0
        last_klc_count = 0
        
        for snapshot in chan.step_load():
            step_count += 1
            current_klc_count = len(chan[0].lst) if len(chan.lv_list) > 0 else 0
            
            if step_count % 50 == 0 or step_count <= 5:
                print(f"  Step {step_count}: KLC 数量={current_klc_count}, Bi 数量={len(chan[0].bi_list)}")
            
            if step_count >= 200:  # 限制步数
                break
        
        print(f"✅ step_load 完成，共 {step_count} 步")
        print(f"   - 最终 KLC 数量：{len(chan[0].lst)}")
        print(f"   - 最终 Bi 数量：{len(chan[0].bi_list)}")
        print(f"   - 最终 Seg 数量：{len(chan[0].seg_list)}")
        print(f"   - BSP 数量：{len(chan[0].bs_point_lst.getSortedBspList())}")
        
        # 尝试获取 BSP
        try:
            bsps = chan.get_latest_bsp(number=1)
            print(f"   - get_latest_bsp 返回：{len(bsps)} 个信号")
            if bsps:
                for bsp in bsps:
                    print(f"      * BSP 类型：{bsp.type2str()}, 买卖：{'买' if bsp.is_buy else '卖'}, 价格：{bsp.klu.close}")
        except Exception as e:
            print(f"   ❌ get_latest_bsp 失败：{e}")
        
        return chan
        
    except Exception as e:
        print(f"❌ CChan step_load 测试失败：{e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    print("🔍 开始调试回测系统 BSP 信号生成问题")
    print("=" * 60)
    
    # 测试 1: CTime
    ctime = test_ctime()
    
    # 测试 2: BacktestKLineUnit
    klu = test_backtest_klu()
    
    # 测试 3: MockStockAPI
    test_data = test_mock_stock_api()
    
    # 测试 4: CChan step_load
    chan = test_chan_step_load()
    
    print("\n" + "=" * 60)
    print("📊 调试总结")
    print("=" * 60)
    
    if chan and len(chan[0].bs_point_lst.getSortedBspList()) == 0:
        print("⚠️  问题确认：CChan 处理完成后没有生成任何 BSP 信号")
        print("\n可能原因:")
        print("1. Bi 列表为空或 Bi 数量不足（至少需要 3 个 Bi 才能形成 BSP）")
        print("2. K 线合并逻辑有问题，导致无法形成有效的分型")
        print("3. BacktestKLineUnit 缺少关键属性或方法")
        print("4. 数据格式不匹配 CChan 的期望")
    elif chan:
        print("✅ CChan 成功生成了 BSP 信号")

if __name__ == "__main__":
    main()
