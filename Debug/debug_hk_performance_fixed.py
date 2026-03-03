#!/usr/bin/env python3
"""
港股扫描性能分析脚本（修复版）
详细测量各个阶段的耗时，确定性能瓶颈
"""

import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# 导入必要的模块
from futu_hk_visual_trading_fixed import FutuHKVisualTrading
from Chan import CChan, DATA_SRC
from Common.CEnum import KL_TYPE
from ChanConfig import CChanConfig


class HKPerformanceAnalyzer:
    def __init__(self):
        self.trader = FutuHKVisualTrading(dry_run=True)
        
    def analyze_kline_fetching(self, code: str, days: int = 30) -> Dict:
        """分析K线获取性能"""
        logger.info(f"=== 分析股票 {code} 的K线获取性能 ===")
        results = {}
        
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        # 测试30M数据获取
        logger.info("测试30M数据获取...")
        start_30m = time.time()
        try:
            chan_30m = CChan(
                code=code,
                begin_time=start_time.strftime("%Y-%m-%d"),
                end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                data_src=DATA_SRC.FUTU,
                lv_list=[KL_TYPE.K_30M],
                config=self.trader.chan_config
            )
            kline_30m_count = sum(1 for _ in chan_30m[0].klu_iter())
            time_30m = time.time() - start_30m
            results['30m'] = {
                'time': time_30m,
                'kline_count': kline_30m_count,
                'success': True
            }
            logger.info(f"30M: {time_30m:.2f}s, {kline_30m_count}根K线")
        except Exception as e:
            time_30m = time.time() - start_30m
            results['30m'] = {
                'time': time_30m,
                'error': str(e),
                'success': False
            }
            logger.error(f"30M获取失败: {e}")
        
        # 测试5M数据获取
        logger.info("测试5M数据获取...")
        start_5m = time.time()
        try:
            chan_5m = CChan(
                code=code,
                begin_time=start_time.strftime("%Y-%m-%d"),
                end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                data_src=DATA_SRC.FUTU,
                lv_list=[KL_TYPE.K_5M],
                config=self.trader.chan_config
            )
            kline_5m_count = sum(1 for _ in chan_5m[0].klu_iter())
            time_5m = time.time() - start_5m
            results['5m'] = {
                'time': time_5m,
                'kline_count': kline_5m_count,
                'success': True
            }
            logger.info(f"5M: {time_5m:.2f}s, {kline_5m_count}根K线")
        except Exception as e:
            time_5m = time.time() - start_5m
            results['5m'] = {
                'time': time_5m,
                'error': str(e),
                'success': False
            }
            logger.error(f"5M获取失败: {e}")
            
        # 测试同时获取（理论上会失败）
        logger.info("测试同时获取30M+5M...")
        start_both = time.time()
        try:
            chan_both = CChan(
                code=code,
                begin_time=start_time.strftime("%Y-%m-%d"),
                end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                data_src=DATA_SRC.FUTU,
                lv_list=[KL_TYPE.K_30M, KL_TYPE.K_5M],
                config=self.trader.chan_config
            )
            time_both = time.time() - start_both
            results['both'] = {
                'time': time_both,
                'success': True
            }
            logger.info(f"同时获取: {time_both:.2f}s (成功)")
        except Exception as e:
            time_both = time.time() - start_both
            results['both'] = {
                'time': time_both,
                'error': str(e),
                'success': False
            }
            logger.info(f"同时获取: {time_both:.2f}s (失败: {e})")
        
        return results
    
    def analyze_full_scan_performance(self, test_codes: List[str] = None) -> Dict:
        """分析完整扫描流程性能"""
        if test_codes is None:
            test_codes = self.trader.get_watchlist_codes()[:3]  # 只测试前3个股票
        
        logger.info(f"=== 完整扫描性能分析 (测试股票: {test_codes}) ===")
        
        total_start = time.time()
        
        # 阶段1: 收集候选信号
        stage1_start = time.time()
        candidate_signals = self.trader._collect_candidate_signals(test_codes)
        stage1_time = time.time() - stage1_start
        
        logger.info(f"阶段1 - 收集候选信号: {stage1_time:.2f}s, 找到 {len(candidate_signals)} 个信号")
        
        if not candidate_signals:
            logger.warning("没有找到候选信号，无法继续后续阶段测试")
            return {
                'total_time': time.time() - total_start,
                'stage1_time': stage1_time,
                'stage2_time': 0,
                'stage3_time': 0,
                'candidate_count': 0
            }
        
        # 阶段2: 生成图表
        stage2_start = time.time()
        signals_with_charts = self.trader._batch_generate_charts(candidate_signals)
        stage2_time = time.time() - stage2_start
        
        logger.info(f"阶段2 - 生成图表: {stage2_time:.2f}s, 成功 {len(signals_with_charts)} 个")
        
        # 阶段3: 评分（如果需要）
        if signals_with_charts:
            stage3_start = time.time()
            scored_signals = self.trader._batch_score_signals(signals_with_charts)
            stage3_time = time.time() - stage3_start
            logger.info(f"阶段3 - AI评分: {stage3_time:.2f}s")
        else:
            stage3_time = 0
            
        total_time = time.time() - total_start
        
        return {
            'total_time': total_time,
            'stage1_time': stage1_time,
            'stage2_time': stage2_time,
            'stage3_time': stage3_time,
            'candidate_count': len(candidate_signals),
            'chart_success_count': len(signals_with_charts)
        }
    
    def run_comprehensive_analysis(self):
        """运行综合性能分析"""
        logger.info("开始港股扫描性能综合分析...")
        
        # 获取测试股票
        watchlist = self.trader.get_watchlist_codes()
        if not watchlist:
            logger.error("无法获取自选股列表")
            return
            
        # 找一个有有效数据的股票进行测试
        test_code = None
        for code in watchlist[:5]:  # 测试前5个股票
            stock_info = self.trader.get_stock_info(code)
            if stock_info and stock_info['current_price'] > 0:
                test_code = code
                break
        
        if not test_code:
            logger.error("找不到有有效数据的测试股票")
            return
            
        logger.info(f"使用测试股票: {test_code}")
        
        # 1. K线获取性能分析
        kline_results = self.analyze_kline_fetching(test_code)
        
        # 2. 完整流程性能分析
        full_results = self.analyze_full_scan_performance([test_code])
        
        # 输出总结
        logger.info("\n" + "="*60)
        logger.info("性能分析总结:")
        logger.info("="*60)
        
        # K线获取分析
        logger.info(f"\nK线获取性能 ({test_code}):")
        if kline_results['30m']['success']:
            logger.info(f"  30M: {kline_results['30m']['time']:.2f}s ({kline_results['30m']['kline_count']}根)")
        if kline_results['5m']['success']:
            logger.info(f"  5M:  {kline_results['5m']['time']:.2f}s ({kline_results['5m']['kline_count']}根)")
        total_separate = kline_results['30m']['time'] + kline_results['5m']['time']
        logger.info(f"  分别获取总时间: {total_separate:.2f}s")
        if 'both' in kline_results:
            logger.info(f"  同时获取时间: {kline_results['both']['time']:.2f}s ({'成功' if kline_results['both']['success'] else '失败'})")
        
        # 完整流程分析
        logger.info(f"\n完整扫描流程 ({test_code}):")
        logger.info(f"  总时间: {full_results['total_time']:.2f}s")
        logger.info(f"  阶段1 (信号收集): {full_results['stage1_time']:.2f}s ({full_results['stage1_time']/full_results['total_time']*100:.1f}%)")
        if full_results['stage2_time'] > 0:
            logger.info(f"  阶段2 (图表生成): {full_results['stage2_time']:.2f}s ({full_results['stage2_time']/full_results['total_time']*100:.1f}%)")
        if full_results['stage3_time'] > 0:
            logger.info(f"  阶段3 (AI评分): {full_results['stage3_time']:.2f}s ({full_results['stage3_time']/full_results['total_time']*100:.1f}%)")
        
        # 主要瓶颈识别
        logger.info(f"\n主要性能瓶颈:")
        stages = [
            ('信号收集', full_results['stage1_time']),
            ('图表生成', full_results['stage2_time']),
            ('AI评分', full_results['stage3_time'])
        ]
        stages = [s for s in stages if s[1] > 0]
        if stages:
            bottleneck = max(stages, key=lambda x: x[1])
            logger.info(f"  {bottleneck[0]} ({bottleneck[1]:.2f}s, {bottleneck[1]/full_results['total_time']*100:.1f}%)")
        
        # K线获取优化建议
        logger.info(f"\nK线获取优化建议:")
        if kline_results['both']['success']:
            logger.info(f"  可以改用同时获取方式，预计节省 {(total_separate - kline_results['both']['time'])/total_separate*100:.1f}% 时间")
        else:
            logger.info(f"  必须分别获取，但可以考虑并行化处理")
            if kline_results['30m']['success'] and kline_results['5m']['success']:
                parallel_time = max(kline_results['30m']['time'], kline_results['5m']['time'])
                logger.info(f"  理论并行时间: max({kline_results['30m']['time']:.2f}, {kline_results['5m']['time']:.2f}) = {parallel_time:.2f}s")
                logger.info(f"  预计节省: {(total_separate - parallel_time)/total_separate*100:.1f}% 时间")


if __name__ == "__main__":
    analyzer = HKPerformanceAnalyzer()
    analyzer.run_comprehensive_analysis()