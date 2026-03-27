import futu
from futu import OpenQuoteContext, SimpleFilter, StockField, SortDir, Market

ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

try:
    # 过滤器 1: 按 TURNOVER 降序
    f_turnover = SimpleFilter()
    f_turnover.stock_field = StockField.TURNOVER
    f_turnover.sort = 2  # DESCEND

    # 过滤器 2: 市值 > 15 亿
    f_cap = SimpleFilter()
    f_cap.stock_field = StockField.VALUE
    f_cap.filter_min = 1_500_000_000

    ret, filter_data = ctx.get_stock_filter(
        market=Market.HK,
        filter_list=[f_turnover, f_cap],
        begin=0,
        num=30
    )
    if ret == 0:
        item_list = filter_data[2]
        codes = [x.stock_code for x in item_list]
        print(f"Top 30 Codes from Filter: {codes}\n")

        # 批量抓取快照看细节
        ret_s, df = ctx.get_market_snapshot(codes)
        if ret_s == 0:
            cols = ['code', 'stock_name', 'turnover', 'cur_price', 'type', 'lot_size', 'suspension']
            # if 'market_cap' exists
            avail_cols = [c for c in cols if c in df.columns]
            if 'market_cap' in df.columns: avail_cols.append('market_cap')
            
            print(df[avail_cols].to_string())
        else:
            print(f"Snapshot Failed: {df}")
    else:
        print(f"Filter Failed: {filter_data}")

except Exception as e:
    print(f"Exception: {e}")
finally:
    ctx.close()
