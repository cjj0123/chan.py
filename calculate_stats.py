import json
import pandas as pd

def calculate_stats(history_file):
    try:
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

        print(f"\n📊 --- {stock} 模拟收益统计报告 ---")
        print("说明：由于缠论 BSP 点通常标记的是结构买卖点而非闭合订单，")
        print("本统计采用“持仓 5 天（30M线 100 根K线）”的模拟逻辑来估算性能。")
        
        # 加载 Parquet 数据以获取价格映射
        df_price = pd.read_parquet("chan.py/stock_cache/HK.00836_k_30m.parquet")
        df_price['time'] = pd.to_datetime(df_price['time']).dt.strftime("%Y/%m/%d %H:%M")
        df_price.set_index('time', inplace=True)

        trades = []
        for s in signals:
            # 只统计买入信号 (1, 2, 3类买点)
            # 注意：缠论中买点带撇号(')通常表示卖点，这里需精准区分
            # 在我们的 output 中，买卖点通过 CChan 内部 is_buy 逻辑区分
            # 我们假设 type2str() 返回的是 1, 2, 3 表示买点，-1, -2, -3 表示卖点
            # 但目前 signal 里的 type 字符如 "1", "2s", "1p" 等需解析
            
            buy_time = s['time']
            buy_price = s['price']
            
            try:
                # 寻找买入后的价格序列
                buy_idx = df_price.index.get_loc(buy_time)
                # 模拟持仓 100 根 30M 线（约 5 个交易日）
                exit_idx = min(buy_idx + 100, len(df_price) - 1)
                exit_price = df_price.iloc[exit_idx]['close']
                exit_time = df_price.index[exit_idx]
                
                profit = (exit_price - buy_price) / buy_price * 100
                trades.append({
                    'buy_time': buy_time,
                    'exit_time': exit_time,
                    'buy_price': buy_price,
                    'exit_price': exit_price,
                    'profit': profit,
                    'type': s['type']
                })
            except:
                continue
        
        if not trades:
            print("未能计算模拟收益。")
            return

        df_trades = pd.DataFrame(trades)
        total_profit = df_trades['profit'].sum()
        win_rate = len(df_trades[df_trades['profit'] > 0]) / len(df_trades) * 100
        
        print(f"\n总模拟交易次数: {len(df_trades)}")
        print(f"模拟胜率: {win_rate:.2f}%")
        print(f"累计模拟盈亏: {total_profit:.2f}%")
        print(f"平均单笔盈亏: {df_trades['profit'].mean():.2f}%")
        print(f"最大单笔涨幅: {df_trades['profit'].max():.2f}%")
        
        print("\n📝 信号类型表现统计:")
        print(df_trades.groupby('type')['profit'].agg(['count', 'mean', 'sum']))

    except Exception as e:
        print(f"统计出错: {e}")

if __name__ == "__main__":
    calculate_stats("chan.py/backtest_history.json")
