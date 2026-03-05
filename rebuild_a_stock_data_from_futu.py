#!/usr/bin/env python3
"""
从Futu重新下载A股数据到本地数据库
"""

import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
import pandas as pd
import os
import yaml

def get_a_stock_list():
    """获取A股股票列表"""
    # 首先尝试从富途自选股获取
    try:
        from Monitoring.FutuMonitor import FutuMonitor
        from futu import RET_OK
        monitor = FutuMonitor()
        watchlists = monitor.get_watchlists()
        if watchlists:
            ret, data = monitor.quote_ctx.get_user_security(group_name=watchlists[0])
            monitor.quote_ctx.close()
            if ret == RET_OK and not data.empty:
                # 过滤出A股（SH.6, SZ.0, SZ.3开头）
                a_stocks = data[data['code'].str.contains(r'^(SH\.6|SZ\.[03])')]
                if not a_stocks.empty:
                    print(f"✅ 从富途自选股获取到 {len(a_stocks)} 只A股")
                    return a_stocks['code'].tolist()
    except Exception as e:
        print(f"⚠️  从富途获取自选股失败: {e}")
    
    # 回退到测试股票列表
    try:
        test_config_path = "Config/test_stocks.yaml"
        if os.path.exists(test_config_path):
            with open(test_config_path, 'r', encoding='utf-8') as f:
                test_config = yaml.safe_load(f)
                if test_config and 'test_stocks' in test_config:
                    test_stocks = test_config['test_stocks']
                    codes = [stock['code'] for stock in test_stocks]
                    # 确保是A股代码格式
                    a_stock_codes = []
                    for code in codes:
                        if code.startswith('6'):
                            a_stock_codes.append(f"SH.{code}")
                        elif code.startswith(('0', '3')):
                            a_stock_codes.append(f"SZ.{code}")
                    if a_stock_codes:
                        print(f"✅ 从配置文件获取到 {len(a_stock_codes)} 只A股")
                        return a_stock_codes
    except Exception as e:
        print(f"⚠️  从配置文件获取股票列表失败: {e}")
    
    # 最后使用默认的A股列表
    default_a_stocks = ['SH.600000', 'SZ.000001', 'SH.600519', 'SZ.000858', 'SH.601318']
    print(f"✅ 使用默认的 {len(default_a_stocks)} 只A股")
    return default_a_stocks

def rebuild_a_stock_data():
    """重新下载A股数据"""
    print("🔄 开始重新下载A股数据...")
    
    # 获取A股股票列表
    stock_codes = get_a_stock_list()
    if not stock_codes:
        print("❌ 无法获取A股股票列表")
        return False
    
    print(f"📊 准备下载 {len(stock_codes)} 只A股的数据")
    print("   股票列表:", stock_codes[:5], "..." if len(stock_codes) > 5 else "")
    
    # 下载多时间级别数据
    try:
        download_and_save_all_stocks_multi_timeframe(
            stock_codes,
            days=365,  # 下载最近365天的数据
            timeframes=['day', '30m', '5m'],  # 支持日线、30分钟、5分钟
            log_callback=print
        )
        print("🎉 A股数据重新下载完成！")
        return True
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 A股数据重建工具")
    print("   - 清理现有的A股数据")
    print("   - 从Futu重新下载A股数据（支持5分钟级别）")
    print()
    
    confirm = input("是否开始重建A股数据? (y/N): ")
    if confirm.lower() == 'y':
        # 先清理A股数据
        print("\n🧹 正在清理现有的A股数据...")
        exec(open('clear_a_stock_data.py').read().replace('input("是否继续? (y/N): ")', '"y"'))
        
        # 重新下载
        print("\n📥 正在从Futu重新下载A股数据...")
        success = rebuild_a_stock_data()
        
        if success:
            print("\n✅ A股数据重建完成！")
            print("   现在您可以使用新的5分钟级别数据进行缠论分析了")
        else:
            print("\n❌ A股数据重建失败")
    else:
        print("已取消操作")