#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股5分钟K线获取问题诊断脚本（修复版）
"""

import os
import sys
import time
from datetime import datetime, timedelta
from futu import *

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_hk_5m_kline_direct_fixed(code: str, days: int = 30):
    """
    直接使用Futu API测试5分钟K线获取（修复版）
    """
    print(f"=== 测试港股 {code} 5分钟K线获取（修复版）===")
    
    # 初始化富途连接
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    
    try:
        # 计算时间范围
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        start_str = start_time.strftime("%Y-%m-%d")
        end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"请求时间范围: {start_str} 到 {end_str}")
        
        # 订阅5分钟K线
        ret, data = quote_ctx.subscribe([code], [SubType.K_5M])
        if ret != RET_OK:
            print(f"❌ 订阅失败: {data}")
            return False
        
        # 获取历史K线数据 - 使用正确的API方法
        print("正在获取5分钟K线数据...")
        ret, kline_data, page_token = quote_ctx.request_history_kline(
            code=code,
            start=start_str,
            end=end_str,
            ktype=KLType.K_5M,
            autype=AuType.QFQ
        )
        
        if ret == RET_OK:
            print(f"✅ 获取成功！共 {len(kline_data)} 根5分钟K线")
            if len(kline_data) > 0:
                print(f"最新K线时间: {kline_data.iloc[-1]['time_key']}")
                print(f"最新K线价格: {kline_data.iloc[-1]['close']}")
                print(f"最早K线时间: {kline_data.iloc[0]['time_key']}")
                
                # 检查数据连续性
                if len(kline_data) >= 20:
                    print("✅ 数据量充足（>=20根）")
                    return True
                else:
                    print(f"⚠️ 数据量不足（{len(kline_data)}根 < 20根）")
                    return False
            else:
                print("❌ 没有获取到任何K线数据")
                return False
        else:
            print(f"❌ 获取失败: {kline_data}")
            return False
            
    except Exception as e:
        print(f"🔥 异常: {e}")
        return False
    finally:
        quote_ctx.close()

def test_with_cchan_fixed(code: str, days: int = 30):
    """
    使用CChan测试5分钟K线获取（修复版）
    """
    print(f"\n=== 使用CChan测试港股 {code} 5分钟K线获取（修复版）===")
    
    try:
        from Chan import CChan
        from ChanConfig import CChanConfig
        from Common.CEnum import KL_TYPE, DATA_SRC
        
        # 加载配置
        from config import CHAN_CONFIG
        chan_config = CChanConfig(CHAN_CONFIG)
        
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        print(f"创建CChan实例，时间范围: {start_time.strftime('%Y-%m-%d')} 到 {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        chan_5m = CChan(
            code=code,
            begin_time=start_time.strftime("%Y-%m-%d"),
            end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
            data_src=DATA_SRC.FUTU,
            lv_list=[KL_TYPE.K_5M],
            config=chan_config
        )
        
        # 统计K线数量 - 使用正确的访问方式
        kline_5m_count = 0
        # chan_5m[0] 返回第一个级别（K_5M）的CKLine_List对象
        for klu in chan_5m[0].klu_iter():
            kline_5m_count += 1
            
        print(f"✅ CChan获取成功！共 {kline_5m_count} 根5分钟K线")
        
        if kline_5m_count >= 20:
            print("✅ CChan数据量充足（>=20根）")
            return True
        else:
            print(f"⚠️ CChan数据量不足（{kline_5m_count}根 < 20根）")
            return False
            
    except Exception as e:
        print(f"🔥 CChan异常: {e}")
        return False

if __name__ == "__main__":
    # 测试几个典型的港股代码
    test_codes = ["HK.00700", "HK.00966"]
    
    for code in test_codes:
        print(f"\n{'='*60}")
        print(f"测试股票: {code}")
        print(f"{'='*60}")
        
        # 测试5分钟K线（修复版）
        success_5m = test_hk_5m_kline_direct_fixed(code)
        
        # 测试CChan方式（修复版）
        success_cchan = test_with_cchan_fixed(code)
        
        print(f"\n📊 测试结果汇总 - {code}:")
        print(f"   5分钟K线 (直接): {'✅' if success_5m else '❌'}")
        print(f"   CChan 5分钟: {'✅' if success_cchan else '❌'}")
        
        if not success_5m:
            print(f"   🔍 5分钟K线获取失败，这可能是问题根源！")