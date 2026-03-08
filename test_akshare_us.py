import akshare as ak
try:
    df = ak.stock_us_daily(symbol="AAPL", adjust="qfq")
    print(df.head())
    print("Columns:", df.columns.tolist())
except Exception as e:
    print("Error:", e)
