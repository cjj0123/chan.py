#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据修复脚本

此脚本用于根据诊断结果，精确回填 `chan_trading.db` 数据库中缺失的股票数据。
它会调用项目中已有的 `DataAPI/SQLiteAPI.py` 中的下载逻辑。

支持两种模式：
1. 单股票修复：根据诊断JSON文件修复单个股票
2. 批量修复：从富途自选股获取股票列表，对每个股票进行诊断和修复（日期范围：2024-01-01 至今天）
"""

import os
import sys
import json
import argparse
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

# 导入 Futu 常量
try:
    from futu import RET_OK
except ImportError:
    RET_OK = 0  # 如果 Futu 未安装，使用默认值


def load_diagnosis_result(file_path: str) -> dict:
    """
    从JSON文件加载诊断结果。

    Args:
        file_path (str): 诊断结果JSON文件路径。

    Returns:
        dict: 诊断结果字典。
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def merge_date_ranges(ranges: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """
    合并重叠或相邻的日期范围。

    Args:
        ranges (List[Tuple[str, str]]): 日期范围列表。

    Returns:
        List[Tuple[str, str]]: 合并后的日期范围列表。
    """
    if not ranges:
        return []
    
    # 按开始日期排序
    sorted_ranges = sorted(ranges, key=lambda x: x[0])
    merged = [sorted_ranges[0]]
    
    for current_start, current_end in sorted_ranges[1:]:
        last_start, last_end = merged[-1]
        
        # 如果当前范围与上一个范围重叠或相邻，则合并
        last_end_dt = datetime.strptime(last_end, "%Y-%m-%d")
        current_start_dt = datetime.strptime(current_start, "%Y-%m-%d")
        
        if (current_start_dt - last_end_dt).days <= 1:
            # 合并范围
            new_end = max(last_end, current_end)
            merged[-1] = (last_start, new_end)
        else:
            # 添加新区间
            merged.append((current_start, current_end))
    
    return merged


def get_futu_watchlist_stocks() -> pd.DataFrame:
    """
    从富途自选股列表获取股票代码
    
    Returns:
        pd.DataFrame: 包含 ['代码', '名称', '最新价', '涨跌幅'] 列的股票列表
                      获取失败时返回空 DataFrame
    """
    try:
        from Monitoring.FutuMonitor import FutuMonitor
        monitor = FutuMonitor()
        # 获取第一个自选股分组的股票
        watchlists = monitor.get_watchlists()
        if not watchlists:
            print("没有找到富途自选股分组")
            monitor.quote_ctx.close()
            return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])
        
        # 使用第一个分组
        ret, data = monitor.quote_ctx.get_user_security(group_name=watchlists[0])
        monitor.quote_ctx.close()
        
        if ret != RET_OK:
            print(f"获取自选股失败: {data}")
            return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])
        
        # data is a pandas DataFrame, convert to our format
        result_df = pd.DataFrame({
            '代码': data['code'],
            '名称': data['name'],
            '最新价': [0.0] * len(data),  # 富途API返回的自选股数据可能不包含最新价
            '涨跌幅': [0.0] * len(data)   # 需要额外查询
        })
        
        return result_df[['代码', '名称', '最新价', '涨跌幅']]
    except Exception as e:
        print(f"从富途获取自选股列表失败: {e}")
        return pd.DataFrame(columns=['代码', '名称', '最新价', '涨跌幅'])


def diagnose_and_repair_stock(
    code: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    log_callback=None
) -> bool:
    """
    诊断并修复单个股票的数据
    
    Args:
        code (str): 股票代码
        timeframe (str): 时间级别 ('day', '30m', '5m', '1m')
        start_date (str): 诊断开始日期 (YYYY-MM-DD)
        end_date (str): 诊断结束日期 (YYYY-MM-DD)
        log_callback (callable, optional): 日志回调函数
        
    Returns:
        bool: 是否有数据被修复
    """
    from check_data_integrity import diagnose_stock_data
    
    # 诊断股票数据
    diagnosis = diagnose_stock_data(
        code=code,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date
    )
    
    missing_ranges = diagnosis['missing_ranges']
    if not missing_ranges:
        msg = f"✅ 股票 {code} 在 {timeframe} 级别无需修复。"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
        return False
    
    # 合并缺失的日期范围以减少API调用次数
    merged_ranges = merge_date_ranges(missing_ranges)
    
    msg = f"🔧 开始修复股票 {code} 在 {timeframe} 级别的数据..."
    if log_callback:
        log_callback(msg)
    else:
        print(msg)
    
    from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
    
    # 对每个合并后的范围进行修复
    repaired = False
    for i, (range_start, range_end) in enumerate(merged_ranges, 1):
        msg = f"  📥 正在下载范围 {i}/{len(merged_ranges)}: {range_start} 至 {range_end}"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
        
        try:
            # 调用现有的多时间级别下载函数
            download_and_save_all_stocks_multi_timeframe(
                stock_codes=[code],
                timeframes=[timeframe],
                start_date=range_start,
                end_date=range_end,
                log_callback=log_callback
            )
            
            msg = f"  ✅ 范围 {range_start} 至 {range_end} 修复成功。"
            if log_callback:
                log_callback(msg)
            else:
                print(msg)
            repaired = True
                
        except Exception as e:
            msg = f"  ❌ 范围 {range_start} 至 {range_end} 修复失败: {e}"
            if log_callback:
                log_callback(msg)
            else:
                print(msg, file=sys.stderr)
    
    if repaired:
        msg = f"🎉 股票 {code} 的数据修复流程已完成。"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    
    return repaired


def repair_all_watchlist_data(
    timeframes: List[str] = ['day', '30m', '5m', '1m'],
    start_date: str = "2024-01-01",
    end_date: Optional[str] = None,
    log_callback=None
):
    """
    从富途自选股获取股票列表，并对所有股票进行批量诊断和修复
    
    Args:
        timeframes (List[str]): 要修复的时间级别列表
        start_date (str): 修复开始日期 (默认: 2024-01-01)
        end_date (Optional[str]): 修复结束日期 (默认: 今天)
        log_callback (callable, optional): 日志回调函数
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    # 获取富途自选股列表
    msg = "🔍 正在从富途获取自选股列表..."
    if log_callback:
        log_callback(msg)
    else:
        print(msg)
    
    stocks_df = get_futu_watchlist_stocks()
    if stocks_df.empty:
        msg = "❌ 无法获取富途自选股列表，修复任务终止。"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
        return
    
    stock_codes = stocks_df['代码'].tolist()
    msg = f"📋 获取到 {len(stock_codes)} 只自选股，开始批量诊断和修复..."
    if log_callback:
        log_callback(msg)
    else:
        print(msg)
    
    total_repaired = 0
    total_stocks = len(stock_codes)
    
    # 对每个股票进行诊断和修复
    for i, code in enumerate(stock_codes, 1):
        msg = f"\n📊 进度 {i}/{total_stocks}: 处理股票 {code}"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
        
        # 对每个时间级别进行诊断和修复
        for timeframe in timeframes:
            if diagnose_and_repair_stock(code, timeframe, start_date, end_date, log_callback):
                total_repaired += 1
    
    msg = f"\n🎉 批量修复完成！总共处理了 {total_stocks} 只股票，修复了 {total_repaired} 个时间级别的数据。"
    if log_callback:
        log_callback(msg)
    else:
        print(msg)


def repair_stock_data(
    diagnosis_file: str,
    log_callback=None
):
    """
    根据诊断结果修复股票数据。

    Args:
        diagnosis_file (str): 诊断结果JSON文件路径。
        log_callback (callable, optional): 日志回调函数。
    """
    from DataAPI.SQLiteAPI import download_and_save_all_stocks_multi_timeframe
    
    # 加载诊断结果
    diagnosis = load_diagnosis_result(diagnosis_file)
    code = diagnosis['code']
    timeframe = diagnosis['timeframe']
    missing_ranges = diagnosis['missing_ranges']
    
    if not missing_ranges:
        msg = f"✅ 股票 {code} 在 {timeframe} 级别无需修复。"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
        return
    
    # 合并缺失的日期范围以减少API调用次数
    merged_ranges = merge_date_ranges(missing_ranges)
    
    msg = f"🔧 开始修复股票 {code} 在 {timeframe} 级别的数据..."
    if log_callback:
        log_callback(msg)
    else:
        print(msg)
    
    # 对每个合并后的范围进行修复
    for i, (start_date, end_date) in enumerate(merged_ranges, 1):
        msg = f"  📥 正在下载范围 {i}/{len(merged_ranges)}: {start_date} 至 {end_date}"
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
        
        try:
            # 调用现有的多时间级别下载函数
            # 注意：这里只下载单个股票和单个时间级别
            download_and_save_all_stocks_multi_timeframe(
                stock_codes=[code],
                timeframes=[timeframe],
                start_date=start_date,
                end_date=end_date,
                log_callback=log_callback
            )
            
            msg = f"  ✅ 范围 {start_date} 至 {end_date} 修复成功。"
            if log_callback:
                log_callback(msg)
            else:
                print(msg)
                
        except Exception as e:
            msg = f"  ❌ 范围 {start_date} 至 {end_date} 修复失败: {e}"
            if log_callback:
                log_callback(msg)
            else:
                print(msg, file=sys.stderr)
    
    msg = f"🎉 股票 {code} 的数据修复流程已完成。"
    if log_callback:
        log_callback(msg)
    else:
        print(msg)


def main():
    """主函数，用于命令行调用。"""
    parser = argparse.ArgumentParser(description="根据诊断结果修复数据库中的股票数据。")
    parser.add_argument("--diagnosis", help="诊断结果JSON文件路径 (例如: diagnosis_SH.600519_day.json)")
    parser.add_argument("--batch", action="store_true", help="启用批量修复模式（从富途自选股获取股票列表）")
    parser.add_argument("--timeframes", nargs="+", default=["day", "30m", "5m", "1m"],
                        choices=["day", "30m", "5m", "1m"],
                        help="批量修复时要处理的时间级别 (默认: day 30m 5m 1m)")
    parser.add_argument("--start-date", default="2024-01-01", help="批量修复的开始日期 (默认: 2024-01-01)")
    parser.add_argument("--end-date", help="批量修复的结束日期 (默认: 今天)")
    
    args = parser.parse_args()
    
    # 检查参数有效性
    if not args.batch and not args.diagnosis:
        print("❌ 错误: 必须指定 --diagnosis 文件或使用 --batch 模式。", file=sys.stderr)
        parser.print_help()
        sys.exit(1)
    
    if args.batch and args.diagnosis:
        print("❌ 错误: 不能同时指定 --diagnosis 和 --batch。", file=sys.stderr)
        sys.exit(1)
    
    if args.diagnosis and not os.path.exists(args.diagnosis):
        print(f"❌ 错误: 诊断文件 '{args.diagnosis}' 不存在。", file=sys.stderr)
        sys.exit(1)
    
    try:
        if args.batch:
            repair_all_watchlist_data(
                timeframes=args.timeframes,
                start_date=args.start_date,
                end_date=args.end_date
            )
            print("\n💡 提示: 批量修复完成后，建议对关键股票再次运行诊断脚本以验证修复结果。")
        else:
            repair_stock_data(args.diagnosis)
            print("\n💡 提示: 修复完成后，建议再次运行诊断脚本以验证修复结果。")
    except Exception as e:
        print(f"❌ 修复过程中发生错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()