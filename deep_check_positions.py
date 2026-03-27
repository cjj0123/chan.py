from futu import *

def check_orders_and_positions():
    trd_ctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
    ret, data = trd_ctx.get_acc_list()
    if ret == RET_OK:
        for _, row in data.iterrows():
            if row['trd_env'] == 'SIMULATE':
                acc_id = int(row['acc_id'])
                print(f"\n===== Account: {acc_id} ({row['sim_acc_type']}) =====")
                
                # Force refresh account info
                trd_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=True)
                
                # Check Orders
                print("--- Today Orders ---")
                ret_o, data_o = trd_ctx.order_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
                if ret_o == RET_OK:
                    if data_o.empty:
                        print("No orders.")
                    else:
                        print(data_o[['code', 'stock_name', 'trd_side', 'order_status', 'dealt_qty', 'create_time']].to_string())
                
                # Check Positions
                print("--- Positions ---")
                # Try all markets
                for mkt in [TrdMarket.HK, TrdMarket.US, TrdMarket.CN]:
                    ret_p, data_p = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, trd_market=mkt)
                    if ret_p == RET_OK and not data_p.empty:
                        print(f"[{mkt}] Positions:")
                        print(data_p[['code', 'stock_name', 'qty', 'can_sell_qty']].to_string())
    trd_ctx.close()

if __name__ == "__main__":
    check_orders_and_positions()
