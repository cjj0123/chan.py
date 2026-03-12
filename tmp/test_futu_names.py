
from futu import OpenQuoteContext, Market, RET_OK
import os

def check_names(codes):
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    ret, data = quote_ctx.get_stock_basicinfo(Market.HK, codes)
    if ret == RET_OK:
        for _, row in data.iterrows():
            print(f"{row['code']}: {row['stock_name']}")
    else:
        print(f"Failed to get info: {data}")
    quote_ctx.close()

if __name__ == "__main__":
    check_names(['HK.00700', 'HK.00981', 'HK.00699', 'HK.09988', 'HK.02469'])
