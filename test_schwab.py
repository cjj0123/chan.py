import os
import json
import requests

def test_schwab_price_history():
    token_file = os.path.join(os.path.dirname(__file__), 'schwab_token.json')
    if not os.path.exists(token_file):
        print("❌ 找不到 schwab_token.json，请先完成授权。")
        return
        
    with open(token_file, 'r') as f:
        token_data = json.load(f)
        
    access_token = token_data.get('access_token')
    if not access_token:
        print("❌ Token 文件中没有 access_token。")
        return

    symbol = 'AAPL'
    # Schwab API params (using typical marketdata endpoint logic from Schwab)
    # https://developer.schwab.com/products/trader-api--individual/details/specifications/Market%20Data%20Production
    url = "https://api.schwabapi.com/marketdata/v1/pricehistory"
    
    params = {
        'symbol': symbol,
        'periodType': 'month',
        'period': 1,
        'frequencyType': 'daily',
        'frequency': 1,
        'needExtendedHoursData': 'false'
    }
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    print(f"⏳ 正在向嘉信理财 API 请求 {symbol} 的历史数据...")
    try:
        response = requests.get(url, headers=headers, params=params)
        print(f"HTTP 状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            if 'candles' in data:
                candles = data['candles']
                print(f"✅ 成功获取了 {len(candles)} 条 K 线数据！")
                if len(candles) > 0:
                    print("\n📊 示例数据 (第一条):")
                    from datetime import datetime
                    first = candles[0]
                    # datetime is usually in milliseconds
                    dt_str = datetime.fromtimestamp(first['datetime']/1000).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"  时间: {dt_str}")
                    print(f"  开盘: {first.get('open')} | 最高: {first.get('high')}")
                    print(f"  最低: {first.get('low')} | 收盘: {first.get('close')}")
                    print(f"  成交量: {first.get('volume')}")
            else:
                print("⚠️ 接口返回成功，但没有 'candles' 字段。")
                print(data)
        else:
            print(f"❌ 请求失败: {response.text}")
    except Exception as e:
        print(f"❌ 发生异常: {e}")

if __name__ == "__main__":
    test_schwab_price_history()
