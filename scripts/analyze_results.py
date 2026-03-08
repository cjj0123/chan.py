#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测结果分析脚本
- 加载回测结果
- 生成可视化图表
- 统计分析
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestAnalyzer:
    """回测结果分析器"""
    
    def __init__(self, results_file: str):
        """
        初始化分析器
        
        Args:
            results_file: JSON 格式的回测结果文件
        """
        self.results = self._load_results(results_file)
        self.logger = logging.getLogger(__name__)
    
    def _load_results(self, filename: str) -> Dict:
        """加载回测结果"""
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def print_summary(self):
        """打印回测摘要"""
        print("\n" + "=" * 60)
        print("📊 回测结果摘要")
        print("=" * 60)
        
        # 基础信息
        print(f"\n📅 回测区间：{self.results.get('start_date', 'N/A')} 至 {self.results.get('end_date', 'N/A')}")
        print(f"💰 初始资金：{self.results.get('initial_funds', 0):,.2f} HKD")
        
        # 核心指标
        print("\n📈 核心绩效指标:")
        print(f"  • 期末总资产：{self.results.get('final_portfolio_value', 0):,.2f} HKD")
        print(f"  • 总回报率：{self.results.get('total_return_pct', 0) * 100:.2f}%")
        print(f"  • 年化回报率：{self.results.get('annualized_return', 0) * 100:.2f}%")
        print(f"  • 最大回撤：{self.results.get('max_drawdown_pct', 0) * 100:.2f}%")
        
        # 交易统计
        print("\n📝 交易统计:")
        print(f"  • 总交易次数：{self.results.get('trades_count', 0)}")
        print(f"  • 买入次数：{self.results.get('total_buys', 0)}")
        print(f"  • 卖出次数：{self.results.get('total_sells', 0)}")
        print(f"  • 胜率：{self.results.get('win_rate', 0) * 100:.2f}%")
        print(f"  • 盈亏比：{self.results.get('profit_loss_ratio', 0):.2f}")
        
        # 成本统计
        cost_stats = self.results.get('cost_statistics', {})
        if cost_stats:
            print("\n💰 交易成本:")
            print(f"  • 总成本：{cost_stats.get('total_cost', 0):,.2f} HKD")
            print(f"  • 佣金：{cost_stats.get('total_commission', 0):,.2f} HKD")
            print(f"  • 印花税：{cost_stats.get('total_stamp_duty', 0):,.2f} HKD")
        
        # 最终持仓
        positions = self.results.get('final_positions', {})
        if positions:
            print("\n📦 最终持仓:")
            for code, pos in positions.items():
                print(f"  • {code}: {pos.get('qty', 0):,} 股 @ {pos.get('avg_price', 0):.3f} HKD")
        else:
            print("\n📦 最终持仓：无")
        
        print("\n" + "=" * 60)
    
    def plot_equity_curve(self, output_file: str = "equity_curve.png"):
        """绘制资金曲线"""
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
            
            # 获取权益曲线数据
            equity_curve = self.results.get('equity_curve', [])
            
            if not equity_curve:
                logger.warning("⚠️ 无权益曲线数据")
                return
            
            df = pd.DataFrame(equity_curve)
            df['time'] = pd.to_datetime(df['time'])
            df = df.sort_values('time')
            df = df.drop_duplicates(subset=['time'], keep='last')
            df = df.reset_index(drop=True)
            
            # 创建图表 (Object-Oriented API)
            fig = Figure(figsize=(14, 8))
            
            # 设置中文字体
            import platform
            from matplotlib import rcParams
            if platform.system() == "Darwin":
                rcParams['font.sans-serif'] = ['Arial Unicode MS']
            elif platform.system() == "Windows":
                rcParams['font.sans-serif'] = ['SimHei']
            rcParams['axes.unicode_minus'] = False
            
            canvas = FigureCanvas(fig)
            axes = fig.subplots(2, 1, gridspec_kw={'height_ratios': [3, 1]})
            
            # 资金曲线
            ax1 = axes[0]
            ax1.plot(df['time'], df['value'], 'b-', linewidth=1.5, label='资产净值')
            ax1.fill_between(df['time'], df['value'].min(), df['value'], 
                            alpha=0.3, color='blue')
            ax1.set_title('资金曲线', fontsize=14)
            ax1.set_xlabel('时间')
            ax1.set_ylabel('资产净值 (HKD)')
            ax1.grid(True, alpha=0.3)
            ax1.legend()
            
            # 格式化 y 轴
            from matplotlib.ticker import FuncFormatter
            ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x:,.0f}'))
            
            # 回撤曲线
            ax2 = axes[1]
            df['peak'] = df['value'].cummax()
            df['drawdown'] = (df['value'] - df['peak']) / df['peak']
            ax2.fill_between(df['time'], df['drawdown'], 0, 
                            color='red', alpha=0.5, label='回撤')
            ax2.set_title('回撤分析', fontsize=14)
            ax2.set_xlabel('时间')
            ax2.set_ylabel('回撤 (%)')
            ax2.grid(True, alpha=0.3)
            ax2.legend()
            
            # 格式化 y 轴
            ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x*100:.1f}%'))
            
            fig.tight_layout()
            fig.savefig(output_file, dpi=150, bbox_inches='tight')
            
            logger.info(f"✅ 资金曲线已保存：{output_file}")
            
        except ImportError:
            logger.warning("⚠️ matplotlib 未安装，无法生成图表")
        except Exception as e:
            logger.error(f"❌ 绘制资金曲线失败：{e}")
    
    def plot_trade_distribution(self, output_file: str = "trade_distribution.png"):
        """绘制交易分布图"""
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
            
            # 获取交易记录
            trades = self.results.get('trade_log', [])
            
            if not trades:
                logger.warning("⚠️ 无交易记录")
                return
            
            df = pd.DataFrame(trades)
            
            # 按股票统计
            stock_trades = df.groupby('code').size().sort_values(ascending=False)
            
            # 创建图表 (Object-Oriented API)
            fig = Figure(figsize=(14, 5))
            
            # 设置中文字体
            import platform
            from matplotlib import rcParams
            if platform.system() == "Darwin":
                rcParams['font.sans-serif'] = ['Arial Unicode MS']
            elif platform.system() == "Windows":
                rcParams['font.sans-serif'] = ['SimHei']
            rcParams['axes.unicode_minus'] = False
            
            canvas = FigureCanvas(fig)
            axes = fig.subplots(1, 2)
            
            # 股票交易次数
            ax1 = axes[0]
            stock_trades.plot(kind='bar', ax=ax1, color='steelblue')
            ax1.set_title('各股票交易次数', fontsize=14)
            ax1.set_xlabel('股票代码')
            ax1.set_ylabel('交易次数')
            ax1.tick_params(axis='x', rotation=45)
            ax1.grid(True, alpha=0.3)
            
            # 买卖分布
            ax2 = axes[1]
            buy_count = len(df[df['action'] == 'BUY'])
            sell_count = len(df[df['action'] == 'SELL'])
            ax2.pie([buy_count, sell_count], labels=['买入', '卖出'], 
                   autopct='%1.1f%%', colors=['red', 'green'])
            ax2.set_title('买卖分布', fontsize=14)
            
            fig.tight_layout()
            fig.savefig(output_file, dpi=150, bbox_inches='tight')
            
            logger.info(f"✅ 交易分布图已保存：{output_file}")
            
        except Exception as e:
            logger.error(f"❌ 绘制交易分布图失败：{e}")
    
    def generate_analysis_report(self, output_file: str = "analysis_report.md"):
        """生成分析报告"""
        report = []
        report.append("# 回测结果分析报告\n")
        report.append(f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
        
        # 1. 执行摘要
        report.append("## 📋 1. 执行摘要\n")
        total_return = self.results.get('total_return_pct', 0) * 100
        if total_return > 20:
            report.append("✅ **优秀**: 策略表现优异，总回报率超过 20%")
        elif total_return > 0:
            report.append("👍 **盈利**: 策略实现盈利")
        elif total_return > -10:
            report.append("⚠️ **小幅亏损**: 策略亏损在可接受范围内")
        else:
            report.append("❌ **需要优化**: 策略表现不佳，需要调整参数")
        report.append("")
        
        # 2. 绩效分析
        report.append("## 📊 2. 绩效分析\n")
        report.append("| 指标 | 数值 |")
        report.append("|------|------|")
        report.append(f"| 总回报率 | {total_return:.2f}% |")
        report.append(f"| 年化回报率 | {self.results.get('annualized_return', 0) * 100:.2f}% |")
        report.append(f"| 最大回撤 | {self.results.get('max_drawdown_pct', 0) * 100:.2f}% |")
        report.append(f"| 胜率 | {self.results.get('win_rate', 0) * 100:.2f}% |")
        report.append(f"| 盈亏比 | {self.results.get('profit_loss_ratio', 0):.2f} |")
        report.append(f"| 夏普比率 | {self.results.get('sharpe_ratio', 0):.2f} |")
        report.append("")
        
        # 3. 风险评估
        report.append("## ⚠️ 3. 风险评估\n")
        max_dd = self.results.get('max_drawdown_pct', 0) * 100
        if max_dd > 30:
            report.append(f"🔴 **高风险**: 最大回撤达到 {max_dd:.1f}%，建议降低仓位")
        elif max_dd > 20:
            report.append(f"🟠 **中高风险**: 最大回撤为 {max_dd:.1f}%，需注意风险控制")
        elif max_dd > 10:
            report.append(f"🟡 **中等风险**: 最大回撤为 {max_dd:.1f}%，风险可控")
        else:
            report.append(f"🟢 **低风险**: 最大回撤为 {max_dd:.1f}%，风险控制良好")
        report.append("")
        
        # 4. 改进建议
        report.append("## 💡 4. 改进建议\n")
        suggestions = []
        
        if self.results.get('win_rate', 0) < 0.4:
            suggestions.append("- 胜率较低，建议优化入场信号或增加过滤条件")
        
        if self.results.get('profit_loss_ratio', 0) < 1.5:
            suggestions.append("- 盈亏比较低，建议优化止盈止损策略")
        
        if self.results.get('trades_count', 0) < 10:
            suggestions.append("- 交易次数过少，统计显著性不足，建议延长回测时间")
        
        if self.results.get('max_drawdown_pct', 0) > 0.2:
            suggestions.append("- 回撤较大，建议降低单票仓位比例")
        
        if suggestions:
            report.extend(suggestions)
        else:
            report.append("策略表现良好，暂无明显改进建议")
        
        report.append("")
        
        # 保存报告
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(report))
        
        logger.info(f"✅ 分析报告已保存：{output_file}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='回测结果分析工具')
    parser.add_argument('results_file', type=str, help='JSON 格式的回测结果文件')
    parser.add_argument('--output-dir', type=str, default='.', help='输出目录')
    parser.add_argument('--no-plots', action='store_true', help='不生成图表')
    
    args = parser.parse_args()
    
    # 创建分析器
    analyzer = BacktestAnalyzer(args.results_file)
    
    # 打印摘要
    analyzer.print_summary()
    
    # 生成图表
    if not args.no_plots:
        analyzer.plot_equity_curve(os.path.join(args.output_dir, 'equity_curve.png'))
        analyzer.plot_trade_distribution(os.path.join(args.output_dir, 'trade_distribution.png'))
    
    # 生成分析报告
    analyzer.generate_analysis_report(os.path.join(args.output_dir, 'analysis_report.md'))
    
    logger.info("✅ 分析完成")


if __name__ == '__main__':
    main()
