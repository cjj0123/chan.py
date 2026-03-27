from futu import *

def check_balance():
    trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
    acc_id = 17278685
    ret, data = trd_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, refresh_cache=True)
    if ret == RET_OK:
        row = data.iloc[0]
        print(f"Account: {acc_id}")
        print(f"Cash: {row['cash']}")
        print(f"Total Assets: {row['total_assets']}")
        print(f"Market Value: {row['market_val']}")
    else:
        print(f"Failed to query account: {data}")
    trd_ctx.close()

if __name__ == "__main__":
    check_balance()
