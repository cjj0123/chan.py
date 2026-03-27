from futu import *
import yaml

def check_history_orders():
    # Load config
    try:
        with open("Config/config.yaml", 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        host = config['futu']['host']
        port = config['futu']['port']
    except Exception:
        host = '127.0.0.1'
        port = 11111

    trd_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=host, port=port)
    
    # 1. Get account list
    ret, data = trd_ctx.get_acc_list()
    if ret != RET_OK:
         trd_ctx.close()
         return

    matched = data[(data['trd_env'] == 'SIMULATE') & (data['sim_acc_type'] == 'STOCK')]
    if matched.empty:
         trd_ctx.close()
         return

    acc_id = int(matched.iloc[0]['acc_id'])

    print(f"Locked US Simulation Account ID: {acc_id}")

    # 2. Query History Orders
    print("\n--- [History Orders List] ---")
    ret_order, order_data = trd_ctx.history_order_list_query(
        acc_id=acc_id, 
        start='2026-03-10', 
        end='2026-03-20', 
        trd_env=TrdEnv.SIMULATE
    )
    
    with open("history_orders_output.txt", "w", encoding='utf-8') as f:
        if ret_order == RET_OK:
            if order_data.empty:
                f.write("No history orders found.\n")
            else:
                f.write(order_data[['code', 'qty', 'price', 'order_status', 'dealt_qty', 'trd_side', 'create_time']].to_string())
        else:
            f.write(f"Failed to get history orders: {order_data}\n")

    trd_ctx.close()

if __name__ == "__main__":
    check_history_orders()
