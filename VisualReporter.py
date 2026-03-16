#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chanlun Bot 开发报告可视化工具 (VisualReporter.py)
"""
import os
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime

# 设置暗色调主题
sns.set_theme(style="dark")
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS']  # Mac 中文支持
plt.rcParams['axes.unicode_minus'] = False

DB_PATH = "/Volumes/存储/Chanlun_Bot_Data/chan_trading.db"
OUTPUT_DIR = "reports"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

class VisualReporter:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_signal_data(self):
        try:
            conn = sqlite3.connect(self.db_path)
            query = "SELECT stock_code, add_date, bstype FROM trading_signals"
            df = pd.read_sql_query(query, conn)
            conn.close()
            return df
        except Exception as e:
            print(f"读取信号错误: {e}")
            return pd.DataFrame()

    def plot_signal_heatmap(self):
        df = self.get_signal_data()
        if df.empty:
            print("⚠️ 没有信号数据，生成模拟热力图...")
            # 生成模拟数据以供演示
            stocks = ['US.AAPL', 'US.TSLA', 'US.NVDA', 'US.MSFT', 'US.AMZN']
            dates = pd.date_range(end=datetime.now(), periods=10).strftime('%Y-%m-%d')
            import numpy as np
            data = np.random.randint(0, 5, size=(len(stocks), len(dates)))
            df_pivot = pd.DataFrame(data, index=stocks, columns=dates)
        else:
            df['date'] = pd.to_datetime(df['add_date']).dt.strftime('%Y-%m-%d')
            df_pivot = df.pivot_table(index='stock_code', columns='date', aggfunc='size', fill_value=0)
            # 只取最近 20 条
            df_pivot = df_pivot.iloc[-10:, -15:]

        plt.figure(figsize=(12, 6))
        sns.heatmap(df_pivot, annot=True, cmap="YlGnBu", cbar_kws={'label': '信号频率'})
        plt.title("🔥 近期美股交易信号热力图", fontsize=15, pad=20)
        plt.xlabel("日期")
        plt.ylabel("股票代码")
        
        path = os.path.join(OUTPUT_DIR, "signal_heatmap.png")
        plt.savefig(path, bbox_inches='tight', dpi=150)
        print(f"✅ 热力图已保存: {path}")

    def plot_performance_curve(self):
        # 这是一个模拟累积收益曲线的演示
        plt.figure(figsize=(12, 5))
        dates = pd.date_range(start='2024-01-01', periods=100)
        import numpy as np
        returns = np.random.normal(0.001, 0.02, 100).cumsum()
        
        plt.plot(dates, returns, label='策略累积收益', color='#1f77b4', linewidth=2)
        plt.fill_between(dates, returns, alpha=0.2, color='#1f77b4')
        
        plt.title("📈 策略性能模拟展示 (PnL Curve)", fontsize=15)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.legend()
        
        path = os.path.join(OUTPUT_DIR, "performance_curve.png")
        plt.savefig(path, bbox_inches='tight', dpi=150)
        print(f"✅ 收益曲线已保存: {path}")

if __name__ == "__main__":
    reporter = VisualReporter(DB_PATH)
    print("🎨 正在生成专业视觉报告...")
    reporter.plot_signal_heatmap()
    reporter.plot_performance_curve()
    print("✨ 全部报告生成完毕！请查看 reports/ 目录。")
