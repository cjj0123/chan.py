from futu import *

def check_code_refresh():
    trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
    acc_id = 17278685
    
    code = 'HK.09880'
    print(f"Refreshing specific code {code} with refresh_cache=True...")
    ret, data = trd_ctx.position_list_query(code=code, acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=True)
    print(f"Result for {code}: {ret}, {data[['code', 'qty', 'market_val']] if ret==0 and not data.empty else data}")
    
    trd_ctx.close()

if __name__ == "__main__":
    check_code_refresh()
