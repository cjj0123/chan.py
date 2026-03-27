from futu import *

def check_user_info():
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    ret, data = quote_ctx.get_global_state()
    if ret == RET_OK:
        print("=== Global State ===")
        print(data)
    else:
        print(f"Failed to get global state: {data}")
    
    ret_u, data_u = quote_ctx.get_user_info()
    if ret_u == RET_OK:
        print("\n=== User Info ===")
        print(data_u)
    else:
        print(f"Failed to get user info: {data_u}")
        
    quote_ctx.close()

if __name__ == "__main__":
    check_user_info()
