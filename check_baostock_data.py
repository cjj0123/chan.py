#!/usr/bin/env python3
import baostock as bs

bs.login()
rs = bs.query_history_k_data_plus('sh.600641', 'date,open,high,low,close', start_date='2026-02-01', end_date='2026-03-05', frequency='d', adjustflag='2')
print('Fields:', rs.fields)
count = 0
while rs.error_code == '0' and rs.next() and count < 10:
    print(rs.get_row_data())
    count += 1
bs.logout()