#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易报告生成器。
负责将指标数据格式化为HTML报告并通过邮件发送。
"""

import os
import sys
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Template
import pandas as pd

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Config.EnvConfig import config
from Monitoring.metrics import CMetricsCalculator


class CReporter:
    """
    交易报告生成器。
    """

    def __init__(self):
        """
        初始化报告生成器，从配置中加载邮件设置。
        """
        self.email_config = config.get('email', {})
        self.smtp_server = self.email_config.get('smtp_server', 'smtp.gmail.com')
        self.smtp_port = self.email_config.get('smtp_port', 587)
        self.sender_email = self.email_config.get('sender_email', '')
        self.sender_password = self.email_config.get('sender_password', '')
        self.recipient_email = self.email_config.get('recipient_email', '')

    def _generate_html_report(self, metrics: dict, positions_df: pd.DataFrame, orders_df: pd.DataFrame) -> str:
        """
        使用Jinja2模板生成HTML报告。

        Args:
            metrics (dict): 性能指标字典。
            positions_df (pd.DataFrame): 当前持仓数据。
            orders_df (pd.DataFrame): 近期订单数据。

        Returns:
            str: 生成的HTML报告字符串。
        """
        # HTML报告模板
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>缠论港股交易系统 - 每日报告</title>
            <style>
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 20px;
                    background-color: #f8f9fa;
                }
                .container {
                    max-width: 1200px;
                    margin: 0 auto;
                    background-color: white;
                    padding: 20px;
                    border-radius: 10px;
                    box-shadow: 0 0 10px rgba(0,0,0,0.1);
                }
                .header {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    border-radius: 8px;
                    margin-bottom: 30px;
                    text-align: center;
                }
                .header h1 { margin: 0; font-size: 28px; }
                .header p { margin: 5px 0 0 0; opacity: 0.9; }
                
                .metrics-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 15px;
                    margin-bottom: 30px;
                }
                .metric-card {
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    text-align: center;
                    border-left: 4px solid #667eea;
                }
                .metric-value {
                    font-size: 24px;
                    font-weight: bold;
                    margin: 10px 0;
                }
                .metric-label {
                    color: #666;
                    font-size: 14px;
                }
                .positive { color: #28a745; }
                .negative { color: #dc3545; }
                .warning { color: #ffc107; }
                
                .section {
                    margin: 30px 0;
                    padding: 20px;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                }
                .section h2 {
                    color: #333;
                    margin-top: 0;
                    padding-bottom: 10px;
                    border-bottom: 2px solid #667eea;
                }
                
                table {
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                    font-size: 14px;
                }
                th, td {
                    border: 1px solid #dee2e6;
                    padding: 12px;
                    text-align: left;
                }
                th {
                    background-color: #f8f9fa;
                    font-weight: 600;
                    color: #495057;
                }
                tr:nth-child(even) { background-color: #f8f9fa; }
                tr:hover { background-color: #e9ecef; }
                
                .footer {
                    text-align: center;
                    margin-top: 30px;
                    color: #6c757d;
                    font-size: 12px;
                    padding-top: 20px;
                    border-top: 1px solid #dee2e6;
                }
                
                @media (max-width: 768px) {
                    .metrics-grid { grid-template-columns: 1fr; }
                    .container { margin: 10px; padding: 15px; }
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>缠论港股交易系统 - 每日报告</h1>
                    <p>报告生成时间: {{ metrics.generated_at }}</p>
                    <p>统计周期: {{ metrics.period }}</p>
                </div>

                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-label">总盈亏 (P&L)</div>
                        <div class="metric-value {% if metrics.total_pnl >= 0 %}positive{% else %}negative{% endif %}">
                            ¥{{ "%.2f"|format(metrics.total_pnl) }}
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">胜率</div>
                        <div class="metric-value {% if metrics.win_rate >= 0.5 %}positive{% else %}negative{% endif %}">
                            {{ "%.2f%%"|format(metrics.win_rate * 100) }}
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">夏普比率</div>
                        <div class="metric-value {% if metrics.sharpe_ratio >= 1.0 %}positive{% elif metrics.sharpe_ratio >= 0.5 %}warning{% else %}negative{% endif %}">
                            {{ "%.2f"|format(metrics.sharpe_ratio) }}
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">最大回撤</div>
                        <div class="metric-value negative">
                            {{ "%.2f%%"|format(metrics.max_drawdown * 100) }}
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">信号总数</div>
                        <div class="metric-value">
                            {{ metrics.total_signals }}
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">已执行订单</div>
                        <div class="metric-value">
                            {{ metrics.total_orders }}
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">当前持仓</div>
                        <div class="metric-value">
                            {{ metrics.active_positions }}
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h2>📊 当前持仓详情</h2>
                    {% if positions_df.empty %}
                        <p style="text-align: center; color: #6c757d;">暂无持仓。</p>
                    {% else %}
                        <table>
                            <thead>
                                <tr>
                                    <th>股票代码</th>
                                    <th>数量</th>
                                    <th>平均成本 (¥)</th>
                                    <th>当前市值 (¥)</th>
                                    <th>盈亏 (%)</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for _, row in positions_df.iterrows() %}
                                <tr>
                                    <td><strong>{{ row['stock_code'] }}</strong></td>
                                    <td>{{ row['quantity'] }}</td>
                                    <td>{{ "%.2f"|format(row['avg_cost']) }}</td>
                                    <td>{{ "%.2f"|format(row.get('current_value', row['avg_cost'] * row['quantity'])) }}</td>
                                    <td class="{% if row.get('pnl_pct', 0) >= 0 %}positive{% else %}negative{% endif %}">
                                        {{ "%.2f%%"|format(row.get('pnl_pct', 0) * 100) }}
                                    </td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    {% endif %}
                </div>

                <div class="section">
                    <h2>📈 近期交易订单</h2>
                    {% if orders_df.empty %}
                        <p style="text-align: center; color: #6c757d;">近期无交易。</p>
                    {% else %}
                        <table>
                            <thead>
                                <tr>
                                    <th>股票代码</th>
                                    <th>方向</th>
                                    <th>价格 (¥)</th>
                                    <th>数量</th>
                                    <th>金额 (¥)</th>
                                    <th>状态</th>
                                    <th>时间</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for _, row in orders_df.iterrows() %}
                                <tr>
                                    <td><strong>{{ row['stock_code'] }}</strong></td>
                                    <td class="{% if row['side'] == 'BUY' %}positive{% else %}negative{% endif %}">
                                        {{ '买入' if row['side'] == 'BUY' else '卖出' }}
                                    </td>
                                    <td>{{ "%.2f"|format(row['price']) }}</td>
                                    <td>{{ row['quantity'] }}</td>
                                    <td>{{ "%.2f"|format(row['price'] * row['quantity']) }}</td>
                                    <td>{{ row['status'] }}</td>
                                    <td>{{ row['add_time'] }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    {% endif %}
                </div>

                <div class="footer">
                    <p>缠论港股交易系统 - 基于技术分析的自动化交易解决方案</p>
                    <p>本报告基于系统实际交易数据生成，仅供参考。</p>
                </div>
            </div>
        </body>
        </html>
        """

        template = Template(html_template)
        html_report = template.render(
            metrics=metrics,
            positions_df=positions_df,
            orders_df=orders_df
        )
        return html_report

    def send_daily_report(self, days: int = 7) -> bool:
        """
        生成并发送每日交易报告。

        Args:
            days (int): 用于计算指标的回溯天数。

        Returns:
            bool: 发送成功返回True，否则返回False。
        """
        try:
            # 1. 计算指标
            calculator = CMetricsCalculator()
            metrics = calculator.calculate_performance_metrics(days=days)
            positions_df = calculator.get_current_positions()
            orders_df = calculator.get_recent_orders(days=1)

            # 2. 生成HTML报告
            html_report = self._generate_html_report(metrics, positions_df, orders_df)

            # 3. 发送邮件
            if not self._send_email(html_report):
                print("警告：邮件发送失败。")
                return False

            print(f"每日报告已成功发送至 {self.recipient_email}")
            return True

        except Exception as e:
            print(f"生成或发送报告时发生错误: {e}")
            return False

    def _send_email(self, html_content: str) -> bool:
        """
        发送HTML邮件。

        Args:
            html_content (str): HTML邮件内容。

        Returns:
            bool: 发送成功返回True，否则返回False。
        """
        # 如果邮件配置为空，则跳过发送
        if not all([self.sender_email, self.sender_password, self.recipient_email]):
            print("邮件配置不完整，跳过发送。")
            return True

        try:
            # 创建邮件对象
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"缠论港股交易系统 - 每日报告 ({datetime.now().strftime('%Y-%m-%d')})"
            msg['From'] = self.sender_email
            msg['To'] = self.recipient_email

            # 添加HTML内容
            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(html_part)

            # 连接SMTP服务器并发送
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)

            return True

        except Exception as e:
            print(f"邮件发送失败: {e}")
            return False