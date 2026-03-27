from futu import *
import getpass

def check_unlock_refresh():
    trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
    # Note: For simulation, password is often empty or anything
    ret, data = trd_ctx.unlock_trade(password_md5='e10adc3949ba59abbe56e057f20f883e') # 123456
    print(f"Unlock result: {ret}, {data}")
    
    acc_id = 17278685
    print("Querying after unlock...")
    ret, data = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=False)
    if ret == RET_OK:
        print(data[['code', 'qty', 'market_val']].to_string())
    
    trd_ctx.close()

if __name__ == "__main__":
    check_unlock_refresh()
