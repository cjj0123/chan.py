from DataAPI.FutuAPI import CFutuAPI
from Common.CEnum import KL_TYPE, AUTYPE

def test_symbols():
    symbols = ['HK.09995', 'HK.09885', 'HK.02688', 'HK.00300']
    for sym in symbols:
        print(f"\n--- Testing {sym} ---")
        try:
            # Instantiate with daily K-line
            api = CFutuAPI(code=sym, k_type=KL_TYPE.K_DAY, begin_date='2025-02-01', end_date='2025-03-01', autype=AUTYPE.QFQ)
            # get_kl_data is a generator
            count = 0
            for item in api.get_kl_data():
                count += 1
                if count >= 3:
                     break
            print(f"✅ {sym}: Loaded {count} items")
        except Exception as e:
            print(f"❌ {sym} failed: {e}")

if __name__ == "__main__":
    test_symbols()
