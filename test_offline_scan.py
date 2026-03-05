#!/usr/bin/env python3
"""
测试离线扫描功能
"""
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from App.ashare_bsp_scanner_gui import get_local_stock_list
from DataAPI.SQLiteAPI import SQLiteAPI
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, KL_TYPE

def test_offline_scan():
    print("获取本地股票列表...")
    stock_list = get_local_stock_list()
    print(f"找到 {len(stock_list)} 只本地股票")
    
    if len(stock_list) == 0:
        print("没有找到本地股票数据")
        return
    
    # 测试前3只股票的扫描
    for i, code in enumerate(stock_list['代码'].head(3)):
        print(f"\n正在分析股票 {code} ({i+1}/{min(3, len(stock_list))})...")
        
        try:
            # 创建SQLite API实例
            sqlite_api = SQLiteAPI(code, autype=AUTYPE.QFQ)
            
            # 获取缠论配置
            chan_config = CChanConfig({
                "bi_strict": True,
                "one_bi_zs": False,
                "seg_algo": "chan",
                "bs_type": "1,1p,2,2s,3a,3b",
                "divergence_rate": float('inf'),
                "min_zs_cnt": 0,
                "bsp2_follow_1": False,
                "bsp3_follow_1": False,
                "bs1_peak": False,
                "macd_algo": "peak",
                "zs_algo": "normal"
            })
            
            # 执行缠论分析
            chan = CChan(
                code=code,
                begin_time=None,
                end_time=None,
                data_src="custom:SQLiteAPI.SQLiteAPI",
                lv_list=[KL_TYPE.K_DAY],
                config=chan_config
            )
            
            # 查找买点
            from datetime import datetime, timedelta
            bsp_list = chan.get_latest_bsp(number=0)
            cutoff_date = datetime.now() - timedelta(days=365)  # 检查所有历史买点
            buy_points = [
                bsp for bsp in bsp_list
                if bsp.is_buy and datetime(bsp.klu.time.year, bsp.klu.time.month, bsp.klu.time.day) >= cutoff_date
            ]
            
            print(f"股票 {code}: 找到 {len(buy_points)} 个买点")
            if buy_points:
                for bp in buy_points[:2]:  # 显示前2个买点
                    print(f"  - 时间: {bp.klu.time}, 价格: {bp.klu.close:.2f}, 类型: {bp.type2str()}")
            
        except Exception as e:
            print(f"分析股票 {code} 失败: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_offline_scan()