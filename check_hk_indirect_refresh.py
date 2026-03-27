from futu import *

def check_hk():
    trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
    ret_acc, acc_data = trd_ctx.get_acc_list()
    if ret_acc == RET_OK:
        for _, row in acc_data.iterrows():
            if row['trd_env'] == 'SIMULATE':
                acc_id = int(row['acc_id'])
                print(f"Testing Account: {acc_id}")
                
                # 1. Refresh via accinfo_query
                print("Refreshing via accinfo_query(refresh_cache=True)...")
                ret_a, data_a = trd_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=True)
                print(f"accinfo_query result: {ret_a}")
                
                # 2. Query positions WITHOUT refresh_cache=True
                print("Querying positions WITH refresh_cache=False...")
                ret_p, data_p = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=False)
                print(f"position_list_query result: {ret_p}")
                if ret_p == RET_OK:
                    if data_p.empty:
                        print("No positions found.")
                    else:
                        print(f"Found {len(data_p)} positions.")
                        print(data_p[['code', 'stock_name', 'qty']].to_string())
    trd_ctx.close()

if __name__ == "__main__":
    check_hk()
