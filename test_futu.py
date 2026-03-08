from futu import *
quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
ret, data, page = quote_ctx.request_history_kline('HK.00358', start='2026-03-07', end='2026-03-08', ktype=SubType.K_5M)
print(f"RET: {ret}")
print(f"LEN: {len(data) if data is not None else 0}")
quote_ctx.close()
