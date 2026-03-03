#!/usr/bin/env python3
"""
测试 lot_size 计算功能
"""

from futu import OpenQuoteContext, RET_OK, TrdEnv
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_lot_size():
    """Test lot size calculation for different stocks"""
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    
    test_symbols = [
        'HK.00700',  # 腾讯 - 100 股/手
        'HK.00288',  # 万洲国际 - 1000 股/手
        'HK.09988',  # 阿里巴巴 - 100 股/手
        'HK.02580',  # 天齐锂业 - 100 股/手
    ]
    
    total_assets = 1000000  # 假设总资金 100 万
    max_position_ratio = 0.2  # 20% 仓位
    
    print("="*80)
    print("📊 Lot Size 计算测试")
    print("="*80)
    
    for symbol in test_symbols:
        try:
            # Get market snapshot
            ret_code, data = quote_ctx.get_market_snapshot(symbol)
            if ret_code != RET_OK:
                print(f"❌ {symbol} - 获取行情失败")
                continue
            
            current_price = float(data.iloc[0]['last_price'])
            
            # Get lot size
            ret_code, info = quote_ctx.get_stock_basicinfo(market='HK', code=symbol)
            if ret_code == RET_OK and not info.empty:
                lot_size = int(info.iloc[0]['lot_size'])
            else:
                lot_size = 100
            
            # Calculate investment amount (20% of total capital)
            investment_amount = total_assets * max_position_ratio
            
            # Calculate maximum quantity
            max_quantity = int(investment_amount / current_price)
            
            # Round down to nearest lot size
            quantity = (max_quantity // lot_size) * lot_size
            
            # Calculate actual investment
            actual_investment = quantity * current_price
            
            print(f"\n{symbol}:")
            print(f"   当前价格：{current_price:.2f} HKD")
            print(f"   每手股数：{lot_size} 股")
            print(f"   可用资金：{investment_amount:.2f} HKD (20% 仓位)")
            print(f"   最大可买：{max_quantity} 股")
            print(f"   实际买入：{quantity} 股 ({quantity // lot_size} 手)")
            print(f"   实际金额：{actual_investment:.2f} HKD")
            print(f"   剩余资金：{investment_amount - actual_investment:.2f} HKD")
            
        except Exception as e:
            print(f"❌ {symbol} - 错误：{e}")
    
    quote_ctx.close()
    print("\n" + "="*80)
    print("✅ 测试完成")
    print("="*80)

if __name__ == "__main__":
    test_lot_size()
