from futu import *

def check_hk():
    trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
    ret_acc, acc_data = trd_ctx.get_acc_list()
    if ret_acc == RET_OK:
        for _, row in acc_data.iterrows():
            if row['trd_env'] == 'SIMULATE':
                acc_id = int(row['acc_id'])
                print(f"Testing Account: {acc_id}")
                ret, data = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=True)
                print(f"Result for refresh_cache=True: {ret}, {data}")
                
                ret2, data2 = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=False)
                print(f"Result for refresh_cache=False: {ret2}, {data2}")
    trd_ctx.close()

if __name__ == "__main__":
    check_hk()
