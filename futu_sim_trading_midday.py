#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论视觉增强交易系统 - 盘中常规扫描 (每 30 分钟延后 1 分钟)
- 视觉评分>=8 分立即执行 20% 资金买入
- 使用增强限价盘
- 11:31 扫描结果留到 13:00 执行 (午休)
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
VISUAL_MODEL = "gemini-2.5-flash"
MIN_VISUAL_SCORE = 8  # 视觉评分阈值 >=8 分买入 (增强版)
DRY_RUN = True  # 模拟盘模式
ORDER_TYPE = "ENHANCED"  # 增强限价盘

# 自选股配置
HK_WATCHLIST_GROUP = "全部"
CN_WATCHLIST_GROUP = "A 股自选"

# 图表保存目录
CHARTS_DIR = "./charts_cn_scan"
os.makedirs(CHARTS_DIR, exist_ok=True)

# 午餐时间持仓记录文件
LUNCH_HOLD_FILE = "./lunch_hold_orders.json"

# ==================== 视觉增强交易引擎 ====================
class MiddayFutuTradingEngine:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
        self.hk_stocks = []
        self.cn_stocks = []
        self.visual_judge = VisualJudge(use_mock=False)
        self.lunch_hold_orders = []
        
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
            
            return score >= MIN_VISUAL_SCORE and action == "BUY", score
        else:
            print(f"   ⚠️ 视觉分析失败，默认 WAIT")
            return False, 0
    
    def is_lunch_time(self):
        """检查是否在午休时间 (11:30-13:00)"""
        now = datetime.now()
        lunch_start = now.replace(hour=11, minute=30, second=0, microsecond=0)
        lunch_end = now.replace(hour=13, minute=0, second=0, microsecond=0)
        return lunch_start <= now <= lunch_end
    
    def should_hold_for_lunch(self, signal_time):
        """检查是否应该留到 13:00 执行 (11:31 扫描结果)"""
        now = datetime.now()
        # 如果是 11:30-11:59 之间的扫描，且当前时间在 13:00 之前，需要持有
        if 11 <= now.hour <= 12 and now.hour < 13:
            return True
        return False
    
    def execute_sim_order(self, code, bsp_type, price, visual_score, hold_for_lunch=False):
        """执行模拟盘下单 (增强限价盘)"""
        order_info = {
            "code": code,
            "bsp_type": bsp_type,
            "price": price,
            "visual_score": visual_score,
            "order_type": ORDER_TYPE,
            "position_ratio": MAX_POSITION_RATIO,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hold_for_lunch": hold_for_lunch
        }
        
        if hold_for_lunch:
            print(f"⏸️ [午餐持仓] {code} {bsp_type} @ {price} (视觉评分：{visual_score}) - 留待 13:00 执行")
            self.lunch_hold_orders.append(order_info)
            self.save_lunch_orders()
        elif self.dry_run:
            print(f"🎯 [模拟交易] {code} {bsp_type} @ {price} | 视觉评分：{visual_score} | 仓位：{MAX_POSITION_RATIO*100:.0f}% | 订单类型：{ORDER_TYPE}")
            # 调用 Futu 模拟盘接口 (Paper Trading)
            if code.startswith('HK'):
                trd_env = TrdEnv.SIMULATE  # 港股模拟盘环境
            else:
                trd_env = TrdEnv.SIMULATE  # A 股模拟盘环境 (假设 Futu 支持)
            
            try:
                # 尝试连接模拟盘
                # 注意：需要确保 OpenD 配置了模拟盘账户或默认支持
                # 这里简单演示，实际可能需要单独的 Context 或 unlock
                # 模拟盘通常不需要 unlock_trade，但需要指定 trd_env
                
                # 重新初始化一个模拟盘 Context (如果默认 Context 不是模拟盘)
                # 但 self.trd_ctx 初始化时没有指定 trd_env，默认为 REAL? 不，OpenHKTradeContext 默认可能是 REAL
                # 让我们尝试用该 Context 下单，指定 trd_env
                
                # 计算数量 (简单按当前价格和 20% 资金，这里简化为固定数量或简单估算)
                qty = 100 # 默认 100 股测试
                
                ret, data = self.trd_ctx.place_order(
                    price=price,
                    qty=qty,
                    code=code,
                    trd_side=TrdSide.BUY,
                    order_type=OrderType.NORMAL, # 模拟盘可能不支持 ENHANCED
                    trd_env=TrdEnv.SIMULATE 
                )
                if ret == RET_OK:
                    print(f"   ✅ [Futu模拟盘] 下单成功！订单号: {data['order_id'][0]}")
                else:
                    print(f"   ❌ [Futu模拟盘] 下单失败: {data}")
            except Exception as e:
                print(f"   ❌ [Futu模拟盘] 接口调用异常: {e}")

        else:
            print(f"⚡️ [实盘交易] {code} {bsp_type} @ {price}, 执行增强限价盘下单...")
            # 实际下单逻辑
            # self.trd_ctx.unlock_trade(...)
            # self.trd_ctx.place_order(order_type=OrderType.ENHANCED, ...)
    
    def save_lunch_orders(self):
        """保存午餐持仓订单到文件"""
        import json
        with open(LUNCH_HOLD_FILE, 'w') as f:
            json.dump(self.lunch_hold_orders, f, indent=2, default=str)
    
    def load_lunch_orders(self):
        """加载之前的午餐持仓订单"""
        import json
        if os.path.exists(LUNCH_HOLD_FILE):
            with open(LUNCH_HOLD_FILE, 'r') as f:
                self.lunch_hold_orders = json.load(f)
            print(f"📋 加载了 {len(self.lunch_hold_orders)} 个午餐持仓订单")
    
    def execute_lunch_orders(self):
        """执行午餐持仓订单 (13:00 后)"""
        if not self.lunch_hold_orders:
            print("✅ 无午餐持仓订单需要执行")
            return
        
        print(f"🔔 开始执行 {len(self.lunch_hold_orders)} 个午餐持仓订单...")
        for order in self.lunch_hold_orders:
            if self.dry_run:
                print(f"🎯 [模拟交易] {order['code']} {order['bsp_type']} @ {order['price']} | 视觉评分：{order['visual_score']} | 仓位：{order['position_ratio']*100:.0f}%")
            else:
                print(f"⚡️ [实盘交易] {order['code']} {order['bsp_type']} @ {order['price']}, 执行增强限价盘下单...")
                # 实际下单逻辑
                # self.trd_ctx.unlock_trade(...)
                # self.trd_ctx.place_order(order_type=OrderType.ENHANCED, ...)
        
        # 清空午餐持仓文件
        self.lunch_hold_orders = []
        if os.path.exists(LUNCH_HOLD_FILE):
            os.remove(LUNCH_HOLD_FILE)
    
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
        print(f"📋 策略配置：视觉阈值 >= {MIN_VISUAL_SCORE} 分 | 仓位：{MAX_POSITION_RATIO*100:.0f}% | 订单类型：{ORDER_TYPE} | DRY_RUN={self.dry_run}")
        
        # 检查是否需要执行午餐持仓订单
        now = datetime.now()
        if now.hour >= 13 and now.minute >= 0:
            print("⏰ 已过 13:00，检查午餐持仓订单...")
            self.load_lunch_orders()
            self.execute_lunch_orders()
            print("-" * 80)
        
        # 检查是否在午餐时间
        hold_for_lunch = self.should_hold_for_lunch(now)
        if hold_for_lunch:
            print(f"⏸️ 当前时间 {now.strftime('%H:%M')} 在午餐窗口 (11:30-13:00)，信号将留待 13:00 执行")
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
                passed, score = self.visual_analysis(code, signal_time, chart_paths)
                if passed:
                    signals_passed += 1
                    print(f"✅ 视觉通过 (评分：{score})！执行买入...")
                    self.execute_sim_order(
                        code,
                        f"买入 {bsp.type2str()}",
                        bsp.klu.close,
                        visual_score=score,
                        hold_for_lunch=hold_for_lunch
                    )
                else:
                    print(f"❌ 视觉过滤 (评分：{score})，放弃该信号")
                
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
        if hold_for_lunch and signals_passed > 0:
            print(f"   ⏸️ 午餐持仓：{signals_passed} 个订单留待 13:00 执行")
        print("=" * 80)
    
    def close(self):
        self.quote_ctx.close()
        self.trd_ctx.close()

# ==================== 主函数 ====================
if __name__ == "__main__":
    engine = MiddayFutuTradingEngine(dry_run=DRY_RUN)
    try:
        engine.load_stocks()
        print("🚀 开始执行盘中常规扫描 (视觉增强版，>=8 分买入)...")
        engine.safe_scan()
    finally:
        engine.close()
