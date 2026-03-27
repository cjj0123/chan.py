import futu
from futu import OpenQuoteContext, Market

ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

try:
    # 抽取 5 只香港主板查看列
    ret, data = ctx.get_plate_stock("HK.BK1910")
    if ret == 0:
         codes = data['code'].head(5).tolist()
         ret_s, df = ctx.get_market_snapshot(codes)
         if ret_s == 0:
              print("\n--- Snapshot Columns ---")
              print(df.columns.tolist())
              print("\nHead Data:")
              print(df.head(2).to_string())

except Exception as e:
    print(f"Exception: {e}")
finally:
    ctx.close()
