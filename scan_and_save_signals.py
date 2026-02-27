#!/usr/bin/env python3
"""
午休扫描脚本 (12:01)
扫描并保存所有买卖信号，等待13:00开盘后执行
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


def scan_and_save():
    """午休扫描：收集所有买卖信号并保存"""
    logger.info("=" * 70)
    logger.info("🌙 午休扫描开始 (12:01) - 收集所有买卖信号")
    logger.info("=" * 70)
    
    try:
        trader = FutuHKVisualTrading(
            hk_watchlist_group="港股",
            min_visual_score=70,
            max_position_ratio=0.2,
            dry_run=False  # 实盘模式
        )
        
        # 收集所有信号
        all_signals = []
        
        watchlist_codes = trader.get_watchlist_codes()
        if not watchlist_codes:
            logger.warning("没有获取到自选股")
            return
        
        for code in watchlist_codes:
            logger.info(f"分析股票: {code}")
            
            stock_info = trader.get_stock_info(code)
            if not stock_info:
                continue
            
            current_price = stock_info['current_price']
            if current_price <= 0:
                continue
            
            chan_result = trader.analyze_with_chan(code)
            if not chan_result:
                continue
            
            is_buy = chan_result.get('is_buy_signal', False)
            bsp_type = chan_result.get('bsp_type', '未知')
            position_qty = trader.get_position_quantity(code)
            
            # 买入信号：检查是否已持仓
            if is_buy and position_qty > 0:
                logger.info(f"{code} 已有持仓({position_qty}股)，跳过买入")
                continue
            
            # 卖出信号：检查是否有持仓
            if not is_buy and position_qty <= 0:
                logger.info(f"{code} 无持仓，跳过卖出")
                continue
            
            chart_paths = trader.generate_charts(code, chan_result['chan_analysis']['chan_30m'])
            if not chart_paths:
                continue
            
            try:
                visual_result = trader.visual_judge.evaluate(chart_paths)
                score = visual_result.get('score', 0)
                
                logger.info(f"{code} 视觉评分: {score}/100 | 类型: {'买入' if is_buy else '卖出'}")
                
                if score >= 70:
                    signal_data = {
                        'code': code,
                        'is_buy': is_buy,
                        'bsp_type': bsp_type,
                        'score': score,
                        'price_at_scan': current_price,
                        'position_qty_at_scan': position_qty,
                        'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'chart_paths': chart_paths,
                        'visual_result': visual_result
                    }
                    all_signals.append(signal_data)
                    logger.info(f"✅ {code} {'买入' if is_buy else '卖出'}信号已收集 (评分: {score})")
                else:
                    logger.info(f"{code} 评分不足，放弃")
                    
            except Exception as e:
                logger.error(f"视觉评分异常 {code}: {e}")
                continue
        
        # 分离买卖信号并分别排序
        buy_signals = [s for s in all_signals if s['is_buy']]
        sell_signals = [s for s in all_signals if not s['is_buy']]
        
        buy_signals.sort(key=lambda x: x['score'], reverse=True)
        sell_signals.sort(key=lambda x: x['score'], reverse=True)
        
        # 合并：卖点优先，然后买点
        final_signals = sell_signals + buy_signals
        
        # 保存到文件
        with open(SIGNALS_FILE, 'w') as f:
            json.dump(final_signals, f, indent=2)
        
        logger.info("=" * 70)
        logger.info(f"📋 午休扫描完成")
        logger.info(f"   卖出信号: {len(sell_signals)} 个")
        logger.info(f"   买入信号: {len(buy_signals)} 个")
        logger.info(f"💾 信号已保存到: {SIGNALS_FILE}")
        logger.info("⏰ 将在 13:00 开盘后执行（卖点优先）")
        logger.info("=" * 70)
        
        for i, sig in enumerate(final_signals, 1):
            action = "买入" if sig['is_buy'] else "卖出"
            logger.info(f"  [{i}] {sig['code']} - {action} - 评分: {sig['score']}")
        
        trader.close_connections()
        
    except Exception as e:
        logger.error(f"午休扫描异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    scan_and_save()
