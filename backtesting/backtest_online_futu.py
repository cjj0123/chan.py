from typing import Iterable, List, Dict, Any
from datetime import datetime, timedelta
import os
import json
import argparse
import sys
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_SRC
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit
from DataAPI.FutuAPI import CFutuAPI
from visual_judge import VisualJudge
from config import TRADING_CONFIG
import time

# --- 核心参数 ---
TARGET_CODE = "HK.00700"  # 目标股票
BACKTEST_YEARS = 1  # 回测年限

def get_backtest_period(years: int) -> (str, str):
    """计算回测的起止日期 (YYYY-MM-DD)"""
    end_date = datetime.now().strftime('%Y-%m-%d')
    # 往前推一年 (365天)
    start_date = (datetime.now() - timedelta(days=years*365)).strftime('%Y-%m-%d')
    return start_date, end_date

def run_chan_backtest(stock_code: str, begin_date: str, end_date: str, visual_enabled: bool) -> Dict[str, Any]:
    """
    使用 CChan 逻辑进行回测，并根据 visual_enabled 标志决定是否纳入视觉评分。
    """
    start_time_run = time.time()
    print(f"\n🚀 [CHAN-BACKTEST] 启动回测: {stock_code}")
    print(f"   📅 周期: {begin_date} 至 {end_date}")
    print(f"   👁️ 视觉评分启用: {visual_enabled}")
    
    # 1. 缠论基础配置 
    config = CChanConfig({
        "bi_strict": True,
        "one_bi_zs": False,
        "seg_algo": "chan",
        "bs_type": TRADING_CONFIG['CHAN_CONFIG']['bs_type'],
    })

    # 2. 初始化 CChan (使用多级数据结构)
    try:
        chan = CChan(
            code=stock_code,
            begin_time=begin_date,
            end_time=end_date,
            data_src=DATA_SRC.FUTU,
            # 显式加载 30M 和 5M 级别
            lv_list=[KL_TYPE.K_30M, KL_TYPE.K_5M], 
            config=config,
            autype=AUTYPE.QFQ,
        )
        
        # 3. 运行 Chan 内部计算（获取所有 BSP 点）
        chan.load() 
        all_bsps = chan.get_bsp()
        
        # 4. 模拟交易和结果收集
        trades = []
        current_buy = None
        
        min_score_threshold = TRADING_CONFIG['min_visual_score']
        
        for bsp in all_bsps:
            # 基础缠论信号点作为潜在交易点
            if bsp.is_buy:
                if current_buy is None:
                    current_buy = {"price": bsp.klu.close, "time": str(bsp.klu.time), "type": bsp.type2str(), "bsp_obj": bsp}
            else:
                if current_buy is not None and bsp.time > current_buy['time']: 
                    
                    profit = (bsp.klu.close - current_buy['price']) / current_buy['price'] * 100
                    action = 'BLIND_TRADE' # 默认：基础缠论交易
                    strategy_type = "Blind"

                    if visual_enabled:
                        # 模拟视觉评估：使用 Mock 模式
                        judge = VisualJudge(use_mock=True)
                        # 模拟图表路径
                        mock_result = judge.evaluate([f"mock_30m_{bsp.klu.time}.png", f"mock_5m_{bsp.klu.time}.png"], signal_type=bsp.type2str())
                        
                        score = mock_result['score']
                        
                        if score >= min_score_threshold:
                            action = 'VISUAL_TRADE'
                            strategy_type = "Visual"
                        else:
                            action = 'VISUAL_REJECTED' # 视觉判断拒绝
                            strategy_type = "Visual_Rejected"
                            
                    
                    if action in ('BLIND_TRADE', 'VISUAL_TRADE'):
                        trades.append({
                            "buy_time": current_buy['time'],
                            "sell_time": str(bsp.klu.time),
                            "profit": profit,
                            "buy_type": current_buy['type'],
                            "sell_type": bsp.type2str(),
                            "strategy_type": strategy_type
                        })
                    
                    current_buy = None
        
        # 5. 结果统计
        stats = {
            "total_trades": 0,
            "total_profit_pct": 0.0,
            "win_trades": 0,
            "blind_trades": [],
            "visual_trades": []
        }
        
        stats["total_trades"] = len(trades)
        stats["blind_trades"] = [t for t in trades if t['strategy_type'] == 'Blind']
        stats["visual_trades"] = [t for t in trades if t['strategy_type'] == 'Visual']
        
        if stats["blind_trades"]:
            total_profit_blind = sum([t['profit'] for t in stats["blind_trades"]])
            win_rate_blind = len([t for t in stats["blind_trades"] if t['profit'] > 0]) / len(stats["blind_trades"]) * 100
            stats["total_profit_pct_blind"] = total_profit_blind
            stats["win_rate_blind"] = win_rate_blind
            
        if stats["visual_trades"]:
            total_profit_visual = sum([t['profit'] for t in stats["visual_trades"]])
            win_rate_visual = len([t for t in stats["visual_trades"] if t['profit'] > 0]) / len(stats["visual_trades"]) * 100
            stats["total_profit_pct_visual"] = total_profit_visual
            stats["win_rate_visual"] = win_rate_visual
            
        print(f"   ✅ 完成! 基础缠论信号对: {len(all_bsps) // 2} (包含未闭合)")
        end_time_run = time.time()
        print(f"   ⏱️ 耗时: {end_time_run - start_time_run:.2f} 秒")

        return stats

    except Exception as e:
        print(f"   ❌ 回测执行失败: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description='Chan Theory Backtesting Engine for Futu HK Stocks')
    parser.add_argument('--code', type=str, default=TARGET_CODE, help='Stock code (e.g., HK.00700)')
    parser.add_argument('--years', type=int, default=BACKTEST_YEARS, help='Number of years to backtest')
    
    # 允许覆盖默认的视觉评分启用状态
    parser.add_argument('--disable-visual', action='store_true', help='Run backtest without visual score filtering/validation')
    
    args = parser.parse_args()
    
    start_date, end_date = get_backtest_period(args.years)
    
    # --- 运行无视觉评分的回测 (Blind) ---
    print("\n" + "="*50)
    print("RUN 1: BLIND TEST (Only basic Chan Signal)")
    print("="*50)
    blind_stats = run_chan_backtest(
        stock_code=args.code, 
        begin_date=start_date, 
        end_date=end_date, 
        visual_enabled=False
    )
    
    # --- 运行有视觉评分的回测 (Visual) ---
    print("\n" + "="*50)
    print("RUN 2: VISUAL TEST (Chan Signal + Visual Judge Filter)")
    print("="*50)
    visual_stats = run_chan_backtest(
        stock_code=args.code, 
        begin_date=start_date, 
        end_date=end_date, 
        visual_enabled=True
    )

    # --- 结果汇总 ---
    print("\n" + "#"*60)
    print(f"## HK Stock Backtest Report for {args.code} ({args.years} Year(s)) ##")
    print("#"*60)
    
    if 'error' in blind_stats or 'error' in visual_stats:
        print("❌ 警告: 至少有一个回测运行失败，无法生成完整报告。")
        
    # 盲测结果
    if 'total_profit_pct_blind' in blind_stats and 'blind_trades' in blind_stats:
        print(f"\n[RESULTS: BLIND TRADING (No Visual Filter)]")
        print(f"  > 交易次数: {len(blind_stats['blind_trades'])}")
        print(f"  > 累计收益率: {blind_stats['total_profit_pct_blind']:.2f}%")
        print(f"  > 胜率: {blind_stats['win_rate_blind']:.2f}%")
    else:
        print(f"\n[RESULTS: BLIND TRADING] 无法获取有效数据或回测失败。")
        
    # 视觉测试结果
    if 'total_profit_pct_visual' in visual_stats and 'visual_trades' in visual_stats:
        print(f"\n[RESULTS: VISUAL TRADING (Visual Score >= {TRADING_CONFIG['min_visual_score']})]")
        print(f"  > 交易次数: {len(visual_stats['visual_trades'])}")
        print(f"  > 累计收益率: {visual_stats['total_profit_pct_visual']:.2f}%")
        print(f"  > 胜率: {visual_stats['win_rate_visual']:.2f}%")
    else:
        print(f"\n[RESULTS: VISUAL TRADING] 无法获取有效数据或回测失败。")

    print("\n" + "="*60)
    print("回测引擎执行完毕。")


if __name__ == "__main__":
    main()
