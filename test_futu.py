import pandas as pd
df = pd.read_parquet("stock_cache/HK.00700_K_DAY.parquet")
print(f"腾讯控股本地数据行数: {len(df)}")
print(f"数据时间范围: {df['time_key'].min()} 到 {df['time_key'].max()}")