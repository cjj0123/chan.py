import sys
import os

# Ensure the directory containing visual_judge.py and this script (chan.py/) is in the Python path
current_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, current_dir) # Add the directory where this script and visual_judge.py are located

try:
    from visual_judge import VisualJudge
    print("✅ Successfully imported VisualJudge from visual_judge module.")
except ImportError as e:
    print(f"Module import error: {e}. Please check Python path and file structure.")
    class VisualJudge:
        def __init__(self, use_mock=True):
            self.use_mock = use_mock
            print("WARNING: VisualJudge not available, using mock mode.")
        
        def evaluate(self, image_paths):
            print("   ⚠️ Mock Visual Scoring: No actual visual analysis performed.")
            return {"score": 50, "action": "WAIT", "analysis": "Visual scoring module not loaded.", "original_score": 5.0}


import subprocess
import time
from datetime import datetime, timedelta
import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


# --- Configuration ---
MAX_POSITION_RATIO = 0.2
SCAN_PERIOD_DEFAULT = KL_TYPE.K_30M
WATCHLIST_GROUP = "港股"
MIN_MARKET_CAP = 50

KL_TYPE_MAP = {
    KL_TYPE.K_30M: "30M",
    KL_TYPE.K_5M: "5M",
}

# --- Helper function for memo logging ---
def record_to_memo(message, memo_dir="memory"):
    if not os.path.exists(memo_dir):
        try:
            os.makedirs(memo_dir)
        except OSError as e:
            print(f"❌ Failed to create memo directory {memo_dir}: {e}")
            return
            
    memo_file_path = os.path.join(memo_dir, datetime.now().strftime("%Y-%m-%d") + ".md")
    try:
        with open(memo_file_path, "a", encoding='utf-8') as f:
            f.write(f"- {message}\n")
    except Exception as e:
        print(f"❌ Failed to write to memo file {memo_file_path}: {e}")

# --- Main Backtest Function ---
def run_backtest(code, begin_date_str, end_date_str, backtest_args=None):
    if backtest_args is None:
        backtest_args = {}
        
    print(f"🚀 开始回测 {code} ({begin_date_str} - {end_date_str}) [策略: 缠论+视觉评分]")

    default_chan_config_params = {
        "zs_combine": True,
        "zs_combine_mode": "zs",
        "bi_strict": True,
        "one_bi_zs": False,
        "seg_algo": "chan",
        "divergence_rate": 0.9,
        "min_zs_cnt": 1,
        "max_bs2_rate": 0.618,
        "bs1_peak": True,
        "macd_algo": "peak",
        "bs_type": "1,1p,2,2s,3a,3b",
        "bsp2_follow_1": True,
        "bsp3_follow_1": True,
        "bsp3_peak": False,
        "bsp2s_follow_2": False,
        "strict_bsp3": False,
        "bsp3a_max_zs_cnt": 1,
    }
    chan_config_params = {**default_chan_config_params, **backtest_args.get("chan_config", {})}
    config = CChanConfig(chan_config_params)

    current_scan_period = backtest_args.get("scan_period", SCAN_PERIOD_DEFAULT)
    period_str = KL_TYPE_MAP.get(current_scan_period)
    if not period_str:
        print(f"❌ 无法处理的 K 线周期 {current_scan_period}。")
        return

    kl_units = force_load_data(code, current_scan_period)
    if not kl_units:
        print(f"❌ 无法从 stock_cache 目录加载 {code} 的数据。")
        return
    
    CCustomParquetAPI._cached_kl_units = kl_units

    chan = CChan(
        code=code,
        begin_time=begin_date_str,
        end_date_str=end_date_str,
        data_src="custom:CustomParquetAPI.CCustomParquetAPI",
        lv_list=[current_scan_period],
        config=config,
        autype=AUTYPE.QFQ,
    )

    trades = []
    current_position = None 
    stop_loss_rate = -0.05 

    processed_signals_this_run = set()

    try:
        processed_klines_list = chan[0]
        if not processed_klines_list or len(processed_klines_list) == 0:
            print(f"❌ 未加载到 {code} 的 K 线数据，无法进行回测。")
            return

        print(f"✅ 数据加载完成 ({len(processed_klines_list)} 根 K 线)，正在扫描信号...")

        all_bs_points_by_time = {}
        for bsp in processed_klines_list.bs_point_lst.getSortedBspList():
            time_str = bsp.klu.time.to_str()
            if time_str not in all_bs_points_by_time:
                all_bs_points_by_time[time_str] = []
            all_bs_points_by_time[time_str].append(bsp)

        for klc in processed_klines_list:
            current_klc_time = klc.time_end
            current_klc_close = klc.lst[-1].close

            if current_position:
                buy_price, buy_time = current_position
                current_profit_rate = (current_klc_close - buy_price) / buy_price
                if current_profit_rate <= stop_loss_rate:
                    trades.append({
                        "entry_time": buy_time, "entry_price": buy_price,
                        "exit_time": current_klc_time, "exit_price": current_klc_close,
                        "profit_loss_rate": current_profit_rate, "exit_reason": "Stop Loss"
                    })
                    current_position = None
                    print(f"   🛑 [{current_klc_time.to_str()}] 止损出场 | 盈亏: {current_profit_rate:.2%}")
                    continue

            klc_signals = all_bs_points_by_time.get(current_klc_time.to_str(), [])
            for bsp in klc_signals:
                signal_type_str = bsp.type2str()
                signal_key = (code, signal_type_str)

                if not current_position and bsp.is_buy:
                    if signal_type_str in [BSP_TYPE.T1.value, BSP_TYPE.T2.value, BSP_TYPE.T2S.value]:
                        if signal_key not in processed_signals_this_run:
                            image_timestamp_str = current_klc_time.to_str()
                            kline_period_str = KL_TYPE_MAP.get(current_scan_period, "30M")

                            img_paths_to_check = [
                                f"charts_cn_scan/{code}_{image_timestamp_str}_{kline_period_str}.png",
                                f"charts_cn_scan/{code}_{image_timestamp_str}_5M.png"
                            ]
                            
                            existing_image_paths = [path for path in img_paths_to_check if os.path.exists(path)]

                            if not existing_image_paths:
                                print(f"⚠️ No chart images found for {code} ({image_timestamp_str}, {kline_period_str}). Skipping visual scoring.")
                                continue

                            visual_judge = VisualJudge(use_mock=False)
                            score_result = visual_judge.evaluate(existing_image_paths)

                            if score_result and score_result.get("action") == "BUY" and score_result.get("score", 0) >= 70:
                                current_position = (current_klc_close, current_klc_time)
                                print(f"   🟢 [{current_klc_time.to_str()}] 买入入场 ({signal_type_str}) @ {current_klc_close:.2f} (Visual Score: {score_result.get('score', 'N/A')})")
                                
                                memo_msg = f"BUY signal for {code} at {current_klc_close:.2f} on {current_klc_time.to_str()}. Chanlun: {signal_type_str}, Visual Score: {score_result.get('score', 'N/A')}. Analysis: {score_result.get('analysis', '')}"
                                record_to_memo(memo_msg)
                                
                                processed_signals_this_run.add(signal_key)
                                break 
                            else:
                                print(f"ℹ️ Visual score criteria not met for {code} ({signal_type_str}). Score: {score_result.get('score', 'N/A')}, Action: {score_result.get('action', 'N/A')}. Skipping order.")
                        else:
                            print(f"ℹ️ [Skipped] {code} {signal_type_str} signal already processed this run.")
                    
                elif current_position and not bsp.is_buy:
                    buy_price, buy_time = current_position
                    current_profit_rate = (current_klc_close - buy_price) / buy_price
                    
                    trades.append({
                        "entry_time": buy_time, "entry_price": buy_price,
                        "exit_time": current_klc_time, "exit_price": current_klc_close,
                        "profit_loss_rate": current_profit_rate, "exit_reason": f"Sell ({signal_type_str})"
                    })
                    print(f"   🔴 [{current_klc_time.to_str()}] 卖点出场 ({signal_type_str}) | 盈亏: {current_profit_rate:.2%}")
                    current_position = None 

    except Exception as e:
        print(f"回测过程中发生错误: {e}")
        
    # --- Report Summary ---
    print("\n--- 回测总结 ---")
    if not trades and not current_position:
        print("未找到任何交易。")
    else:
        winning_trades = [t for t in trades if t.get("profit_loss_rate", 0) > 0]
        total_pnl_rate = sum([t.get("profit_loss_rate", 0) for t in trades])
        win_rate = len(winning_trades) / len(trades) if trades else 0
        
        print(f"交易总数: {len(trades)}")
        print(f"胜率: {win_rate:.2%}")
        print(f"总盈亏: {total_pnl_rate:.2%}")

        if total_trades == 0:
            print("\n⚠️ 指标计算限制: 由于没有交易数据，无法计算夏普比率和最大回撤。")
        else:
            print("\n⚠️ 指标计算限制: 夏普比率和最大回撤的精确计算需要完整的每日净值曲线，目前仅根据交易列表估算，可能不完全准确。")

    # --- Record Summary to MEMORY.md ---
    memo_summary = f"Backtest for {code} ({begin_date_str} to {end_date_str}): Total Trades={len(trades)}, Win Rate={win_rate:.2%}, Total P/L={total_pnl_rate:.2%}. Visual Scoring enabled (>=70 score for BUY)."
    record_to_memo(memo_summary, memo_dir="memory")


if __name__ == "__main__":
    # --- Argument Parsing ---
    stock_code_arg = "HK.00836"
    begin_date_str_arg = "2025-11-24"
    end_date_str_arg = "2026-02-24"

    if len(sys.argv) > 1:
        stock_code_arg = sys.argv[1]
    if len(sys.argv) > 2:
        begin_date_str_arg = sys.argv[2]
    if len(sys.argv) > 3:
        end_date_str_arg = sys.argv[3]

    # --- Main Execution ---
    backtest_config = {
        "scan_period": KL_TYPE.K_30M, 
    }

    run_backtest(
        code=stock_code_arg,
        begin_date_str=begin_date_str_arg,
        end_date_str=end_date_str_arg,
        backtest_args=backtest_config
    )

    print("\n--- 回测脚本执行完成 ---")
