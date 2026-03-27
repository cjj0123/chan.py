import sys
from futu import *
import yaml

def check_account():
    # Load config
    try:
        with open("Config/config.yaml", 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        host = config['futu']['host']
        port = config['futu']['port']
    except Exception:
        host = '127.0.0.1'
        port = 11111

    # Redirect output to file
    with open("sim_account_output.txt", "w", encoding='utf-8') as sys.stdout:
        print(f"Connecting to Futu OpenD at {host}:{port}...")
        trd_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=host, port=port)
        
        # 1. Get account list
        ret, data = trd_ctx.get_acc_list()
        if ret != RET_OK:
            print(f"Failed to get account list: {data}")
            trd_ctx.close()
            return

        print("\n=== [Futu Account List] ===")
        print(data[['acc_id', 'trd_env', 'sim_acc_type', 'card_num']])

        # Find simulation account
        matched = data[(data['trd_env'] == 'SIMULATE') & (data['sim_acc_type'] == 'STOCK')]
        if matched.empty:
            matched = data[(data['trd_env'] == 'SIMULATE') & 
                         ((data['sim_acc_type'] == 2) | (data['card_num'].str.contains('美国|US', case=False, na=False)))]

        if matched.empty:
            print("\n❌ No US Simulation Account found!")
            trd_ctx.close()
            return

        acc_id = int(matched.iloc[0]['acc_id'])
        print(f"\n🎯 Locked US Simulation Account ID: {acc_id}")

        # 2. Query Assets
        print("\n--- [Asset Info] ---")
        ret_asset, asset_data = trd_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
        if ret_asset == RET_OK:
            print(asset_data.to_string())
        else:
            print(f"Failed to get assets: {asset_data}")

        # 3. Query Positions
        print("\n--- [Positions List] ---")
        ret_pos, pos_data = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
        if ret_pos == RET_OK:
            if pos_data.empty:
                print("No positions found.")
            else:
                print(pos_data[['code', 'stock_name', 'qty', 'can_sell_qty', 'cost_price', 'nominal_price', 'market_val']].to_string())
        else:
            print(f"Failed to get positions: {pos_data}")

        # 4. Query Order List
        print("\n--- [Today Order List] ---")
        ret_order, order_data = trd_ctx.order_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
        if ret_order == RET_OK:
            if order_data.empty:
                print("No orders today.")
            else:
                print(order_data[['code', 'qty', 'price', 'order_status', 'dealt_qty', 'create_time']].to_string())
        else:
            print(f"Failed to get orders: {order_data}")

        trd_ctx.close()

if __name__ == "__main__":
    check_account()
