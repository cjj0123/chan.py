#!/usr/bin/env python3
"""
K线数据库更新脚本
用于初始化和维护本地SQLite K线数据库
支持多市场（A股、港股、美股）和多时间级别
"""

import sys
import os
import yaml
from datetime import datetime, timedelta
from typing import List

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DataAPI.DataManager import get_data_manager
from Common.CEnum import KL_TYPE


def load_config():
    """加载数据库配置"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Config", "database_config.yaml")
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    else:
        print(f"⚠️ 警告: 配置文件 {config_path} 不存在，使用默认配置")
        return None


def get_default_stock_codes() -> List[str]:
    """获取默认的股票代码列表"""
    config = load_config()
    if config and 'default_stocks' in config:
        stocks = []
        for market_stocks in config['default_stocks'].values():
            stocks.extend(market_stocks)
        return stocks
    
    # 从配置文件或预定义列表获取股票代码
    default_codes = [
        # 港股示例
        "HK.00966", "HK.00916", "HK.00100",
        # A股示例  
        "SH.600000", "SZ.000001",
        # 美股示例
        "US.AAPL", "US.GOOG"
    ]
    return default_codes


def update_database_for_timeframe(stock_codes: List[str], 
                                k_type: KL_TYPE, 
                                days: int = 365,
                                start_date: str = None,
                                end_date: str = None):
    """
    更新指定时间级别的数据库
    
    Args:
        stock_codes: 股票代码列表
        k_type: K线类型
        days: 下载天数
        start_date: 开始日期
        end_date: 结束日期
    """
    print(f"🔄 开始更新 {k_type.name} 数据...")
    
    data_manager = get_data_manager()
    result = data_manager.update_local_database(
        stock_codes, k_type, days, start_date, end_date
    )
    
    success_count = sum(1 for success in result.values() if success)
    total_count = len(result)
    
    print(f"✅ {k_type.name} 数据更新完成: {success_count}/{total_count} 成功")
    
    # 显示失败的股票
    failed_codes = [code for code, success in result.items() if not success]
    if failed_codes:
        print(f"❌ 失败的股票: {', '.join(failed_codes)}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='K线数据库更新工具')
    parser.add_argument('--stocks', '-s', nargs='+', 
                       help='股票代码列表，例如: HK.00966 SH.600000 US.AAPL')
    parser.add_argument('--timeframes', '-t', nargs='+', 
                       choices=['day', '30m', '5m', '1m'],
                       default=['day'],
                       help='时间级别 (默认: day)')
    parser.add_argument('--days', '-d', type=int, default=365,
                       help='下载天数 (默认: 365)')
    parser.add_argument('--start-date', 
                       help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', 
                       help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--all-default', action='store_true',
                       help='使用默认股票列表')
    
    args = parser.parse_args()
    
    # 确定股票代码列表
    if args.stocks:
        stock_codes = args.stocks
    elif args.all_default:
        stock_codes = get_default_stock_codes()
    else:
        print("❌ 错误: 必须指定股票代码或使用 --all-default")
        parser.print_help()
        sys.exit(1)
    
    # 时间级别映射
    tf_map = {
        'day': KL_TYPE.K_DAY,
        '30m': KL_TYPE.K_30M,
        '5m': KL_TYPE.K_5M,
        '1m': KL_TYPE.K_1M
    }
    
    timeframes = [tf_map[tf] for tf in args.timeframes]
    
    print(f"📊 准备更新 {len(stock_codes)} 只股票的数据")
    print(f"📈 时间级别: {', '.join(args.timeframes)}")
    print(f"📅 数据范围: {args.days} 天" if not args.start_date else f"📅 自定义日期范围: {args.start_date} 到 {args.end_date or '今天'}")
    
    # 更新每个时间级别
    for k_type in timeframes:
        update_database_for_timeframe(
            stock_codes, k_type, args.days, args.start_date, args.end_date
        )
    
    print("🎉 所有数据更新完成！")


if __name__ == "__main__":
    main()