#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试邮件发送功能
用于诊断邮件发送失败的具体原因
"""

import os
import sys
import smtplib
import ssl
from pathlib import Path
from dotenv import load_dotenv

# 加载邮件配置
env_file = Path(__file__).parent / "email_config.env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ 已从 {env_file} 加载邮件配置")
else:
    print(f"❌ 配置文件不存在：{env_file}")
    sys.exit(1)

# 获取配置
smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
smtp_port = int(os.getenv("SMTP_PORT", "587"))
sender_email = os.getenv("SENDER_EMAIL", "")
sender_password = os.getenv("SENDER_PASSWORD", "")
recipient_email = os.getenv("RECIPIENT_EMAIL", sender_email)

print(f"\n📧 邮件配置:")
print(f"  SMTP 服务器：{smtp_server}:{smtp_port}")
print(f"  发送邮箱：{sender_email}")
print(f"  接收邮箱：{recipient_email}")
print(f"  密码长度：{len(sender_password) if sender_password else 0} 字符")

if not sender_email or not sender_password:
    print("\n❌ 邮件配置不完整，无法测试")
    print("请设置环境变量：SENDER_EMAIL, SENDER_PASSWORD")
    sys.exit(1)

# 测试 1: TLS 连接 (端口 587)
print("\n" + "="*60)
print("测试 1: TLS 连接 (端口 587)")
print("="*60)
try:
    server = smtplib.SMTP(smtp_server, smtp_port)
    server.set_debuglevel(1)
    print(f"✅ 成功连接到 {smtp_server}:{smtp_port}")
    
    server.starttls()
    print("✅ TLS 握手成功")
    
    server.login(sender_email, sender_password)
    print("✅ 登录成功")
    
    server.quit()
    print("✅ TLS 连接测试通过")
    tls_success = True
except smtplib.SMTPAuthenticationError as e:
    print(f"❌ 认证失败：{e}")
    print("   可能原因：密码错误或应用专用密码已失效")
    tls_success = False
except smtplib.SMTPConnectError as e:
    print(f"❌ 连接失败：{e}")
    print("   可能原因：SMTP 服务器不可达或端口被阻止")
    tls_success = False
except Exception as e:
    print(f"❌ 未知错误：{e}")
    import traceback
    traceback.print_exc()
    tls_success = False

# 测试 2: SSL 连接 (端口 465)
print("\n" + "="*60)
print("测试 2: SSL 连接 (端口 465)")
print("="*60)
try:
    context = ssl.create_default_context()
    server = smtplib.SMTP_SSL(smtp_server, 465, context=context)
    server.set_debuglevel(1)
    print(f"✅ 成功连接到 {smtp_server}:465 (SSL)")
    
    server.login(sender_email, sender_password)
    print("✅ 登录成功")
    
    server.quit()
    print("✅ SSL 连接测试通过")
    ssl_success = True
except smtplib.SMTPAuthenticationError as e:
    print(f"❌ 认证失败：{e}")
    print("   可能原因：密码错误或应用专用密码已失效")
    ssl_success = False
except smtplib.SMTPConnectError as e:
    print(f"❌ 连接失败：{e}")
    print("   可能原因：SMTP 服务器不可达或端口被阻止")
    ssl_success = False
except Exception as e:
    print(f"❌ 未知错误：{e}")
    import traceback
    traceback.print_exc()
    ssl_success = False

# 测试 3: 发送简单测试邮件
print("\n" + "="*60)
print("测试 3: 发送简单测试邮件")
print("="*60)

if not (tls_success or ssl_success):
    print("⚠️ 跳过此测试：连接测试失败")
else:
    try:
        from email.mime.text import MIMEText
        
        msg = MIMEText("这是一封测试邮件，用于验证邮件发送功能。", 'plain', 'utf-8')
        msg['Subject'] = '🧪 邮件发送测试'
        msg['From'] = sender_email
        msg['To'] = recipient_email
        
        if tls_success:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, [recipient_email], msg.as_string())
        else:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, 465, context=context) as server:
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, [recipient_email], msg.as_string())
        
        print(f"✅ 测试邮件已发送到：{recipient_email}")
        print("   请检查收件箱（包括垃圾邮件文件夹）")
    except Exception as e:
        print(f"❌ 发送失败：{e}")
        import traceback
        traceback.print_exc()

# 测试 4: 检查 send_email_report.py 的异常处理逻辑
print("\n" + "="*60)
print("测试 4: 检查 send_email_report.py 的异常处理逻辑")
print("="*60)

try:
    from send_email_report import send_stock_report
    
    # 测试不带图片的简单邮件
    test_signals = [
        {
            'code': 'TEST.001',
            'stock_name': '测试股票',
            'is_buy': True,
            'bsp_type': 'b1',
            'score': 85,
            'current_price': 100.00,
            'visual_result': {'analysis': '测试分析'}
        }
    ]
    
    print("尝试发送简单测试邮件（不带图片）...")
    result = send_stock_report(test_signals, [], subject="🧪 send_email_report 测试")
    
    if result:
        print("✅ send_email_report 测试通过")
    else:
        print("❌ send_email_report 返回 False，但未抛出异常")
except Exception as e:
    print(f"❌ send_email_report 测试失败：{e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("测试完成")
print("="*60)
