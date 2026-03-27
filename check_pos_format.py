from futu import *

def check_pos_format():
    trd_ctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
    acc_id = 17278685
    ret, data = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
    if ret == RET_OK and not data.empty:
        print(f"Position Code Sample: '{data.iloc[0]['code']}'")
        print(f"Full Position Row: {data.iloc[0].to_dict()}")
    trd_ctx.close()

if __name__ == "__main__":
    check_pos_format()
