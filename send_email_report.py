#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发送股票扫描报告邮件（带图表图片）
"""

import smtplib
import os
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime


def send_stock_report(signals, chart_paths, subject=None):
    """
    发送股票扫描报告邮件
    
    Args:
        signals: 信号列表，包含 code, stock_name, bsp_type, score, visual_result 等
        chart_paths: 图表文件路径列表
        subject: 邮件主题
    """
    try:
        # 邮件配置
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        sender_email = os.getenv("SENDER_EMAIL", "")
        sender_password = os.getenv("SENDER_PASSWORD", "")
        recipient_email = os.getenv("RECIPIENT_EMAIL", sender_email)
        
        if not sender_email or not sender_password:
            print("⚠️ 邮件配置不完整，跳过邮件发送")
            print("请设置环境变量：SENDER_EMAIL, SENDER_PASSWORD")
            return False
        
        if not subject:
            now = datetime.now()
            subject = f"🎯 A 股交易信号 - {now.strftime('%Y-%m-%d %H:%M')}"
        
        # 创建邮件
        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = recipient_email
        
        # 构建 HTML 内容
        html_content = build_html_content(signals)
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        # 附加图表图片
        for chart_path in chart_paths:
            if os.path.exists(chart_path):
                with open(chart_path, 'rb') as f:
                    img = MIMEImage(f.read())
                    img.add_header('Content-ID', f'<{os.path.basename(chart_path)}>')
                    img.add_header('Content-Disposition', 'inline', filename=os.path.basename(chart_path))
                    msg.attach(img)
        
        # 发送邮件
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [recipient_email], msg.as_string())
        
        print(f"✅ 邮件已发送：{recipient_email}")
        return True
        
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")
        return False


def build_html_content(signals):
    """构建 HTML 邮件内容"""
    now = datetime.now()
    
    buy_signals = [s for s in signals if s.get('is_buy')]
    sell_signals = [s for s in signals if not s.get('is_buy')]
    
    html = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
            .header {{ background: #2c3e50; color: white; padding: 20px; text-align: center; }}
            .summary {{ background: #ecf0f1; padding: 15px; margin: 20px 0; border-radius: 5px; }}
            .signal {{ border: 1px solid #ddd; margin: 15px 0; padding: 15px; border-radius: 5px; }}
            .buy {{ border-left: 5px solid #27ae60; }}
            .sell {{ border-left: 5px solid #e74c3c; }}
            .score {{ font-size: 24px; font-weight: bold; }}
            .score-high {{ color: #27ae60; }}
            .score-medium {{ color: #f39c12; }}
            .score-low {{ color: #e74c3c; }}
            .chart {{ text-align: center; margin: 10px 0; }}
            .chart img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🎯 A 股缠论视觉交易信号</h1>
            <p>扫描时间：{now.strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="summary">
            <h2>📊 扫描摘要</h2>
            <p><strong>总信号数：</strong> {len(signals)} 个</p>
            <p><strong>买入信号：</strong> {len(buy_signals)} 个</p>
            <p><strong>卖出信号：</strong> {len(sell_signals)} 个</p>
        </div>
    """
    
    # 买入信号
    if buy_signals:
        html += "<h2 style='color: #27ae60;'>✅ 买入信号</h2>"
        for signal in buy_signals:
            html += build_signal_html(signal, 'buy')
    
    # 卖出信号
    if sell_signals:
        html += "<h2 style='color: #e74c3c;'>❌ 卖出信号</h2>"
        for signal in sell_signals:
            html += build_signal_html(signal, 'sell')
    
    html += """
    </body>
    </html>
    """
    
    return html


def build_signal_html(signal, signal_type):
    """构建单个信号的 HTML"""
    code = signal.get('code', 'N/A')
    stock_name = signal.get('stock_name', '')
    bsp_type = signal.get('bsp_type', '未知')
    score = signal.get('score', 0)
    price = signal.get('current_price', 0)
    visual_result = signal.get('visual_result', {})
    analysis = visual_result.get('analysis', '')
    chart_paths = signal.get('chart_paths', [])
    
    # 评分颜色
    if score >= 80:
        score_class = 'score-high'
    elif score >= 60:
        score_class = 'score-medium'
    else:
        score_class = 'score-low'
    
    html = f"""
    <div class="signal {signal_type}">
        <h3>{code} {stock_name}</h3>
        <p><strong>信号类型：</strong> {bsp_type}</p>
        <p><strong>当前价格：</strong> {price:.2f}</p>
        <p class="score {score_class}">视觉评分：{score}/100</p>
        <p><strong>分析：</strong> {analysis}</p>
    """
    
    # 添加图表
    if chart_paths:
        html += "<div class='chart'><h4>📊 图表分析</h4>"
        for chart_path in chart_paths:
            if os.path.exists(chart_path):
                filename = os.path.basename(chart_path)
                html += f'<p>{filename}</p>'
                # 注意：实际发送时需要使用 CID 引用
                # html += f'<img src="cid:{filename}" alt="{filename}">'
        html += "</div>"
    
    html += "</div>"
    
    return html


if __name__ == "__main__":
    # 测试邮件发送
    print("测试邮件发送功能...")
    
    # 示例数据
    test_signals = [
        {
            'code': 'SH.600886',
            'stock_name': '国电南瑞',
            'is_buy': True,
            'bsp_type': 'b1',
            'score': 82,
            'current_price': 13.27,
            'visual_result': {
                'analysis': '趋势清晰，买点明确'
            },
            'chart_paths': []
        }
    ]
    
    send_stock_report(test_signals, [])
