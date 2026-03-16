import os
import sys
import json
import base64
import requests
import urllib.parse
from dotenv import set_key, load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

def setup_schwab_auth():
    print("="*60)
    print("      Charles Schwab 嘉信理财 API 首次身份验证工具")
    print("="*60)
    
    app_key = os.getenv('SCHWAB_APP_KEY')
    app_secret = os.getenv('SCHWAB_APP_SECRET')
    
    if not app_key or not app_secret:
        print("💡 请准备好您的嘉信理财开发者门户的 App Key 和 App Secret。")
        app_key = input("👉 请输入您的 App Key (Client ID): ").strip()
        app_secret = input("👉 请输入您的 App Secret (Client Secret): ").strip()
        
        # Save to .env
        set_key(env_path, 'SCHWAB_APP_KEY', app_key)
        set_key(env_path, 'SCHWAB_APP_SECRET', app_secret)
        print("✅ App Key 和 App Secret 已保存到 .env 文件中。")
    else:
        print(f"✅ 从 .env 加载了 SCHWAB_APP_KEY: {app_key[:5]}...{app_key[-3:]}")

    redirect_uri = "https://127.0.0.1"
    
    # 1. 构造授权 URL
    auth_url_params = urllib.parse.urlencode({
        "client_id": app_key,
        "redirect_uri": redirect_uri
    })
    auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?{auth_url_params}"
    
    print("\n" + "-"*60)
    print("📌 步骤 1: 浏览器授权")
    print("请复制以下完整链接，并在浏览器中打开：")
    print(f"\n{auth_url}\n")
    print("⚠️ 注意：必须使用您的嘉信理财【交易账户凭据】登录，勾选需要授权的经纪账户并点击同意。")
    print("授权完成后，浏览器会重定向到一个类似 https://127.0.0.1/?code=... 的空白页面（或提示无法连接）。")
    print("-"*60 + "\n")
    
    # 2. 获取授权码
    redirected_url = input("👉 步骤 2: 请将重定向后浏览器地址栏中的【完整 URL】粘贴到此处:\n").strip()
    
    try:
        parsed_url = urllib.parse.urlparse(redirected_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        auth_code = query_params.get('code', [None])[0]
        
        if not auth_code:
            # 兼容截取 code= 后面全部字符的方法
            if 'code=' in redirected_url:
                auth_code = redirected_url.split('code=')[1].split('&')[0]
                # Schwab 授权码可能以 @ 结尾及包含特殊字符，需 urllib.parse.unquote
                auth_code = urllib.parse.unquote(auth_code)
            else:
                print("❌ 未在 URL 中找到授权码 (code)。请重新检查您的 URL。")
                return
                
        print(f"✅ 成功提取授权码。\n")
    except Exception as e:
        print(f"❌ 解析 URL 失败: {e}")
        return
        
    # 3. 交换令牌 (Token)
    print("⏳ 步骤 3: 正在向嘉信服务器请求 Token (Access & Refresh)...")
    
    token_url = "https://api.schwabapi.com/v1/oauth/token"
    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{app_key}:{app_secret}".encode()).decode(),
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri
    }
    
    try:
        response = requests.post(token_url, headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()
        
        access_token = token_data.get('access_token')
        refresh_token = token_data.get('refresh_token')
        
        if access_token and refresh_token:
            # Save to config or JSON file for the main application to use
            token_file = os.path.join(os.path.dirname(__file__), 'schwab_token.json')
            with open(token_file, 'w') as f:
                json.dump(token_data, f, indent=4)
                
            print("🚀 ===================================== 🚀")
            print("🎉 恭喜！嘉信理财 API 首次身份验证成功！🎉")
            print(f"✅ Token 已保存至: {token_file}")
            print("⏳ Access Token 有效期: 30 分钟。")
            print("⏳ Refresh Token 有效期: 7 天。")
            print("⚠️ 请记得：您需要每周手动运行 `python schwab_auth.py` 一次来重新刷新授权，因为嘉信不支持自动续期。")
            print("🚀 ===================================== 🚀")
        else:
            print("❌ 获取的 Token 格式不正确。")
            print(json.dumps(token_data, indent=2))
            
    except requests.exceptions.HTTPError as e:
        print(f"❌ 请求 Token 失败。HTTP 状态码: {e.response.status_code}")
        print(f"错误信息: {e.response.text}")
    except Exception as e:
        print(f"❌ 发生未知错误: {e}")


if __name__ == "__main__":
    setup_schwab_auth()
