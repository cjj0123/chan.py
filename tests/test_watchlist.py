#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试脚本：列出 Futu OpenD 所有自选股组和股票"""

from futu import *

ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

print("=" * 80)
print("📋 Futu OpenD 自选股组列表")
print("=" * 80)

# 获取所有自选组
ret, groups_data = ctx.get_user_security_group()
if ret == RET_OK:
    print(f"✅ 找到 {len(groups_data)} 个自选股组:\n")
    
    for i, group_name in enumerate(groups_data['group_name'].tolist(), 1):
        print(f"{i}. 【{group_name}】")
        
        # 获取该组中的股票
        ret, stocks = ctx.get_user_security(group_name)
        if ret == RET_OK and len(stocks) > 0:
            # 分类统计
            hk_stocks = stocks[stocks['code'].str.startswith('HK.')]
            cn_stocks = stocks[stocks['code'].str.startswith('SH.') | stocks['code'].str.startswith('SZ.')]
            us_stocks = stocks[stocks['code'].str.startswith('US.')]
            
            print(f"   共 {len(stocks)} 只股票")
            if len(hk_stocks) > 0:
                print(f"   🇭🇰 港股：{len(hk_stocks)} 只 - {hk_stocks['code'].head(5).tolist()}{'...' if len(hk_stocks) > 5 else ''}")
            if len(cn_stocks) > 0:
                print(f"   🇨🇳 A 股：{len(cn_stocks)} 只 - {cn_stocks['code'].head(5).tolist()}{'...' if len(cn_stocks) > 5 else ''}")
            if len(us_stocks) > 0:
                print(f"   🇺🇸 美股：{len(us_stocks)} 只 - {us_stocks['code'].head(5).tolist()}{'...' if len(us_stocks) > 5 else ''}")
        else:
            print(f"   ⚠️ 无股票或获取失败")
        print()
else:
    print(f"❌ 获取自选组失败，错误码：{ret}")

ctx.close()

print("=" * 80)
print("✅ 测试完成")
print("=" * 80)
