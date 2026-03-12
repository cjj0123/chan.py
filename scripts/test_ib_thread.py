import threading
from DataAPI.InteractiveBrokersAPI import CInteractiveBrokersAPI
from Common.CEnum import KL_TYPE
import os

def thread_task():
    code = "US.AAPL"
    print(f"🧵 [Thread] Starting download for {code} in a fresh thread...")
    try:
        api = CInteractiveBrokersAPI(code, k_type=KL_TYPE.K_DAY, begin_date="2026-03-01", end_date="2026-03-05")
        klines = list(api.get_kl_data())
        print(f"✅ [Thread] Success! Received {len(klines)} klines.")
    except Exception as e:
        print(f"❌ [Thread] Failed with error: {e}")

if __name__ == "__main__":
    os.environ["IB_HOST"] = "127.0.0.1"
    # Create a thread to mimic the GUI environment
    t = threading.Thread(target=thread_task)
    t.start()
    t.join()
