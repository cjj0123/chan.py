#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股缠论视觉交易系统 - V2 (邮件通知版)
功能：扫描 A 股缠论信号，通过邮件发送交易报告（含图表），不执行交易
"""

import os
import sys
import time
import logging
import shutil
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
import asyncio
import aiohttp
from concurrent.futures import ProcessPoolExecutor, as_completed


# TODO: 每年需要手动更新此节假日列表
CN_HOLIDAYS_2026 = [
    '2026-01-01',  # 元旦
    '2026-01-22',  # 农历年初三
    '2026-01-23',  # 农历年初四
    '2026-04-03',  # 清明节
    '2026-04-06',  # 复活节星期一
    '2026-05-01',  # 劳动节
    '2026-05-25',  # 佛诞
    '2026-06-19',  # 端午节
    '2026-07-01',  # 香港特区成立纪念日
    '2026-09-28',  # 中秋节
    '2026-10-01',  # 国庆节
    '2026-10-02',  # 国庆节
    '2026-10-21',  # 重阳节
    '2026-12-25',  # 圣诞节
]

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from futu import *
from visual_judge import VisualJudge
from send_email_report import send_stock_report


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cn_stock_trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class CNStockVisualTrading:
    """A 股视觉交易类（仅扫描通知）"""
    
    def __init__(self, 
                 cn_watchlist_group: str = "沪深",
                 min_visual_score: int = 70):
        """
        初始化 A 股视觉交易系统（仅扫描通知）
        
        Args:
            cn_watchlist_group: 自选股组名
            min_visual_score: 最小视觉评分阈值
        """
        self.cn_watchlist_group = cn_watchlist_group
        self.min_visual_score = min_visual_score
        self.dry_run = True  # A 股版本只扫描不交易
        
        # 配置 Chan
        self.chan_config = CChanConfig({
            "bi_strict": True,
            "seg_algo": "chan",
            "trigger_step": False,
            "bs_type": '1,1p,2,2s,3a,3b',
            "divergence_rate": 0.9,    # 优化后的背驰率
            "min_zs_cnt": 0,           # 允许 0 个中枢 (更灵敏)
            "max_bs2_rate": 1.2,
            "bsp1_only_multibi_zs": False,
            "bs1_peak": False,
        })
        
        # 初始化视觉评判 (它会自动从环境变量加载API Key)
        self.visual_judge = VisualJudge()
        
        # 图表保存目录
        self.charts_dir = "charts_cn"
        os.makedirs(self.charts_dir, exist_ok=True)
        
        # 初始化 Futu 连接
        self.quote_ctx = None
        try:
            self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            time.sleep(1)  # 等待连接就绪
            logger.info("Futu 行情连接已建立")
        except Exception as e:
            logger.error(f"Futu 连接失败：{e}")
        
        logger.info(f"A 股扫描初始化完成 - 评分阈值：{min_visual_score}")

    def send_email_notification(self, scan_summary: Dict):
        """发送扫描结果邮件"""
        try:
            all_signals = scan_summary.get('all_signals', [])
            if not all_signals:
                logger.info("没有发现交易信号 (评分 >= 阈值)，不发送邮件。")
                return

            logger.info(f"正在为 {len(all_signals)} 个信号准备邮件报告...")
            all_chart_paths = []
            for signal in all_signals:
                # 确保 signal 字典中有 is_buy 键，供 send_email_report.py 使用
                if 'is_buy' not in signal and 'is_buy_signal' in signal:
                    signal['is_buy'] = signal['is_buy_signal']
                
                stock_info = self.get_stock_info(signal['code'])
                signal['stock_name'] = stock_info.get('stock_name', '')
                chart_paths = signal.get('chart_paths', [])
                if chart_paths:
                    all_chart_paths.extend(chart_paths)

            now = datetime.now()
            subject = f"A 股交易信号 - {now.strftime('%Y-%m-%d %H:%M')}"

            logger.info(f"发送邮件: {subject}, 包含 {len(all_signals)} 个信号")
            success = send_stock_report(all_signals, all_chart_paths, subject=subject)
            if success:
                logger.info("邮件发送成功")
            else:
                logger.error("邮件发送失败")
        except Exception as e:
            logger.error(f"发送邮件通知异常: {e}")
    
    def get_cn_watchlist_codes(self) -> List[str]:
        """获取 A 股自选股列表"""
        try:
            if self.quote_ctx: self.quote_ctx.close()
            self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            time.sleep(1.5)
            
            ret, data = self.quote_ctx.get_user_security(self.cn_watchlist_group)
            if ret == RET_OK:
                codes = data['code'].tolist()
                cn_codes = [code for code in codes if code.startswith(('SH.', 'SZ.'))]
                logger.info(f"获取到 {len(cn_codes)} 只 A 股：{cn_codes[:10]}...")
                return cn_codes
            else:
                logger.error(f"获取自选股失败：{data}")
                return []
        except Exception as e:
            logger.error(f"获取自选股异常：{e}")
            return []
    
    def get_stock_info(self, code: str) -> Dict:
        """获取股票信息"""
        try:
            ret, data = self.quote_ctx.get_market_snapshot([code])
            if ret == RET_OK and not data.empty:
                stock_info = data.iloc[0].to_dict()
                return {
                    'current_price': stock_info['last_price'],
                    'stock_name': stock_info.get('name', ''),
                    'market_val': stock_info.get('market_val', 0),
                    'lot_size': int(stock_info.get('lot_size', 100))
                }
            else:
                logger.warning(f"无法获取 {code} 的市场快照")
                return {}
        except Exception as e:
            logger.error(f"获取股票信息异常 {code}: {e}")
            return {}

    def analyze_with_chan(self, code: str) -> Optional[Dict]:
        """使用 CChan 分析股票"""
        try:
            chan_multi_level = CChan(
                code=code,
                begin_time=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                data_src=DATA_SRC.FUTU,
                lv_list=[KL_TYPE.K_30M, KL_TYPE.K_5M],
                config=self.chan_config
            )
            
            chan_30m = chan_multi_level[0]
            # 修复：使用 CChan.get_latest_bsp 并在 KLine_List 上正确调用
            latest_bsps = chan_multi_level.get_latest_bsp(idx=0, number=1)
            if not latest_bsps:
                return None
            
            bsp = latest_bsps[0]
            bsp_ctime = bsp.klu.time
            bsp_time = datetime(bsp_ctime.year, bsp_ctime.month, bsp_ctime.day, 
                               bsp_ctime.hour, bsp_ctime.minute, bsp_ctime.second)
            
            # 生产环境：计算交易小时数并应用 4 小时窗口
            trading_hours = self.calculate_trading_hours(bsp_time, datetime.now())
            if trading_hours > 4: 
                return None
            
            logger.info(f"{code} {bsp.type2str()} 信号在 4 小时窗口内 ({trading_hours:.1f}h)")
            return {
                'code': code,
                'bsp_type': bsp.type2str(),
                'is_buy': bsp.is_buy,
                'is_buy_signal': bsp.is_buy,
                'chan_multi_level': chan_multi_level
            }
        except Exception as e:
            logger.error(f"CChan 分析异常 {code}: {e}")
            return None
    
    def calculate_trading_hours(self, start_time: datetime, end_time: datetime) -> float:
        """计算两个时间点之间的 A 股交易小时数"""
        total_hours = 0.0
        current = start_time
        
        while current < end_time:
            if current.weekday() >= 5 or current.strftime('%Y-%m-%d') in CN_HOLIDAYS_2026:
                current += timedelta(days=1)
                current = current.replace(hour=0, minute=0)
                continue

            morning_start = current.replace(hour=9, minute=30)
            morning_end = current.replace(hour=11, minute=30)
            afternoon_start = current.replace(hour=13, minute=0)
            afternoon_end = current.replace(hour=15, minute=0)

            calc_start = max(current, morning_start)
            
            # Morning session
            if calc_start < morning_end:
                segment_end = min(end_time, morning_end)
                if segment_end > calc_start:
                    total_hours += (segment_end - calc_start).total_seconds() / 3600
            
            # Afternoon session
            if end_time > afternoon_start:
                 calc_start = max(current, afternoon_start)
                 if calc_start < afternoon_end:
                    segment_end = min(end_time, afternoon_end)
                    if segment_end > calc_start:
                        total_hours += (segment_end - calc_start).total_seconds() / 3600

            if end_time.date() > current.date():
                current = (current + timedelta(days=1)).replace(hour=0, minute=0)
            else:
                break

        return total_hours

    def generate_charts(self, code: str, chan_multi_level: CChan) -> List[str]:
        """生成 30M+5M 图表"""
        chart_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_code = code.replace('.', '_')
        original_lv_list = chan_multi_level.lv_list
        
        try:
            for lv in original_lv_list:
                # 暂时修改级别列表以生成单层图表
                chan_multi_level.lv_list = [lv]
                
                plot_driver = CPlotDriver(chan_multi_level, plot_config={
                    "plot_kline": True, "plot_bi": True, "plot_seg": True,
                    "plot_zs": True, "plot_macd": True, "plot_bsp": True,
                })
                chart_path = f"{self.charts_dir}/{safe_code}_{timestamp}_{lv.name.replace('K_','')}.png"
                plt.savefig(chart_path, bbox_inches='tight', dpi=120, facecolor='white')
                plt.close('all')
                chart_paths.append(chart_path)
            
            logger.info(f"生成图表：{chart_paths}")
            return chart_paths
        except Exception as e:
            logger.error(f"生成图表异常 {code}: {e}")
            return []
        finally:
            # 必须在 finally 块恢复原始级别列表
            chan_multi_level.lv_list = original_lv_list

    def _collect_candidate_signals(self, watchlist_codes: List[str]) -> List[Dict]:
        """第一阶段：快速收集所有有效信号"""
        logger.info("阶段 1: 开始收集候选信号...")
        candidate_signals = []
        for code in watchlist_codes:
            stock_info = self.get_stock_info(code)
            if not stock_info or stock_info['current_price'] <= 0:
                continue
            
            chan_result = self.analyze_with_chan(code)
            if chan_result:
                signal_data = {**stock_info, **chan_result}
                candidate_signals.append(signal_data)
                logger.info(f"✅ {code} 候选信号已收集 ({chan_result['bsp_type']})")
        logger.info(f"共收集到 {len(candidate_signals)} 个候选信号")
        return candidate_signals

    def _generate_single_chart(self, signal_data: Dict) -> Optional[Dict]:
        """生成单个图表的辅助函数"""
        try:
            chart_paths = self.generate_charts(signal_data['code'], signal_data['chan_multi_level'])
            if not chart_paths: return None
            signal_data['chart_paths'] = chart_paths
            logger.info(f"✅ {signal_data['code']} 图表已生成")
            return signal_data
        except Exception as e:
            logger.error(f"生成图表异常 {signal_data['code']}: {e}")
            return None

    def _batch_generate_charts(self, candidate_signals: List[Dict]) -> List[Dict]:
        """第二阶段：批量生成图表 (同步执行，避免进程池序列化问题)"""
        logger.info(f"阶段 2: 开始批量生成图表 (共 {len(candidate_signals)} 个)")
        signals_with_charts = []
        
        for signal in candidate_signals:
            result = self._generate_single_chart(signal)
            if result:
                signals_with_charts.append(result)
                
        logger.info(f"批量图表生成完成，成功 {len(signals_with_charts)} 个")
        return signals_with_charts

    async def _async_evaluate_single_signal(self, signal: Dict) -> Optional[Dict]:
        """异步评估单个信号"""
        try:
            loop = asyncio.get_event_loop()
            visual_result = await loop.run_in_executor(
                None, self.visual_judge.evaluate, signal['chart_paths'], signal['bsp_type']
            )
            score = visual_result.get('score', 0)
            logger.info(f"{signal['code']} 视觉评分: {score}/100")
            
            if score >= self.min_visual_score:
                signal['score'] = score
                signal['visual_result'] = visual_result
                return signal
            return None
        except Exception as e:
            logger.error(f"视觉评分异常 {signal['code']}: {e}")
            return None

    async def _batch_score_signals_async(self, signals_with_charts: List[Dict]) -> List[Dict]:
        """异步批量评分"""
        tasks = [self._async_evaluate_single_signal(s) for s in signals_with_charts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_signals = []
        for res in results:
            if isinstance(res, dict):
                final_signals.append(res)
            elif res is not None:
                logger.error(f"评分任务异常: {res}")
        return final_signals

    def _batch_score_signals(self, signals_with_charts: List[Dict]) -> List[Dict]:
        """第三阶段：批量视觉评分"""
        logger.info(f"阶段 3: 开始批量视觉评分 (共 {len(signals_with_charts)} 个)")
        if not signals_with_charts: return []
        
        scored_signals = asyncio.run(self._batch_score_signals_async(signals_with_charts))
        
        # 按买卖和评分排序
        buy_signals = sorted([s for s in scored_signals if s.get('is_buy', s.get('is_buy_signal'))], key=lambda x: x['score'], reverse=True)
        sell_signals = sorted([s for s in scored_signals if not s.get('is_buy', s.get('is_buy_signal'))], key=lambda x: x['score'], reverse=True)
        
        logger.info(f"评分完成. 买入信号: {len(buy_signals)}个, 卖出信号: {len(sell_signals)}个")
        return sell_signals + buy_signals # 卖点优先

    def is_cn_trading_day(self) -> bool:
        """检查是否为 A 股交易日"""
        now = datetime.now()
        if now.weekday() >= 5: return False
        if now.strftime('%Y-%m-%d') in CN_HOLIDAYS_2026: return False
        return True

    def scan_and_trade(self):
        """A 股扫描主流程（三段式）"""
        if not self.is_cn_trading_day():
            logger.info(f"📭 今日是非交易日，跳过 A 股扫描")
            return
        
        logger.info("=" * 70)
        logger.info("🔍 A 股缠论信号扫描开始 (V2)...")
        logger.info("=" * 70)
        
        # 阶段 1: 收集候选信号
        watchlist_codes = self.get_cn_watchlist_codes()
        if not watchlist_codes:
            logger.warning("没有获取到自选股，退出")
            return
        candidate_signals = self._collect_candidate_signals(watchlist_codes)
        
        if not candidate_signals:
            logger.info("没有发现任何候选信号，扫描结束。")
            return
            
        # 阶段 2: 批量生成图表
        signals_with_charts = self._batch_generate_charts(candidate_signals)
        
        if not signals_with_charts:
            logger.info("没有成功生成任何图表，扫描结束。")
            return

        # 阶段 3: 批量评分并筛选
        final_signals = self._batch_score_signals(signals_with_charts)
        
        # 阶段 4: 发送邮件通知
        scan_summary = {
            'total_stocks': len(watchlist_codes),
            'all_signals': final_signals,
        }
        self.send_email_notification(scan_summary)
        
        logger.info("=" * 70)
        logger.info("✅ A 股扫描完成")
        logger.info("=" * 70)
    
    def close_connections(self):
        """关闭富途连接"""
        if self.quote_ctx:
            self.quote_ctx.close()


def main():
    """主函数"""
    try:
        trader = CNStockVisualTrading(
            cn_watchlist_group="沪深",
            min_visual_score=70
        )
        trader.scan_and_trade()
    except Exception as e:
        logger.error(f"程序异常：{e}")
    finally:
        try:
            trader.close_connections()
        except:
            pass


if __name__ == "__main__":
    main()
