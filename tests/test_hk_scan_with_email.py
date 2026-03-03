#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股实时扫描测试脚本
扫描港股自选股，发现缠论信号时发送邮件通知（带图表图片）
"""
import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from futu_hk_visual_trading_fixed import FutuHKVisualTrading
from send_email_report import send_stock_report
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def scan_hk_stocks_and_send_email(
    min_visual_score=70,
    max_signals=5,
    dry_run=True
):
    """
    扫描港股并发送邮件通知
    
    Args:
        min_visual_score: 最小视觉评分阈值
        max_signals: 最大信号数量
        dry_run: 是否为模拟盘模式
    """
    logger.info("=" * 70)
    logger.info("🔍 港股实时扫描测试 - 发现信号即发送邮件")
    logger.info("=" * 70)
    
    try:
        # 初始化交易器
        trader = FutuHKVisualTrading(
            hk_watchlist_group="港股",
            min_visual_score=min_visual_score,
            max_position_ratio=0.2,
            dry_run=dry_run
        )
        
        # 收集所有信号
        all_signals = []
        all_chart_paths = []
        
        # 获取自选股列表
        watchlist_codes = trader.get_watchlist_codes()
        if not watchlist_codes:
            logger.warning("⚠️ 没有获取到自选股列表")
            return False
        
        logger.info(f"📋 扫描 {len(watchlist_codes)} 只股票...")
        
        for code in watchlist_codes:
            logger.info(f"分析股票：{code}")
            
            # 获取股票信息
            stock_info = trader.get_stock_info(code)
            if not stock_info:
                continue
            
            current_price = stock_info.get('current_price', 0)
            if current_price <= 0:
                continue
            
            # 缠论分析
            chan_result = trader.analyze_with_chan(code)
            if not chan_result:
                continue
            
            is_buy = chan_result.get('is_buy_signal', False)
            bsp_type = chan_result.get('bsp_type', '未知')
            position_qty = trader.get_position_quantity(code)
            
            # 买入信号：检查是否已持仓
            if is_buy and position_qty > 0:
                logger.info(f"{code} 已有持仓 ({position_qty}股)，跳过买入")
                continue
            
            # 卖出信号：检查是否有持仓
            if not is_buy and position_qty <= 0:
                logger.info(f"{code} 无持仓，跳过卖出")
                continue
            
            # 生成图表
            chart_paths = trader.generate_charts(code, chan_result['chan_analysis']['chan_multi_level'])
            if not chart_paths:
                continue
            
            # 视觉评分
            try:
                visual_result = trader.visual_judge.evaluate(chart_paths)
                score = visual_result.get('score', 0)
                
                logger.info(f"{code} 视觉评分：{score}/100 | 类型：{'买入' if is_buy else '卖出'}")
                
                if score >= min_visual_score:
                    signal_data = {
                        'code': code,
                        'stock_name': stock_info.get('name', ''),
                        'is_buy': is_buy,
                        'bsp_type': bsp_type,
                        'score': score,
                        'current_price': current_price,
                        'position_qty': position_qty,
                        'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'chart_paths': chart_paths,
                        'visual_result': visual_result
                    }
                    all_signals.append(signal_data)
                    all_chart_paths.extend(chart_paths)
                    
                    logger.info(f"✅ {code} {'买入' if is_buy else '卖出'}信号已收集 (评分：{score})")
                else:
                    logger.info(f"{code} 评分不足，放弃")
                    
            except Exception as e:
                logger.error(f"视觉评分异常 {code}: {e}")
                continue
            
            # 增加1秒间隔，防止触发频率限制
            time.sleep(1)
        
        # 分离买卖信号并排序
        buy_signals = [s for s in all_signals if s['is_buy']]
        sell_signals = [s for s in all_signals if not s['is_buy']]
        
        buy_signals.sort(key=lambda x: x['score'], reverse=True)
        sell_signals.sort(key=lambda x: x['score'], reverse=True)
        
        # 限制信号数量
        buy_signals = buy_signals[:max_signals]
        sell_signals = sell_signals[:max_signals]
        
        # 合并：卖点优先，然后买点
        final_signals = sell_signals + buy_signals
        
        # 扫描摘要
        scan_summary = {
            'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_stocks': len(watchlist_codes),
            'total_signals': len(final_signals),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals)
        }
        
        logger.info("=" * 70)
        logger.info("📊 扫描完成")
        logger.info(f"   扫描股票数：{scan_summary['total_stocks']}")
        logger.info(f"   发现信号数：{scan_summary['total_signals']}")
        logger.info(f"   买入信号：{scan_summary['buy_signals']} 个")
        logger.info(f"   卖出信号：{scan_summary['sell_signals']} 个")
        logger.info("=" * 70)
        
        # 打印信号详情
        for i, sig in enumerate(final_signals, 1):
            action = "买入" if sig['is_buy'] else "卖出"
            logger.info(f"  [{i}] {sig['code']} - {sig['stock_name']} - {action} - 评分：{sig['score']} - 价格：{sig['current_price']:.2f}")
        
        # 发送邮
        if final_signals:
            logger.info("\n📧 正在发送邮件通知...")
            
            # 构建邮件主题
            now = datetime.now()
            subject = f"🎯 港股缠论信号 - {now.strftime('%Y-%m-%d %H:%M')} - 发现{len(final_signals)}个信号"
            
            # 发送邮件
            email_success = send_stock_report(final_signals, all_chart_paths, subject=subject)
            
            if email_success:
                logger.info("✅ 邮件发送成功")
            else:
                logger.warning("⚠️ 邮件发送失败")
        else:
            logger.info("\n📭 本次扫描未发现任何缠论信号")
            logger.info("   程序运行正常，系统处于监控状态。")
        
        trader.close_connections()
        
        return len(final_signals) > 0
        
    except Exception as e:
        logger.error(f"扫描异常：{e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("🔍 港股实时扫描测试")
    # 执行扫描并发送邮件
    has_signals = scan_hk_stocks_and_send_email(
        min_visual_score=70,
        max_signals=5,
        dry_run=True  # 模拟盘模式
    )

    print("=" * 70)

    # 强制发送一封测试邮件以进行调试
    print("\n📧 正在强制发送测试邮件以进行调试...")
    send_stock_report(
        signals=[{
            'code': 'HK.TEST', 'stock_name': '测试股票', 'is_buy': True, 
            'bsp_type': 'Test-b1', 'score': 99, 'current_price': 123.45,
            'visual_result': {'analysis': '这是一个调试邮件，用于验证邮件发送功能。'},
            'chart_paths': []
        }],
        chart_paths=[],
        subject="[调试] 港股扫描系统邮件功能测试"
    )
    
    print("\n" + "=" * 70)
    if has_signals:
        print("✅ 扫描完成，发现信号并已发送邮件")
    else:
        print("📭 扫描完成，未发现符合条件的信号")
    print("=" * 70)
