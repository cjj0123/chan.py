#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股缠论视觉交易系统 - 仅扫描通知版
功能：扫描 A 股缠论信号，发送备忘录通知（含图表），不执行交易
"""

import os
import sys
import time
import logging
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from futu import *
from visual_judge import VisualJudge

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
                 cn_watchlist_group: str = "A 股",
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
            
        })
        
        # 初始化视觉评判
        self.visual_judge = VisualJudge()
        
        # 图表保存目录
        self.charts_dir = "charts_cn"
        os.makedirs(self.charts_dir, exist_ok=True)
        
        # 初始化 Futu 连接
        self.quote_ctx = None
        try:
            self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            logger.info("Futu 行情连接已建立")
        except Exception as e:
            logger.error(f"Futu 连接失败：{e}")
        
        # 检查 memo CLI 是否可用
        self.memo_available = shutil.which("memo") is not None
        if not self.memo_available:
            logger.warning("memo CLI 未安装，Apple Notes 通知功能不可用")
        
        logger.info(f"A 股扫描初始化完成 - 评分阈值：{min_visual_score}")
    
    def get_cn_watchlist_codes(self) -> List[str]:
        """
        获取 A 股自选股列表
        
        Returns:
            股票代码列表
        """
        try:
            ret, data = self.quote_ctx.get_user_security(self.cn_watchlist_group)
            if ret == RET_OK:
                codes = data['code'].tolist()
                # 过滤 A 股代码 (SH. SZ.)
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
            end_time = datetime.now()
            start_time = end_time - timedelta(days=30)
            
            chan_30m = CChan(
                code=code,
                begin_time=start_time.strftime("%Y-%m-%d"),
                end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                data_src=DATA_SRC.FUTU,
                lv_list=[KL_TYPE.K_30M],
                config=self.chan_config
            )
            
            latest_bsps = chan_30m.get_latest_bsp(number=1)
            if not latest_bsps:
                logger.debug(f"{code} 未发现买卖点")
                return None
            
            bsp = latest_bsps[0]
            bsp_type = bsp.type2str()
            is_buy = bsp.is_buy
            price = bsp.klu.close
            
            # 时间过滤：只交易最近 4 个交易小时内的信号
            bsp_ctime = bsp.klu.time
            bsp_time = datetime(bsp_ctime.year, bsp_ctime.month, bsp_ctime.day, 
                               bsp_ctime.hour, bsp_ctime.minute, bsp_ctime.second)
            
            now = datetime.now()
            trading_hours = self.calculate_trading_hours(bsp_time, now)
            
            if trading_hours > 4:
                logger.info(f"{code} {bsp_type} 信号产生于 {bsp_time.strftime('%Y-%m-%d %H:%M')}，"
                           f"距今 {trading_hours:.1f} 个交易小时，超过 4 小时窗口，跳过")
                return None
            
            logger.info(f"{code} {bsp_type} 信号在 4 小时窗口内（{trading_hours:.1f}个交易小时前），继续分析")
            
            result = {
                'code': code,
                'bsp_type': bsp_type,
                'is_buy_signal': is_buy,
                'bsp_price': price,
                'bsp_datetime': bsp.klu.time,
                'chan_analysis': {
                    'chan_30m': chan_30m
                }
            }
            
            logger.info(f"{code} 缠论分析：{bsp_type} 信号，价格：{price}")
            return result
            
        except Exception as e:
            logger.error(f"CChan 分析异常 {code}: {e}")
            return None
    
    def calculate_trading_hours(self, start_time: datetime, end_time: datetime) -> float:
        """计算两个时间点之间的 A 股交易小时数"""
        # A 股交易时间：09:30-11:30, 13:00-15:00
        morning_start = start_time.replace(hour=9, minute=30, second=0, microsecond=0)
        morning_end = start_time.replace(hour=11, minute=30, second=0, microsecond=0)
        afternoon_start = start_time.replace(hour=13, minute=0, second=0, microsecond=0)
        afternoon_end = start_time.replace(hour=15, minute=0, second=0, microsecond=0)
        
        total_hours = 0.0
        current = start_time
        
        while current < end_time:
            # 上午时段
            if current < morning_end:
                segment_end = min(end_time, morning_end)
                if current >= morning_start:
                    total_hours += (segment_end - current).total_seconds() / 3600
                current = segment_end
                if current >= end_time:
                    break
                # 跳到下午开盘
                if current < afternoon_start:
                    current = afternoon_start
            
            # 下午时段
            if current < afternoon_end and current >= afternoon_start:
                segment_end = min(end_time, afternoon_end)
                total_hours += (segment_end - current).total_seconds() / 3600
                current = segment_end
                if current >= end_time:
                    break
            
            # 如果过了下午收盘，进入下一天
            if current >= afternoon_end:
                current = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0)
            elif morning_end <= current < afternoon_start:
                current = afternoon_start
        
        return total_hours
    
    def generate_charts(self, code: str, chan_30m: CChan) -> List[str]:
        """生成 30M+5M 图表"""
        chart_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_code = code.replace('.', '_').replace('-', '_')
        
        try:
            # 30 分钟图
            plot_30m = CPlotDriver(chan_30m, plot_config={
                "plot_kline": True,
                "plot_bi": True,
                "plot_seg": True,
                "plot_zs": True,
                "plot_macd": True,
                "plot_mean": False,
                "plot_channel": False,
            })
            chart_30m_path = f"{self.charts_dir}/{safe_code}_{timestamp}_30M.png"
            plt.savefig(chart_30m_path, bbox_inches='tight', dpi=120, facecolor='white')
            plt.close('all')
            chart_paths.append(chart_30m_path)
            
            # 5 分钟图
            end_time = datetime.now()
            start_time = end_time - timedelta(days=7)
            chan_5m = CChan(
                code=code,
                begin_time=start_time.strftime("%Y-%m-%d"),
                end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
                data_src=DATA_SRC.FUTU,
                lv_list=[KL_TYPE.K_5M],
                config=self.chan_config
            )
            plot_5m = CPlotDriver(chan_5m, plot_config={
                "plot_kline": True,
                "plot_bi": True,
                "plot_seg": False,
                "plot_zs": True,
                "plot_macd": True,
            })
            chart_5m_path = f"{self.charts_dir}/{safe_code}_{timestamp}_5M.png"
            plt.savefig(chart_5m_path, bbox_inches='tight', dpi=120, facecolor='white')
            plt.close('all')
            chart_paths.append(chart_5m_path)
            
            logger.info(f"生成图表：{chart_paths}")
            return chart_paths
            
        except Exception as e:
            logger.error(f"生成图表异常 {code}: {e}")
            return []
    
    def send_scan_result_to_notes(self, scan_summary):
        """将扫描结果发送到 Apple Notes 备忘录（包含图表图片）"""
        try:
            if scan_summary.get('valid_signals', 0) == 0:
                logger.info("📭 无有效信号，跳过备忘录通知")
                return
            
            now = datetime.now()
            title = "🎯 A 股交易信号 - " + now.strftime('%Y-%m-%d %H:%M')
            
            # 构建文本内容
            text_lines = [
                "🎯 A 股缠论视觉交易信号",
                "═══════════════════════════════",
                "",
                "⏰ 扫描时间：" + now.strftime('%Y-%m-%d %H:%M:%S'),
                "✅ 有效信号：" + str(scan_summary.get('valid_signals', 0)) + "个",
                ""
            ]
            
            all_chart_paths = []
            
            # 卖出信号
            sell_signals = scan_summary.get('sell_signals', [])
            if sell_signals:
                text_lines.append("【卖出信号】" + str(len(sell_signals)) + "个")
                for i, signal in enumerate(sell_signals, 1):
                    code = signal.get('code', 'N/A')
                    bsp_type = signal.get('bsp_type', '未知')
                    score = signal.get('score', 0)
                    chart_paths = signal.get('chart_paths', [])
                    
                    text_lines.append(str(i) + ". " + str(code) + " - " + str(bsp_type) + " (评分：" + str(score) + ")")
                    if chart_paths:
                        all_chart_paths.extend(chart_paths)
                    text_lines.append("")
            
            # 买入信号
            buy_signals = scan_summary.get('buy_signals', [])
            if buy_signals:
                text_lines.append("【买入信号】" + str(len(buy_signals)) + "个")
                for i, signal in enumerate(buy_signals, 1):
                    code = signal.get('code', 'N/A')
                    bsp_type = signal.get('bsp_type', '未知')
                    score = signal.get('score', 0)
                    chart_paths = signal.get('chart_paths', [])
                    
                    text_lines.append(str(i) + ". " + str(code) + " - " + str(bsp_type) + " (评分：" + str(score) + ")")
                    if chart_paths:
                        all_chart_paths.extend(chart_paths)
                    text_lines.append("")
            
            text_content = "\n".join(text_lines)
            escaped_title = title.replace('"', '\\"')
            escaped_text = text_content.replace('"', '\\"').replace("\n", "\\n")
            
            # 创建备忘录
            script1 = 'tell application "Notes"\n    make new note with properties {name:"' + escaped_title + '", body:"' + escaped_text + '"}\nend tell'
            result = subprocess.run(["osascript", "-e", script1], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                logger.info("✅ 备忘录已创建：" + title)
                
                # 插入图表图片
                if all_chart_paths:
                    for chart_path in all_chart_paths:
                        if os.path.exists(chart_path):
                            abs_path = os.path.abspath(chart_path)
                            script2 = 'tell application "Notes"\n    tell note "' + escaped_title + '"\n        insert image from file "' + abs_path + '"\n    end tell\nend tell'
                            subprocess.run(["osascript", "-e", script2], capture_output=True, timeout=10)
                    logger.info("📊 已插入 " + str(len(all_chart_paths)) + " 张图表")
            else:
                logger.error("❌ 创建备忘录失败：" + result.stderr)
            
        except Exception as e:
            logger.error("❌ 发送备忘录异常：" + str(e))
    
    def scan_and_trade(self):
        """A 股扫描：只扫描信号并发送备忘录通知"""
        logger.info("=" * 70)
        logger.info("🔍 A 股缠论信号扫描开始...")
        logger.info("=" * 70)
        
        all_signals = []
        
        # 获取自选股列表
        watchlist_codes = self.get_cn_watchlist_codes()
        if not watchlist_codes:
            logger.warning("没有获取到自选股")
            return
        
        logger.info(f"获取到 {len(watchlist_codes)} 只 A 股")
        
        # 扫描所有股票
        for code in watchlist_codes:
            logger.info(f"分析股票：{code}")
            
            stock_info = self.get_stock_info(code)
            if not stock_info:
                continue
            
            current_price = stock_info['current_price']
            if current_price <= 0:
                logger.warning(f"{code} 价格无效，跳过")
                continue
            
            # 缠论分析
            chan_result = self.analyze_with_chan(code)
            if not chan_result:
                logger.debug(f"{code} 无缠论信号，跳过")
                continue
            
            # 记录信号类型
            bsp_type = chan_result.get('bsp_type', '未知')
            is_buy = chan_result.get('is_buy_signal', False)
            bsp_type_display = f"{'b' if is_buy else 's'}{bsp_type}"
            logger.info(f"{code} 信号类型：{bsp_type_display}, 是否买入：{is_buy}")
            
            # 生成图表
            chart_paths = self.generate_charts(code, chan_result['chan_analysis']['chan_30m'])
            if not chart_paths:
                logger.warning(f"{code} 图表生成失败，跳过")
                continue
            
            # 视觉评分
            try:
                visual_result = self.visual_judge.evaluate(chart_paths)
                score = visual_result.get('score', 0)
                action = visual_result.get('action', 'WAIT')
                
                logger.info(f"{code} 视觉评分：{score}/100, 建议：{action}")
                
                # 收集达到阈值的信号
                if score >= self.min_visual_score:
                    signal_data = {
                        'code': code,
                        'is_buy': is_buy,
                        'bsp_type': bsp_type,
                        'score': score,
                        'current_price': current_price,
                        'chart_paths': chart_paths,
                        'visual_result': visual_result
                    }
                    all_signals.append(signal_data)
                    logger.info(f"✅ {code} 信号收集成功 (评分：{score})")
                else:
                    logger.info(f"{code} 评分 ({score}) 低于阈值 ({self.min_visual_score})，不收集")
                    
            except Exception as e:
                logger.error(f"视觉评分异常 {code}: {e}")
                continue
        
        logger.info(f"共收集到 {len(all_signals)} 个有效信号")
        
        # 分离买卖信号
        sell_signals = [s for s in all_signals if not s['is_buy']]
        buy_signals = [s for s in all_signals if s['is_buy']]
        
        # 按评分排序
        sell_signals.sort(key=lambda x: x['score'], reverse=True)
        buy_signals.sort(key=lambda x: x['score'], reverse=True)
        
        logger.info(f"卖出信号：{len(sell_signals)}个，买入信号：{len(buy_signals)}个")
        
        # 发送备忘录通知
        try:
            scan_summary = {
                'total_stocks': len(watchlist_codes),
                'valid_signals': len(all_signals),
                'sell_signals': sell_signals,
                'buy_signals': buy_signals,
                'initial_funds': 0,
                'final_funds': 0
            }
            self.send_scan_result_to_notes(scan_summary)
        except Exception as e:
            logger.error(f"发送扫描结果到备忘录失败：{e}")
        
        logger.info("=" * 70)
        logger.info("✅ A 股扫描完成")
        logger.info("=" * 70)
    
    def close_connections(self):
        """关闭富途连接"""
        if hasattr(self, 'quote_ctx'):
            self.quote_ctx.close()
        if hasattr(self, 'trd_ctx'):
            self.trd_ctx.close()


def main():
    """主函数"""
    try:
        # 初始化交易系统
        trader = CNStockVisualTrading(
            cn_watchlist_group="A 股",
            min_visual_score=70
        )
        
        # 执行扫描
        trader.scan_and_trade()
        
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在退出...")
    except Exception as e:
        logger.error(f"程序异常：{e}")
    finally:
        # 清理资源
        try:
            trader.close_connections()
        except:
            pass


if __name__ == "__main__":
    main()
