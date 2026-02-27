#!/usr/bin/env python3
"""
下午开盘执行脚本 (13:00)
执行午休期间保存的所有买卖信号（卖点优先）
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, '/Users/jijunchen/.openclaw/workspace/chan.py')

from futu_hk_visual_trading_fixed import FutuHKVisualTrading
import logging

# 信号保存文件
SIGNALS_FILE = '/Users/jijunchen/.openclaw/workspace/chan.py/pending_signals.json'

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def execute_pending():
    """执行午休保存的所有信号（卖点优先）"""
    logger.info("=" * 70)
    logger.info("☀️ 下午开盘执行开始 (13:00) - 执行午休收集的信号")
    logger.info("=" * 70)
    
    # 检查是否有待执行信号
    if not os.path.exists(SIGNALS_FILE):
        logger.info("📭 没有待执行的信号")
        return
    
    try:
        with open(SIGNALS_FILE, 'r') as f:
            pending_signals = json.load(f)
    except Exception as e:
        logger.error(f"读取信号文件失败: {e}")
        return
    
    if not pending_signals:
        logger.info("📭 信号列表为空")
        return
    
    logger.info(f"📋 发现 {len(pending_signals)} 个待执行信号")
    
    try:
        trader = FutuHKVisualTrading(
            hk_watchlist_group="港股",
            min_visual_score=70,
            max_position_ratio=0.2,
            dry_run=False  # 实盘模式
        )
        
        available_funds = trader.get_available_funds()
        logger.info(f"💰 当前可用资金: {available_funds:.2f}")
        
        executed_buy = 0
        executed_sell = 0
        skipped_count = 0
        
        for i, signal in enumerate(pending_signals, 1):
            code = signal['code']
            is_buy = signal['is_buy']
            score = signal['score']
            scan_price = signal['price_at_scan']
            action_str = "买入" if is_buy else "卖出"
            
            logger.info(f"\n[{i}/{len(pending_signals)}] 处理: {code} - {action_str}")
            logger.info(f"   午休评分: {score} | 扫描价格: {scan_price}")
            
            # 获取最新价格和持仓
            stock_info = trader.get_stock_info(code)
            if not stock_info:
                logger.warning(f"   ❌ 无法获取 {code} 最新信息，跳过")
                skipped_count += 1
                continue
            
            current_price = stock_info['current_price']
            position_qty = trader.get_position_quantity(code)
            
            if is_buy:
                # 买入逻辑
                if position_qty > 0:
                    logger.info(f"   ⏭️ {code} 已有持仓({position_qty}股)，跳过买入")
                    skipped_count += 1
                    continue
                
                buy_quantity = trader.calculate_position_size(current_price, available_funds)
                if buy_quantity <= 0:
                    logger.warning(f"   ⚠️ 资金不足，跳过 {code}")
                    skipped_count += 1
                    continue
                
                required_funds = current_price * buy_quantity
                logger.info(f"   当前价格: {current_price} | 计划买入: {buy_quantity}股 | 预计花费: {required_funds:.2f}")
                
                if trader.execute_trade(code, 'BUY', buy_quantity, current_price):
                    logger.info(f"   ✅ 买入成功 {code}")
                    available_funds -= required_funds
                    executed_buy += 1
                else:
                    logger.error(f"   ❌ 买入失败 {code}")
                    skipped_count += 1
            else:
                # 卖出逻辑
                if position_qty <= 0:
                    logger.info(f"   ⏭️ {code} 已无持仓，跳过卖出")
                    skipped_count += 1
                    continue
                
                logger.info(f"   当前价格: {current_price} | 持仓: {position_qty}股 | 计划全仓卖出")
                
                if trader.execute_trade(code, 'SELL', position_qty, current_price):
                    logger.info(f"   ✅ 卖出成功 {code}")
                    released_funds = current_price * position_qty
                    available_funds += released_funds
                    executed_sell += 1
                else:
                    logger.error(f"   ❌ 卖出失败 {code}")
                    skipped_count += 1
        
        logger.info("\n" + "=" * 70)
        logger.info("📊 执行汇总")
        logger.info("=" * 70)
        logger.info(f"✅ 买入成功: {executed_buy} 个")
        logger.info(f"✅ 卖出成功: {executed_sell} 个")
        logger.info(f"⏭️ 跳过: {skipped_count} 个")
        logger.info(f"💰 最终可用资金: {available_funds:.2f}")
        
        # 清空信号文件
        with open(SIGNALS_FILE, 'w') as f:
            json.dump([], f)
        logger.info("🗑️ 已清空待执行信号列表")
        
        trader.close_connections()
        
    except Exception as e:
        logger.error(f"执行异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    execute_pending()
