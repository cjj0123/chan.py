#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论视觉增强交易系统 - 支持港股 + A 股
集成 Gemini 2.5 Flash 视觉评分
"""

import time
import os
import sys
from datetime import datetime, timedelta
import pandas as pd
from futu import *
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, AUTYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 导入视觉评分模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from visual_judge import VisualJudge

# ==================== 策略配置 ====================
MAX_POSITION_RATIO = 0.2  # 单票最大仓位 20%
SCAN_PERIOD = KL_TYPE.K_30M
VISUAL_MODEL = "gemini-2.5-flash"  # Gemini 视觉模型
MIN_VISUAL_SCORE = 6  # 视觉评分阈值 >=6 分买入
DRY_RUN = True  # 模拟盘模式

# 自选股配置
HK_WATCHLIST_GROUP = "全部"  # 港股自选组名称
CN_WATCHLIST_GROUP = "A 股自选"  # A 股自选组名称

# 图表保存目录
CHARTS_DIR = "./charts_visual"
os.makedirs(CHARTS_DIR, exist_ok=True)

# ==================== 视觉增强交易引擎 ====================
class VisualFutuTradingEngine:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
        self.hk_stocks = []
        self.cn_stocks = []
        self.visual_judge = VisualJudge(use_mock=False)
        
    def load_stocks(self):
        """加载港股 + A 股自选股"""
        stocks_set = set()
        
        # 加载港股自选
        ret, user_stocks = self.quote_ctx.get_user_security(HK_WATCHLIST_GROUP)
        if ret == RET_OK:
            hk_watchlist = user_stocks[user_stocks['code'].str.startswith('HK.')]['code'].tolist()
            stocks_set.update(hk_watchlist)
            print(f"✅ 已加载自选港股：{len(hk_watchlist)} 只")
        
        # 加载 A 股自选
        ret, user_stocks = self.quote_ctx.get_user_security(CN_WATCHLIST_GROUP)
        if ret == RET_OK:
            cn_watchlist = user_stocks[user_stocks['code'].str.startswith('SH.') | 
                                       user_stocks['code'].str.startswith('SZ.')]['code'].tolist()
            stocks_set.update(cn_watchlist)
            print(f"✅ 已加载自选 A 股：{len(cn_watchlist)} 只")
        
        # 分类存储
        self.hk_stocks = [s for s in stocks_set if s.startswith('HK.')]
        self.cn_stocks = [s for s in stocks_set if s.startswith('SH.') or s.startswith('SZ.')]
        
        print(f"📊 标的池汇总：港股 {len(self.hk_stocks)} 只 + A 股 {len(self.cn_stocks)} 只 = {len(stocks_set)} 只")
    
    def generate_charts(self, code, chan_30m, chan_5m, signal_time):
        """生成 30M+5M 缠论图表"""
        safe_code = code.replace('.', '_')
        safe_time = signal_time.strftime("%Y%m%d_%H%M%S")
        
        try:
            # 生成 30M 图表
            plot_30m = CPlotDriver(
                chan_30m,
                plot_config={"plot_kline": True, "plot_bi": True, "plot_zs": True, "plot_bsp": True},
                plot_para={"figure": {"w": 14, "h": 8}}
            )
            chart_30m = f"{CHARTS_DIR}/{safe_code}_{safe_time}_30M.png"
            plt.savefig(chart_30m, bbox_inches='tight', dpi=100)
            plt.close('all')
            
            # 生成 5M 图表
            plot_5m = CPlotDriver(
                chan_5m,
                plot_config={"plot_kline": True, "plot_bi": True, "plot_zs": True, "plot_bsp": True},
                plot_para={"figure": {"w": 14, "h": 8}}
            )
            chart_5m = f"{CHARTS_DIR}/{safe_code}_{safe_time}_5M.png"
            plt.savefig(chart_5m, bbox_inches='tight', dpi=100)
            plt.close('all')
            
            return [chart_30m, chart_5m]
        except Exception as e:
            print(f"⚠️ 图表生成失败：{e}")
            return None
    
    def visual_analysis(self, code, signal_time, chart_paths):
        """调用 Gemini 视觉评分"""
        print(f"👁️ [视觉分析] {code} - 正在调用 Gemini 2.5 Flash...")
        
        result = self.visual_judge.evaluate(chart_paths)
        
        if result:
            score = result['score']
            action = result['action']
            analysis = result['analysis']
            
            print(f"   📊 评分：{score}/10 | 决策：{action}")
            print(f"   💡 分析：{analysis}")
            
            return score >= MIN_VISUAL_SCORE and action == "BUY"
        else:
            print(f"   ⚠️ 视觉分析失败，默认 WAIT")
            return False
    
    def execute_sim_order(self, code, bsp_type, price, visual_score=None):
        """执行模拟盘下单"""
        if self.dry_run:
            print(f"🎯 [模拟交易] {code} {bsp_type} @ {price} (视觉评分：{visual_score})")
        else:
            print(f"⚡️ [实盘交易] {code} {bsp_type} @ {price}, 执行下单...")
            # 实际下单逻辑
            # self.trd_ctx.unlock_trade(...)
            # self.trd_ctx.place_order(...)
    
    def safe_scan(self):
        """扫描所有标的，集成视觉评分"""
        config = CChanConfig({
            "bi_strict": False,
            "one_bi_zs": True,
            "bs_type": '1,1p,2,2s,3a,3b'
        })
        
        all_stocks = self.hk_stocks + self.cn_stocks
        total = len(all_stocks)
        
        print(f"🔍 开始扫描 {total} 只股票 (港股 {len(self.hk_stocks)} + A 股 {len(self.cn_stocks)})")
        print(f"📋 策略配置：视觉阈值 >= {MIN_VISUAL_SCORE} 分 | DRY_RUN={self.dry_run}")
        print("-" * 80)
        
        signals_found = 0
        signals_passed = 0
        
        for i, code in enumerate(all_stocks, 1):
            try:
                # 进度显示
                print(f"[{i}/{total}] 扫描 {code}...", end=" ")
                
                # 获取 30M 数据
                chan_30m = CChan(
                    code=code,
                    begin_time=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                    data_src=DATA_SRC.FUTU,
                    lv_list=[KL_TYPE.K_30M],
                    config=config
                )
                
                # 获取最新买卖点
                latest_bsp = chan_30m.get_latest_bsp(number=1)
                if not latest_bsp:
                    print("无信号")
                    continue
                
                bsp = latest_bsp[0]
                signal_time = pd.to_datetime(str(bsp.klu.time))
                is_fresh = (datetime.now() - signal_time).total_seconds() < 14400  # 4 小时内
                
                if not is_fresh:
                    print(f"信号过期 ({signal_time})")
                    continue
                
                # 发现新鲜信号
                signals_found += 1
                print(f"✨ 发现 {bsp.type2str()} @ {bsp.klu.close:.2f}")
                
                # 获取 5M 数据用于视觉分析
                chan_5m = CChan(
                    code=code,
                    begin_time=(signal_time - timedelta(days=5)).strftime("%Y-%m-%d"),
                    end_time=(signal_time + timedelta(days=1)).strftime("%Y-%m-%d"),
                    data_src=DATA_SRC.FUTU,
                    lv_list=[KL_TYPE.K_5M],
                    config=config
                )
                
                # 生成图表
                chart_paths = self.generate_charts(code, chan_30m, chan_5m, signal_time)
                if not chart_paths:
                    print("⚠️ 图表生成失败，跳过视觉分析")
                    continue
                
                # 视觉评分
                if self.visual_analysis(code, signal_time, chart_paths):
                    signals_passed += 1
                    print(f"✅ 视觉通过！执行买入...")
                    self.execute_sim_order(
                        code,
                        f"买入 {bsp.type2str()}",
                        bsp.klu.close,
                        visual_score="PASS"
                    )
                else:
                    print(f"❌ 视觉过滤，放弃该信号")
                
                print("-" * 80)
                time.sleep(1)  # 避免 API 限流
                
            except Exception as e:
                print(f"❌ 扫描失败：{e}")
                continue
        
        print("=" * 80)
        print(f"📊 扫描完成！")
        print(f"   总标的：{total} 只")
        print(f"   发现信号：{signals_found} 个")
        print(f"   视觉通过：{signals_passed} 个")
        print(f"   过滤率：{(1 - signals_passed/max(signals_found,1))*100:.1f}%")
        print("=" * 80)
    
    def close(self):
        self.quote_ctx.close()
        self.trd_ctx.close()

# ==================== 主函数 ====================
if __name__ == "__main__":
    engine = VisualFutuTradingEngine(dry_run=DRY_RUN)
    try:
        engine.load_stocks()
        print("🚀 开始执行视觉增强策略扫描...")
        engine.safe_scan()
    finally:
        engine.close()
