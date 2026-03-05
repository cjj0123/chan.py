#!/usr/bin/env python3
"""
调试BaoStock字段映射问题
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import baostock as bs
from DataAPI.BaoStockAPI import CBaoStock, GetColumnNameFromFieldList
from Common.CEnum import KL_TYPE, AUTYPE

def debug_baostock_fields():
    """调试BaoStock字段映射"""
    print("=== 调试BaoStock字段映射 ===")
    
    # 初始化BaoStock
    CBaoStock.do_init()
    
    # 测试A股股票
    stock_code = "sh.600519"
    begin_date = "2024-01-01"
    end_date = "2024-02-01"
    
    print(f"查询股票: {stock_code}")
    print(f"日期范围: {begin_date} 到 {end_date}")
    
    # 天级别数据字段
    fields = "date,open,high,low,close,volume,amount,turn"
    print(f"请求字段: {fields}")
    
    rs = bs.query_history_k_data_plus(
        code=stock_code,
        fields=fields,
        start_date=begin_date,
        end_date=end_date,
        frequency='d',
        adjustflag='2',  # QFQ
    )
    
    if rs.error_code != '0':
        print(f"查询失败: {rs.error_msg}")
        return
    
    print(f"字段列表: {rs.fields}")
    
    # 获取字段映射
    column_names = GetColumnNameFromFieldList(fields)
    print(f"映射后的字段名: {column_names}")
    
    # 获取一行数据
    if rs.next():
        row_data = rs.get_row_data()
        print(f"原始数据: {row_data}")
        
        # 创建字典
        from DataAPI.BaoStockAPI import create_item_dict
        try:
            item_dict = create_item_dict(row_data, column_names)
            print(f"转换后的字典: {item_dict}")
            print(f"字典键: {list(item_dict.keys())}")
        except Exception as e:
            print(f"转换失败: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("没有获取到数据")

if __name__ == "__main__":
    debug_baostock_fields()