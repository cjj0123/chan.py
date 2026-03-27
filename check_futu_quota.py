from futu import *

def check_quota():
    try:
        quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        ret, data = quote_ctx.get_history_kl_quota(get_detail=True)
        if ret == RET_OK:
            print("\n=== Futu History K-line Quota ===")
            print(f"Data type: {type(data)}")
            print(data)
        else:
            print(f"Failed to get quota: {data}")
        quote_ctx.close()
    except Exception as e:
        print(f"Error checking quota: {e}")

if __name__ == "__main__":
    check_quota()
