from futu import *

def check_df_columns():
    trd_ctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
    ret, data = trd_ctx.get_acc_list()
    if ret == RET_OK:
        for _, row in data.iterrows():
            if row['trd_env'] == 'SIMULATE':
                acc_id = row['acc_id']
                print(f"\n===== Account: {acc_id} ({row['sim_acc_type']}) =====")
                
                # Check AccInfo Columns
                ret_a, data_a = trd_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
                if ret_a == RET_OK:
                    print(f"AccInfo Columns: {data_a.columns.tolist()}")
                    if not data_a.empty:
                        print(f"Sample AccInfo: {data_a.iloc[0].to_dict()}")
                
                # Check Position Columns
                ret_p, data_p = trd_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
                if ret_p == RET_OK:
                    print(f"Position Columns: {data_p.columns.tolist()}")
    trd_ctx.close()

if __name__ == "__main__":
    check_df_columns()
