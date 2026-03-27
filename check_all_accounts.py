import sys
from futu import *
import yaml

def check_hk_account():
    host = '127.0.0.1'
    port = 11111

    # Try OpenSecTradeContext instead of market-specific one to see all
    trd_ctx = OpenSecTradeContext(host=host, port=port)
    
    # 1. Get account list
    ret, data = trd_ctx.get_acc_list()
    if ret != RET_OK:
        print(f"Failed to get account list: {data}")
        trd_ctx.close()
        return

    print("\n=== [Futu Account List] ===")
    print(data[['acc_id', 'trd_env', 'sim_acc_type', 'card_num']])

    for _, row in data.iterrows():
        acc_id = int(row['acc_id'])
        env = TrdEnv.REAL if row['trd_env'] == 'REAL' else TrdEnv.SIMULATE
        print(f"\n🎯 Checking Account ID: {acc_id} Env: {row['trd_env']}")

        # 2. Query Assets
        print("\n--- [Asset Info] ---")
        ret_asset, asset_data = trd_ctx.accinfo_query(acc_id=acc_id, trd_env=env, refresh_cache=True)
        if ret_asset == RET_OK:
            print(asset_data.to_string())
        else:
            print(f"Failed to get assets: {asset_data}")

        # 3. Query Positions
        print("\n--- [Positions List] ---")
        # Try both without and with market
        ret_pos, pos_data = trd_ctx.position_list_query(acc_id=acc_id, trd_env=env, refresh_cache=True)
        if ret_pos == RET_OK:
            if pos_data.empty:
                print("No positions found.")
            else:
                print(pos_data[['code', 'stock_name', 'qty', 'can_sell_qty', 'cost_price', 'nominal_price', 'market_val']].to_string())
        else:
            print(f"Failed to get positions (no market): {pos_data}")
            
            # Try with market if it failed
            for mkt in [TrdMarket.HK, TrdMarket.US, TrdMarket.CN]:
                ret_pos2, pos_data2 = trd_ctx.position_list_query(acc_id=acc_id, trd_env=env, refresh_cache=True, trd_market=mkt)
                if ret_pos2 == RET_OK:
                    print(f"Positions for {mkt}:")
                    if pos_data2.empty:
                        print("Empty.")
                    else:
                        print(pos_data2[['code', 'stock_name', 'qty', 'can_sell_qty', 'cost_price', 'nominal_price', 'market_val']].to_string())
                else:
                    print(f"Failed for {mkt}: {pos_data2}")

    trd_ctx.close()

if __name__ == "__main__":
    check_hk_account()
