#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据完整性诊断脚本

此脚本用于检查 `chan_trading.db` 数据库中指定股票在特定时间级别下的数据完整性。
它会报告缺失的日期范围，以便后续进行精确修复。
"""

import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Tuple, Optional


def get_existing_dates(db_path: str, code: str, table_name: str) -> List[str]:
    """
    从数据库中获取指定股票在指定表中的所有日期。

    Args:
        db_path (str): 数据库文件路径。
        code (str): 股票代码。
        table_name (str): 表名 (e.g., 'kline_day', 'kline_30m').

    Returns:
        List[str]: 排序后的日期列表。
    """
    with sqlite3.connect(db_path) as conn:
        query = f"SELECT date FROM {table_name} WHERE code = ? ORDER BY date"
        df = pd.read_sql_query(query, conn, params=(code,))
        return df['date'].tolist()


def find_missing_date_ranges(dates: List[str], start_date: str, end_date: str, timeframe: str) -> List[Tuple[str, str]]:
    """
    在给定的日期列表中找出缺失的日期范围。

    Args:
        dates (List[str]): 已存在的日期列表。
        start_date (str): 检查的开始日期 (YYYY-MM-DD)。
        end_date (str): 检查的结束日期 (YYYY-MM-DD)。
        timeframe (str): 时间级别 ('day', '30m', '5m', '1m').

    Returns:
        List[Tuple[str, str]]: 缺失的日期范围列表 [(start, end), ...]。
    """
    if not dates:
        return [(start_date, end_date)]

    # 将字符串日期转换为 datetime 对象
    existing_dates = set()
    for d in dates:
        # 处理可能包含时间的日期字符串
        date_part = d.split(' ')[0]
        existing_dates.add(datetime.strptime(date_part, "%Y-%m-%d").date())

    # 创建完整的日期范围
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    
    # 根据时间级别确定需要检查的日期
    # 对于分钟级别，我们只关心交易日
    # 这里简化处理，假设所有市场都遵循周一到周五
    current_date = start_dt
    all_dates = set()
    
    while current_date <= end_dt:
        if current_date.weekday() < 5:  # Monday is 0, Sunday is 6
            all_dates.add(current_date)
        current_date += timedelta(days=1)

    # 找出缺失的日期
    missing_dates = sorted(list(all_dates - existing_dates))
    
    if not missing_dates:
        return []

    # 将缺失的日期合并成连续的范围
    missing_ranges = []
    range_start = missing_dates[0]
    prev_date = missing_dates[0]

    for current_date in missing_dates[1:]:
        if (current_date - prev_date).days > 1:
            # 不连续，结束当前范围并开始新范围
            missing_ranges.append((range_start.strftime("%Y-%m-%d"), prev_date.strftime("%Y-%m-%d")))
            range_start = current_date
        prev_date = current_date
    
    # 添加最后一个范围
    missing_ranges.append((range_start.strftime("%Y-%m-%d"), prev_date.strftime("%Y-%m-%d")))
    
    return missing_ranges


def diagnose_stock_data(
    db_path: str = "chan_trading.db",
    code: str = "SH.600519",
    timeframe: str = "day",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> dict:
    """
    诊断指定股票在指定时间级别的数据完整性。

    Args:
        db_path (str): 数据库文件路径。
        code (str): 股票代码。
        timeframe (str): 时间级别 ('day', '30m', '5m', '1m')。
        start_date (Optional[str]): 检查的开始日期。如果为None，则使用数据库中的最早日期。
        end_date (Optional[str]): 检查的结束日期。如果为None，则使用今天。

    Returns:
        dict: 诊断结果，包含缺失的日期范围等信息。
    """
    table_map = {
        'day': 'kline_day',
        '30m': 'kline_30m',
        '5m': 'kline_5m',
        '1m': 'kline_1m'
    }
    
    if timeframe not in table_map:
        raise ValueError(f"不支持的时间级别: {timeframe}. 支持的级别: {list(table_map.keys())}")
    
    table_name = table_map[timeframe]
    
    # 获取现有日期
    existing_dates = get_existing_dates(db_path, code, table_name)
    
    if not existing_dates:
        print(f"⚠️  股票 {code} 在 {timeframe} 级别没有数据。")
        if start_date and end_date:
            return {
                "code": code,
                "timeframe": timeframe,
                "missing_ranges": [(start_date, end_date)],
                "total_missing_days": (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days + 1
            }
        else:
            return {
                "code": code,
                "timeframe": timeframe,
                "missing_ranges": [],
                "total_missing_days": 0
            }
    
    # 确定检查范围
    if start_date is None:
        # 使用数据库中的最早日期
        earliest_date = min(d.split(' ')[0] for d in existing_dates)
        start_date = earliest_date
    
    if end_date is None:
        # 使用今天
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    # 查找缺失的日期范围
    missing_ranges = find_missing_date_ranges(existing_dates, start_date, end_date, timeframe)
    
    # 计算总缺失天数
    total_missing_days = 0
    for start, end in missing_ranges:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        total_missing_days += (end_dt - start_dt).days + 1
    
    return {
        "code": code,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "existing_data_points": len(existing_dates),
        "missing_ranges": missing_ranges,
        "total_missing_days": total_missing_days
    }


def main():
    """主函数，用于命令行调用。"""
    import argparse
    
    parser = argparse.ArgumentParser(description="诊断数据库中股票数据的完整性。")
    parser.add_argument("--db", default="chan_trading.db", help="数据库文件路径 (默认: chan_trading.db)")
    parser.add_argument("--code", required=True, help="要诊断的股票代码 (例如: SH.600519)")
    parser.add_argument("--timeframe", choices=["day", "30m", "5m", "1m"], default="day", help="时间级别 (默认: day)")
    parser.add_argument("--start", help="检查的开始日期 (格式: YYYY-MM-DD)")
    parser.add_argument("--end", help="检查的结束日期 (格式: YYYY-MM-DD)")
    
    args = parser.parse_args()
    
    try:
        result = diagnose_stock_data(
            db_path=args.db,
            code=args.code,
            timeframe=args.timeframe,
            start_date=args.start,
            end_date=args.end
        )
        
        print(f"\n📊 数据完整性诊断报告")
        print(f"股票代码: {result['code']}")
        print(f"时间级别: {result['timeframe']}")
        print(f"检查范围: {result.get('start_date', 'N/A')} 到 {result.get('end_date', 'N/A')}")
        print(f"现有数据点: {result['existing_data_points']}")
        print(f"总缺失天数: {result['total_missing_days']}")
        
        if result['missing_ranges']:
            print("\n❌ 发现以下缺失的日期范围:")
            for i, (start, end) in enumerate(result['missing_ranges'], 1):
                print(f"  {i}. {start} 至 {end}")
        else:
            print("\n✅ 数据完整，未发现缺失日期。")
            
        # 将结果保存到JSON文件以便其他脚本使用
        import json
        output_file = f"diagnosis_{args.code}_{args.timeframe}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n📝 详细诊断结果已保存至: {output_file}")
        
    except Exception as e:
        print(f"❌ 诊断过程中发生错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()