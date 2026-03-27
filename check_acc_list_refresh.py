from futu import *

def check_acc_list_refresh():
    trd_ctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
    # Refresh account list
    print("Refreshing account list via get_acc_list(refresh_cache=True)...")
    ret, data = trd_ctx.get_acc_list(refresh_cache=True)
    print(f"Result: {ret}")
    
    acc_id = 17278685
    print("Querying positions after list refresh...")
    ret, data_p = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=False)
    if ret == RET_OK:
        print(data_p[['code', 'qty', 'market_val']].to_string())
    
    trd_ctx.close()

if __name__ == "__main__":
    check_acc_list_refresh()
