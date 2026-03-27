from futu import OpenHKTradeContext, TrdEnv, TrdMarket, RET_OK
import logging

def test_params():
    trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
    acc_id = 17278685
    
    params_to_test = [
        {'trd_market': TrdMarket.HK},
        {'market': TrdMarket.HK},
        {'position_market': TrdMarket.HK},
        {'trd_market': 'HK'},
        {'market': 'HK'},
    ]
    
    print(f"Testing account {acc_id} with refresh_cache=True...")
    
    for params in params_to_test:
        print(f"\nTrying params: {params}")
        try:
            ret, data = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=True, **params)
            print(f"Result: {ret}")
            if ret == RET_OK:
                print("✅ SUCCESS!")
                print(data)
                return params
            else:
                print(f"❌ Failed: {data}")
        except Exception as e:
            print(f"💥 Exception: {e}")
            
    trd_ctx.close()
    return None

if __name__ == "__main__":
    test_params()
