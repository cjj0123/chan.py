import pandas as pd
from datetime import datetime
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_FIELD, BSP_TYPE, DATA_SRC
from Common.CTime import CTime
from backtest_direct import force_load_data
from DataAPI.CustomParquetAPI import CCustomParquetAPI

def run_backtest(code, begin_date_str, end_date_str):
    print(f"🚀 开始回测 {code} ({begin_date_str} - {end_date_str}) [大跨度+结构放宽模式]")

    # 缠论配置：放宽条件以增加买卖点数量
    config = CChanConfig({
        "zs_combine": True,
        "zs_combine_mode": "zs",
        "bi_strict": False, # 放宽成笔条件
        "one_bi_zs": True,  # 允许一笔成中枢，显著增加信号频率
        "seg_algo": "chan",
        "divergence_rate": 0.9,
        "min_zs_cnt": 1,
        "max_bs2_rate": 0.99,
        "bs1_peak": True,
        "macd_algo": "peak",
        "bs_type": "1,1p,2,2s,3a,3b",
        "print_warning": False,
    })

    # 加载 K 线数据
    kl_units = force_load_data(code, KL_TYPE.K_30M)
    if not kl_units:
        print("❌ 数据加载失败")
        return

    CCustomParquetAPI._cached_kl_units = kl_units

    # 创建CChan对象
    chan = CChan(
        code=code,
        begin_time=begin_date_str,
        end_time=end_date_str,
        data_src="custom:CustomParquetAPI.CCustomParquetAPI", 
        lv_list=[KL_TYPE.K_30M], 
        config=config,
        autype=AUTYPE.QFQ,
    )

    trades = []
    current_position = None
    stop_loss_rate = -0.05

    try:
        processed_klines_list = chan[0]
        if not processed_klines_list:
            return

        print(f"✅ 数据加载完成 ({len(processed_klines_list)} 根 K 线)，正在扫描信号...")

        # 映射买卖点
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
                current_profit = (current_klc_close - buy_price) / buy_price
                if current_profit <= stop_loss_rate:
                    trades.append({
                        "entry_time": buy_time, "entry_price": buy_price,
                        "exit_time": current_klc_time, "exit_price": current_klc_close,
                        "profit_loss_rate": current_profit, "exit_reason": "Stop Loss"
                    })
                    current_position = None
                    print(f"   🛑 [{current_klc_time.to_str()}] 止损出场 | 盈亏: {current_profit:.2%}")
                    continue

            klc_signals = all_bs_points_by_time.get(current_klc_time.to_str(), [])
            for bsp in klc_signals:
                if not current_position and bsp.is_buy:
                    if bsp.type2str() in [BSP_TYPE.T1.value, BSP_TYPE.T2.value, BSP_TYPE.T2S.value]:
                        current_position = (current_klc_close, current_klc_time)
                        print(f"   🟢 [{current_klc_time.to_str()}] 买入入场 ({bsp.type2str()}) @ {current_klc_close:.2f}")
                        break

                elif current_position and not bsp.is_buy:
                    buy_price, buy_time = current_position
                    current_profit = (current_klc_close - buy_price) / buy_price
                    trades.append({
                        "entry_time": buy_time, "entry_price": buy_price,
                        "exit_time": current_klc_time, "exit_price": current_klc_close,
                        "profit_loss_rate": current_profit, "exit_reason": f"Sell ({bsp.type2str()})"
                    })
                    current_position = None
                    print(f"   🔴 [{current_klc_time.to_str()}] 卖点出场 ({bsp.type2str()}) | 盈亏: {current_profit:.2%}")
                    break

    except Exception as e:
        print(f"回测异常: {e}")

    print("\n--- 回测总结 ---")
    if trades:
        win_trades = [t for t in trades if t["profit_loss_rate"] > 0]
        total_pnl = sum([t["profit_loss_rate"] for t in trades])
        print(f"交易总数: {len(trades)} | 胜率: {len(win_trades)/len(trades):.2%} | 总盈亏: {total_pnl:.2%}")
        print("\n--- 交易明细 ---")
        for t in trades:
            print(f"{t['entry_time'].to_str()} 买 -> {t['exit_time'].to_str()} 卖 | 盈亏: {t['profit_loss_rate']:.2%} | 原因: {t['exit_reason']}")
    else:
        print("无交易。")
        if current_position:
            print(f"持仓中: {current_position[1].to_str()} 买入 @ {current_position[0]:.2f}")

if __name__ == "__main__":
    # 时间范围延长到 2025 年底
    run_backtest(code="HK.00700", begin_date_str="2024-01-01", end_date_str="2025-12-31")
