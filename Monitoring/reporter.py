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
                body { font-family: Arial, sans-serif; margin: 20px; }
                .header { background-color: #f4f4f4; padding: 10px; border-radius: 5px; }
                .metric { display: inline-block; margin: 10px; padding: 10px; background-color: #e9e9e9; border-radius: 5px; }
                table { width: 100%; border-collapse: collapse; margin: 20px 0; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                .positive { color: green; }
                .negative { color: red; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>缠论港股交易系统 - 每日报告</h1>
                <p>报告生成时间: {{ metrics.generated_at }}</p>
                <p>统计周期: {{ metrics.period }}</p>
            </div>

            <h2>核心性能指标</h2>
            <div class="metric">
                <strong>总盈亏 (P&L):</strong>
                <span class="{% if metrics.total_pnl >= 0 %}positive{% else %}negative{% endif %}">
                    {{ "%.2f"|format(metrics.total_pnl) }}
                </span>
            </div>
            <div class="metric">
                <strong>胜率:</strong> {{ "%.2f%%"|format(metrics.win_rate * 100) }}
            </div>
            <div class="metric">
                <strong>夏普比率:</strong> {{ "%.2f"|format(metrics.sharpe_ratio) }}
            </div>
            <div class="metric">
                <strong>最大回撤:</strong> 
                <span class="negative">{{ "%.2f%%"|format(metrics.max_drawdown * 100) }}</span>
            </div>
            <div class="metric">
                <strong>信号总数:</strong> {{ metrics.total_signals }}
            </div>
            <div class="metric">
                <strong>已执行订单:</strong> {{ metrics.total_orders }}
            </div>
            <div class="metric">
                <strong>当前持仓:</strong> {{ metrics.active_positions }}
            </div>

            <h2>当前持仓详情</h2>
            {% if positions_df.empty %}
                <p>暂无持仓。</p>
            {% else %}
                <table>
                    <thead>
                        <tr>
                            <th>股票代码</th>
                            <th>数量</th>
                            <th>平均成本</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for _, row in positions_df.iterrows() %}
                        <tr>
                            <td>{{ row['stock_code'] }}</td>
                            <td>{{ row['quantity'] }}</td>
                            <td>{{ "%.2f"|format(row['avg_cost']) }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            {% endif %}

            <h2>近期交易订单</h2>
            {% if orders_df.empty %}
                <p>近期无交易。</p>
            {% else %}
                <table>
                    <thead>
                        <tr>
                            <th>股票代码</th>
                            <th>方向</th>
                            <th>价格</th>
                            <th>数量</th>
                            <th>状态</th>
                            <th>时间</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for _, row in orders_df.iterrows() %}
                        <tr>
                            <td>{{ row['stock_code'] }}</td>
                            <td>{{ row['side'] }}</td>
                            <td>{{ "%.2f"|format(row['price']) }}</td>
                            <td>{{ row['quantity'] }}</td>
                            <td>{{ row['status'] }}</td>
                            <td>{{ row['add_time'] }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            {% endif %}
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