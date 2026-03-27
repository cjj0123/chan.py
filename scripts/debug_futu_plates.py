import futu
from futu import OpenQuoteContext, Market

ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

try:
    plates = {
        "HK_Turnover": "HK.BK1018",      # 港股成交额排行
        "HK_Mainboard": "HK.BK1910",    # 港股主板
        "SH_Turnover": "SH.BK0973",      # 上证成交额 (Wait, is it?)
    }
    
    for name, code in plates.items():
        ret, data = ctx.get_plate_stock(code)
        if ret == 0:
            print(f"\n--- {name} ({code}) ---")
            print(f"Total Count: {len(data)}")
            if not data.empty:
                 print(data.head(10)[['code', 'stock_name']].to_string())
        else:
            print(f"Failed {name}: {data}")

except Exception as e:
    print(f"Exception: {e}")
finally:
    ctx.close()
