from futu import *
import time

def test_connection():
    try:
        quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        print("Connected to OpenD!")
        
        # Test a simple action
        ret, data = quote_ctx.get_market_snapshot(['HK.00700'])
        print(f" Snapshot ret: {ret}")
        print(f" Snapshot data: {data}")
        
        ret_kl, data_kl, page_token = quote_ctx.request_history_kline(
            'HK.00700',
            start='2025-03-01',
            end='2025-03-10',
            ktype=SubType.K_DAY
        )
        print(f" History K-Line ret: {ret_kl}")
        print(f" History K-Line data: {data_kl if ret_kl == RET_OK else 'Error'}")
        
        quote_ctx.close()
    except Exception as e:
        print(f"Connect failed: {e}")

if __name__ == "__main__":
    test_connection()
