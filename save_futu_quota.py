from futu import *

def check_quota():
    with open("quota_output.txt", "w") as f:
        try:
            quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            ret, data = quote_ctx.get_history_kl_quota(get_detail=True)
            if ret == RET_OK:
                f.write("\n=== Futu History K-line Quota ===\n")
                f.write(f"Data type: {type(data)}\n")
                f.write(str(data))
                f.write("\n")
            else:
                f.write(f"Failed to get quota: {data}\n")
            quote_ctx.close()
        except Exception as e:
            f.write(f"Error checking quota: {e}\n")

if __name__ == "__main__":
    check_quota()
