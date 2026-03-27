import sys
from futu import *
import yaml

def check_hk_account():
    host = '127.0.0.1'
    port = 11111

    trd_ctx = OpenHKTradeContext(host=host, port=port)
    
    # 1. Get account list
    ret, data = trd_ctx.get_acc_list()
    if ret != RET_OK:
        print(f"Failed to get account list: {data}")
        trd_ctx.close()
        return

    print("\n=== [Futu HK Account List] ===")
    print(data[['acc_id', 'trd_env', 'sim_acc_type', 'card_num']])

    # Find simulation account
    matched = data[(data['trd_env'] == 'SIMULATE')]
    if matched.empty:
        print("\n❌ No HK Simulation Account found!")
        trd_ctx.close()
        return

    for _, row in matched.iterrows():
        acc_id = int(row['acc_id'])
        print(f"\n🎯 Checking HK Simulation Account ID: {acc_id}")

        # 2. Query Assets
        print("\n--- [Asset Info] ---")
        ret_asset, asset_data = trd_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=True)
        if ret_asset == RET_OK:
            print(asset_data.to_string())
        else:
            print(f"Failed to get assets: {asset_data}")

        # 3. Query Positions
        print("\n--- [Positions List] ---")
        ret_pos, pos_data = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=True)
        if ret_pos == RET_OK:
            if pos_data.empty:
                print("No positions found.")
            else:
                print(pos_data[['code', 'stock_name', 'qty', 'can_sell_qty', 'cost_price', 'nominal_price', 'market_val']].to_string())
        else:
            print(f"Failed to get positions: {pos_data}")

    trd_ctx.close()

if __name__ == "__main__":
    check_hk_account()
