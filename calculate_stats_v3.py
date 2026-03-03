import json
import pandas as pd
import os

def calculate_stats(history_file, parquet_file):
    try:
        if not os.path.exists(history_file):
            print(f"找不到历史文件: {history_file}")
            return

        with open(history_file, 'r') as f:
            lines = f.readlines()
        
        if not lines:
            print("没有找到回测记录。")
            return

        last_run = json.loads(lines[-1])
        stock = last_run.get('stock', 'Unknown')
        signals = last_run.get('signals', [])
        
        if not signals:
            print(f"标的 {stock} 没有识别到交易信号。")
            return

        print(f"\n📊 --- {stock} 模拟收益统计报告 (2023-2026) ---")
        
        # 加载数据并标准化列名
        df_price = pd.read_parquet(parquet_file)
        df_price.columns = [c.lower() for c in df_price.columns]
        if 'time_key' in df_price.columns and 'time' not in df_price.columns:
            df_price.rename(columns={'time_key': 'time'}, inplace=True)
            
        df_price['time_str'] = pd.to_datetime(df_price['time']).dt.strftime("%Y/%m/%d %H:%M")
        df_price.set_index('time_str', inplace=True)

        trades = []
        for s in signals:
            buy_time = s['time']
            buy_price = float(s['price'])
            
            if buy_time not in df_price.index:
                continue
                
            try:
                # 定位买入点位置
                buy_idx = df_price.index.get_loc(buy_time)
                if isinstance(buy_idx, slice): # 处理重复索引
                    buy_idx = buy_idx.start
                
                # 模拟逻辑：持仓 100 根 K 线 (约 5 个交易日) 或直到数据结束
                exit_idx = min(buy_idx + 100, len(df_price) - 1)
                exit_price = float(df_price.iloc[exit_idx]['close'])
                exit_time = df_price.index[exit_idx]
                
                profit = (exit_price - buy_price) / buy_price * 100
                trades.append({
                    'buy_time': buy_time,
                    'exit_time': exit_time,
                    'profit': profit,
                    'type': s['type']
                })
            except Exception as e:
                continue
        
        if not trades:
            print("未能计算模拟收益。")
            return

        df_trades = pd.DataFrame(trades)
        total_profit = df_trades['profit'].sum()
        win_rate = len(df_trades[df_trades['profit'] > 0]) / len(df_trades) * 100
        
        print(f"信号总数: {len(signals)}")
        print(f"有效模拟交易: {len(df_trades)}")
        print(f"模拟胜率: {win_rate:.2f}%")
        print(f"累计模拟盈亏: {total_profit:.2f}%")
        print(f"平均单笔盈亏: {df_trades['profit'].mean():.2f}%")
        print(f"单笔最大收益: {df_trades['profit'].max():.2f}%")
        print(f"单笔最大亏损: {df_trades['profit'].min():.2f}%")
        
        print("\n📝 信号类型细分表现:")
        summary = df_trades.groupby('type')['profit'].agg(['count', 'mean', 'sum']).round(2)
        print(summary)

    except Exception as e:
        print(f"统计出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    calculate_stats("chan.py/backtest_history.json", "chan.py/stock_cache/HK.00836_k_30m.parquet")
