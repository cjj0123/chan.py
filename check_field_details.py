from futu import *

def check_field_details():
    trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
    acc_id = 17278685
    # Force refresh everything
    trd_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=True)
    
    ret, data = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=False)
    if ret == RET_OK:
        print(data[['code', 'stock_name', 'qty', 'can_sell_qty', 'market_val', 'nominal_price']].to_string())
    else:
        print(f"Error: {data}")
    trd_ctx.close()

if __name__ == "__main__":
    check_field_details()
