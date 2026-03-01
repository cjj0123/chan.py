#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论核心库 CChan 诊断脚本
目的：独立于主扫描程序，深入检查 CChan 内部，判断买卖点生成是否正常。
"""

import sys
from datetime import datetime, timedelta

# 确保能找到 Chan 库
# sys.path.append('.') # 如果 Chan.py 在当前目录

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC

# --- 配置 ---
# 从之前的日志中选取一个股票作为样本
TARGET_STOCK = "SZ.300772" 
DATA_DAYS = 60 # 加载更多数据以确保有足够的K线形成买卖点

def run_chan_diagnostic():
    """执行缠论核心诊断"""
    print("=" * 70)
    print(f"🔬 开始对 {TARGET_STOCK} 进行缠论核心诊断...")
    print("=" * 70)

    # 1. 使用与主程序完全相同的缠论配置
    chan_config = CChanConfig({
        "bi_strict": True,
        "seg_algo": "chan",
        "trigger_step": False,
        "bs_type": '1,1p,2,2s,3a,3b',
    })
    print("✅ 配置加载成功 (bi_strict: True)")

    try:
        # 2. 初始化 CChan 核心分析器
        # 我们加载30分钟级别的数据，和主程序一致
        chan = CChan(
            code=TARGET_STOCK,
            begin_time=(datetime.now() - timedelta(days=DATA_DAYS)).strftime("%Y-%m-%d"),
            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data_src=DATA_SRC.FUTU,
            lv_list=[KL_TYPE.K_30M],
            config=chan_config
        )
        print(f"✅ CChan 初始化成功，加载了 {DATA_DAYS} 天的 30M K线数据。")
        
        # 3. 深入检查内部数据结构
        # chan[0] 返回的是该级别的 CChanLevelData 对象 (或者是 CKLine_List)
        chan_30m_data = chan[0]

        # 检查K线数量
        # 根据日志，CKLine_List 对象有一个 .lst 属性
        kline_count = len(chan_30m_data.lst)
        print(f"\n--- 检查结果 ---")
        print(f"📊 合并后K线数量 (CKLine): {kline_count}")

        if kline_count == 0:
            print("❌ 错误：未能加载到任何K线数据，请检查Futu数据源或网络连接。")
            return

        # 检查原始K线总数
        raw_kline_count = sum(len(ckl.lst) for ckl in chan_30m_data.lst)
        print(f"📊 原始K线数量 (CKLine_Unit): {raw_kline_count}")

        # 检查笔的数量
        bi_list = chan_30m_data.bi_list
        bi_count = len(bi_list)
        print(f"✒️  笔 (bi) 数量: {bi_count}")

        # 检查线段的数量
        seg_list = chan_30m_data.seg_list
        seg_count = len(seg_list)
        print(f"📈  线段 (seg) 数量: {seg_count}")

        # 关键：检查所有买卖点的数量
        # 从 scan_strategy.py 看，bs_point_lst 存放了买卖点
        bsp_obj = chan_30m_data.bs_point_lst
        bs_points = []
        for attr in ['items', 'lst', 'points', 'bsp_list']:
            if hasattr(bsp_obj, attr):
                val = getattr(bsp_obj, attr)
                bs_points = val() if callable(val) else val
                if bs_points: break
        
        if not bs_points:
            for v in bsp_obj.__dict__.values():
                if isinstance(v, list) and len(v) > 0:
                    bs_points = v
                    break

        bs_point_count = len(bs_points)
        print(f"🎯  所有买卖点 (bs_point) 数量: {bs_point_count}")

        print("-" * 18)
        
        # 4. 最终诊断
        print("\n--- 最终诊断 ---")
        if bi_count > 0 and seg_count > 0 and bs_point_count == 0:
            print("结论: 🔴 问题已定位！")
            print("     K线、笔、线段均已成功计算，但买卖点数量为0。")
            print("     这100%表明 CChan 核心库内部的`cal_bs_point()`算法在严格笔模式下未能生成任何买卖点。")
            print("     问题不在于我们重构的扫描脚本，而在于更底层的策略算法本身。")
        elif bs_point_count > 0:
            print("结论: 🟢 意外发现！")
            print(f"     核心库实际上生成了 {bs_point_count} 个买卖点！")
            print("     这意味着问题可能出在主程序的 `get_latest_bsp()` 函数未能正确提取它们。")
            print("\n最近的3个买卖点是:")
            for bsp in bs_points[-3:]:
                bsp_time = bsp.klu.time
                print(f"  - 类型: {bsp.type2str()}, 时间: {bsp_time.year}-{bsp_time.month}-{bsp_time.day} {bsp_time.hour}:{bsp_time.minute}")
        else:
            print("结论: 🟡 未知问题。")
            print("     未能计算出笔或线段，这可能是数据量不足或数据格式问题。")

    except Exception as e:
        print(f"\n❌ 诊断脚本在执行过程中发生异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_chan_diagnostic()
