#!/usr/bin/env python3
"""
强制平仓所有持仓
用于 futu_sim_trading_enhanced.py 更新后清空现有仓位
"""

from futu import *
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def close_all_positions():
    """Close all positions"""
    logging.info("="*60)
    logging.info("🔄 开始强制平仓所有持仓")
    logging.info("="*60)
    
    # Initialize contexts
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    trade_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
    
    try:
        # Get all positions
        ret_code, data = trade_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
        if ret_code != RET_OK:
            logging.error(f"获取持仓失败：{data}")
            return
        
        if data.empty:
            logging.info("✅ 当前无持仓")
            return
        
        # Close each position
        closed_count = 0
        for _, row in data.iterrows():
            symbol = row['code']
            quantity = int(row['qty'])
            
            if quantity > 0:
                logging.info(f"\n📉 平仓 {symbol} - {quantity} 股...")
                
                # Place sell order (market price)
                ret_code, order_data = trade_ctx.place_order(
                    price=0,
                    qty=quantity,
                    code=symbol,
                    trd_side=TrdSide.SELL,
                    order_type=OrderType.MARKET,
                    trd_env=TrdEnv.SIMULATE
                )
                
                if ret_code == RET_OK:
                    logging.info(f"   ✅ 已提交平仓订单：{symbol} - {quantity} 股")
                    closed_count += 1
                else:
                    logging.error(f"   ❌ 平仓失败：{symbol} - {order_data}")
        
        logging.info("\n" + "="*60)
        logging.info(f"✅ 平仓完成：共平仓 {closed_count} 只股票")
        logging.info("="*60)
        
    except Exception as e:
        logging.error(f"平仓过程出错：{str(e)}")
    finally:
        quote_ctx.close()
        trade_ctx.close()

if __name__ == "__main__":
    close_all_positions()
