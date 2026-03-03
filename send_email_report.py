#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发送股票扫描报告邮件（带图表图片）
支持从配置文件或环境变量加载邮件设置
"""

import smtplib
import os
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# 尝试从配置文件加载环境变量 (优化)
# 优先使用项目根目录下的 .env 文件
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')
# 其次尝试当前目录下的 email_config.env
load_dotenv(dotenv_path=Path(__file__).parent / 'email_config.env')

if os.getenv("SENDER_EMAIL"):
    print("✅ 已从 .env 或 email_config.env 加载邮件配置")


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
        
        # 发送邮件 - 使用 TLS 连接 (端口 587)
        # Gmail SMTP 配置：
        # - 端口 587: 使用 SMTP + starttls() 升级加密（推荐）
        # - 端口 465: 使用 SMTP_SSL 直接建立 SSL 连接
        # 错误"EOF occurred in violation of protocol"通常表示 SSL 握手失败
        # 可能原因：Gmail 需要应用专用密码 (App Password) 或 2FA 配置
        import ssl
        try:
            # 使用 TLS 连接 (端口 587) - 先建立普通连接，再升级 TLS
            server = smtplib.SMTP(smtp_server, 587, timeout=30)
            server.set_debuglevel(0)
            server.ehlo()
            # 使用系统默认的 SSL 上下文进行 TLS 升级
            server.starttls()
            server.ehlo()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [recipient_email], msg.as_string())
            server.quit()
            
            print(f"✅ 邮件已发送：{recipient_email}")
            return True
        except Exception as e:
            # TLS 失败，尝试 SSL (端口 465)
            print(f"⚠️ TLS 连接失败，尝试 SSL: {e}")
            try:
                ssl_context = ssl.create_default_context()
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                
                with smtplib.SMTP_SSL(smtp_server, 465, context=ssl_context, timeout=30) as server:
                    server.set_debuglevel(0)
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, [recipient_email], msg.as_string())
                
                print(f"✅ 邮件已发送：{recipient_email}")
                return True
            except Exception as ssl_error:
                print(f"❌ SSL 连接也失败：{ssl_error}")
                raise ssl_error from e
        
        print(f"✅ 邮件已发送：{recipient_email}")
        return True
        
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")
        import traceback
        traceback.print_exc()
        return False


def build_html_content(signals):
    """构建 HTML 邮件内容（支持移动端和图片显示）"""
    now = datetime.now()
    
    buy_signals = [s for s in signals if s.get('is_buy')]
    sell_signals = [s for s in signals if not s.get('is_buy')]
    
    html = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            /* 基础样式 */
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; line-height: 1.6; margin: 0; padding: 0; background-color: #f5f5f5; }}
            .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
            
            /* 头部样式 */
            .header {{ background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 25px 20px; text-align: center; }}
            .header h1 {{ margin: 0 0 10px 0; font-size: 24px; }}
            .header p {{ margin: 0; opacity: 0.9; font-size: 14px; }}
            
            /* 摘要卡片 */
            .summary {{ background: #ecf0f1; padding: 20px; margin: 20px; border-radius: 10px; }}
            .summary h2 {{ margin: 0 0 15px 0; font-size: 18px; color: #2c3e50; }}
            .summary p {{ margin: 8px 0; font-size: 14px; }}
            
            /* 信号卡片 */
            .signal {{ background: #fff; border: 1px solid #e0e0e0; margin: 15px; padding: 20px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }}
            .buy {{ border-left: 5px solid #27ae60; }}
            .sell {{ border-left: 5px solid #e74c3c; }}
            .signal h3 {{ margin: 0 0 15px 0; font-size: 18px; color: #2c3e50; }}
            .signal p {{ margin: 8px 0; font-size: 14px; color: #555; }}
            
            /* 评分样式 */
            .score {{ font-size: 20px; font-weight: bold; margin: 10px 0 !important; }}
            .score-high {{ color: #27ae60; }}
            .score-medium {{ color: #f39c12; }}
            .score-low {{ color: #e74c3c; }}
            
            /* 图表样式 */
            .chart {{ text-align: center; margin: 15px 0; padding: 15px; background: #f9f9f9; border-radius: 8px; }}
            .chart h4 {{ margin: 0 0 10px 0; font-size: 16px; color: #2c3e50; }}
            .chart img {{ max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 5px; margin: 10px 0; }}
            .chart p {{ font-size: 12px; color: #888; margin: 5px 0; }}
            
            /* 分析内容 */
            .analysis {{ background: #f8f9fa; padding: 12px; border-radius: 6px; margin-top: 10px; font-size: 13px; color: #444; line-height: 1.7; }}
            
            /* 移动端适配 */
            @media only screen and (max-width: 600px) {{
                .container {{ width: 100% !important; }}
                .header {{ padding: 20px 15px !important; }}
                .header h1 {{ font-size: 20px !important; }}
                .summary {{ margin: 10px !important; padding: 15px !important; }}
                .signal {{ margin: 10px !important; padding: 15px !important; }}
                .signal h3 {{ font-size: 16px !important; }}
                .score {{ font-size: 18px !important; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
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
        </div>
    </body>
    </html>
    """
    
    return html


def build_signal_html(signal, signal_type):
    """构建单个信号的 HTML（支持图片显示）"""
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
        <div class="analysis"><strong>分析：</strong> {analysis}</div>
    """
    
    # 添加图表（修复图片显示问题）
    if chart_paths:
        html += "<div class='chart'><h4>📊 图表分析</h4>"
        for chart_path in chart_paths:
            if os.path.exists(chart_path):
                filename = os.path.basename(chart_path)
                # 使用 CID 引用嵌入的图片
                html += f'<img src="cid:{filename}" alt="{filename}" />'
        html += "</div>"
    
    html += "</div>"
    
    return html


if __name__ == "__main__":
    # 测试邮件发送（带图片）
    print("测试邮件发送功能（带图片）...")
    
    # 使用实际的图表文件
    chart_30m = "/Users/jijunchen/Documents/Projects/Chanlun_Bot/charts_test/HK_00700_20260227_035540_30M.png"
    chart_5m = "/Users/jijunchen/Documents/Projects/Chanlun_Bot/charts_test/HK_00700_20260227_035540_5M.png"
    
    # 示例数据
    test_signals = [
        {
            'code': 'HK.00700',
            'stock_name': '腾讯控股',
            'is_buy': True,
            'bsp_type': 'b1',
            'score': 85,
            'current_price': 450.00,
            'visual_result': {
                'analysis': '30 分钟图显示清晰的底部背驰结构，5 分钟图提供区间套确认，买点质量高。'
            },
            'chart_paths': [chart_30m, chart_5m]
        }
    ]
    
    # 将所有图表路径收集到列表中
    all_chart_paths = []
    for signal in test_signals:
        all_chart_paths.extend(signal.get('chart_paths', []))
    
    send_stock_report(test_signals, all_chart_paths)
