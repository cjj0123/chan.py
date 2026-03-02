#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"
港股视觉增强扫描 - 集成 Gemini 视觉评分并执行交易
\"\"\"

import time
import os
import sys
from datetime import datetime, timedelta
import pandas as pd
from futu import *
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import subprocess
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('futu_trading.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 导入视觉评分模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from visual_judge import VisualJudge

# ==================== 配置 ====================
HK_WATCHLIST_GROUP = "港股"  # Futu 港股自选股组名称
SCAN_PERIOD = KL_TYPE.K_30M
MIN_VISUAL_SCORE = 60  # 视觉评分阈值 >=60 分买入 (Gemini返回0-100)
CHARTS_DIR = "./charts_hk_scan"
os.makedirs(CHARTS_DIR, exist_ok=True)

DRY_RUN = False  # True=模拟盘，False=实盘
MAX_POSITION_RATIO = 0.2  # 单票最大仓位 20%
INITIAL_CAPITAL = 100000.0 # 初始资金，用于仓位计算

# 港股交易时间检查
def is_hk_market_open():
    \"\"\"检查是否在港股交易时间内\"\"\"
    now = datetime.now()
    
    # 周末不交易
    if now.weekday() >= 5:
        return False
    
    # 交易时间：9:30-12:00, 13:00-16:00
    # 扫描时间：9:31, 10:01, 10:31, 11:01, 11:31, 13:01, 13:31, 14:01, 14:31, 15:01, 15:31, 15:55, 16:01
    from datetime import time
    morning_start = time(9, 25)
    morning_end = time(12, 5)
    afternoon_start = time(12, 55)
    afternoon_end = time(16, 5)
    
    if (morning_start <= now.time() <= morning_end) or \
       (afternoon_start <= now.time() <= afternoon_end):
        return True
    
    return False

def send_hk_signal_notification(code, bsp_type, price, score, analysis, chart_paths, action="BUY"):
    \"\"\"发送港股交易信号通知\"\"\"
    try:
        title = f"🎯 港股交易信号 - {code}"
        content = f\"\"\"
# {code} 交易信号

**信号类型:** {bsp_type}
**价格:** {price:.2f} HKD
**视觉评分:** {score}/100
**决策:** {'✅ 执行买入' if action == 'BUY' else '❌ 过滤'}

## 视觉分析
{analysis}

## 图表
{', '.join(chart_paths)}

---
⚠️ 仅供参考，不构成投资建议
\"\"\"
        
        # 发送到备忘录
        # cmd = ["memo", "create", "--title", title, content]
        # result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        # if result.returncode == 0:
        #    logger.info(f"📱 已发送通知到备忘录：{title}")
        
        # 保存信号到文件
        signal_file = f"{CHARTS_DIR}/signal_{code.replace('.', '_')}_{int(time.time())}.json"
        signal_data = {
            "code": code,
            "type": bsp_type,
            "price": price,
            "score": score,
            "analysis": analysis,
            "action": action,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "charts": chart_paths
        }
        with open(signal_file, 'w', encoding='utf-8') as f:
            json.dump(signal_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 信号已保存到：{signal_file}")
        
    except Exception as e:
        logger.error(f"⚠️ 通知发送失败：{e}")

# ==================== 港股视觉扫描引擎 ====================
class HKStockVisualScanner:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.trd_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
        self.hk_stocks = []
        self.visual_judge = VisualJudge(use_mock=False)
        self.results = []
        self.current_positions = self.get_current_positions()
        self.available_cash = self.get_available_cash()

        if not self.dry_run:
            ret, data = self.trd_ctx.unlock_trade(passwd="", is_unlock=True)
            if ret != RET_OK:
                logger.error(f"解锁交易失败：{data}")
                raise Exception("交易解锁失败")
            logger.info("✅ 交易账户已解锁")
        
    def get_available_cash(self) -> float:
        \"\"\"获取当前可用资金\"\"\"
        if self.dry_run:
            return INITIAL_CAPITAL # 模拟资金

        ret, data = self.trd_ctx.accinfo_query(trd_env=TrdEnv.REAL # Change to REAL for real trading
)
        if ret == RET_OK:
            return float(data.iloc[0]['available_cash'])
        else:
            logger.error(f"获取可用资金失败: {data}")
            return 0.0

    def get_current_positions(self) -> Dict[str, Any]:
        \"\"\"获取当前持仓\"\"\"
        if self.dry_run:
            return {}
        
        positions = {}
        ret, data = self.trd_ctx.position_list_query(trd_env=TrdEnv.REAL # Change to REAL for real trading
)
        if ret == RET_OK:
            for _, row in data.iterrows():
                positions[row['code']] = {
                    'qty': float(row['qty']),
                    'cost_price': float(row['cost_price'])
                }
        else:
            logger.error(f"获取持仓失败: {data}")
        return positions

    def load_hk_stocks(self):
        \"\"\"加载港股自选股\"\"\"
        stocks_list = []
        
        # 先列出所有可用的自选组
        logger.info("📋 正在获取 Futu 自选股列表...")
        ret, groups_data = self.quote_ctx.get_user_security_group()
        if ret == RET_OK:
            logger.info(f"✅ 找到 {len(groups_data)} 个自选股组:")
            for i, group_name in enumerate(groups_data['group_name'].tolist(), 1):
                logger.info(f"   {i}. {group_name}")
        
        # 从 Futu 自选组加载港股
        logger.info(f"\\n📂 正在加载 '{HK_WATCHLIST_GROUP}' 自选股...")
        ret, user_stocks = self.quote_ctx.get_user_security(HK_WATCHLIST_GROUP)
        if ret == RET_OK and len(user_stocks) > 0:
            hk_watchlist = user_stocks[user_stocks['code'].str.startswith('HK.')]['code'].tolist()
            stocks_list.extend(hk_watchlist)
            logger.info(f"✅ 已加载自选港股：{len(hk_watchlist)} 只")
        else:
            logger.warning(f"⚠️ 无法从 '{HK_WATCHLIST_GROUP}' 加载股票，错误码：{ret}")
            logger.warning("💡 请确认 Futu App 中存在该自选股组，并且包含股票")
        
        self.hk_stocks = stocks_list
        if stocks_list:
            logger.info(f"📊 准备扫描 {len(self.hk_stocks)} 只港股")
        else:
            logger.error("❌ 未找到任何港股，请检查自选股配置")
    
    def generate_charts(self, code, chan_30m, chan_5m, signal_time):
        \"\"\"生成 30M+5M 缠论图表\"\"\"
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
            logger.error(f"⚠️ 图表生成失败：{e}")
            return None
    
    def get_lot_size(self, code: str) -> int:
        \"\"\"获取港股每手股数\"\"\"
        # Placeholder for HKMarket.get_lot_size
        # This needs to be implemented or imported correctly
        # For now, return a default value or fetch from a dummy source
        try:
            ret, data = self.quote_ctx.get_stock_basicinfo(Market.HK, [code])
            if ret == RET_OK and not data.empty:
                return int(data.iloc[0]['lot_size'])
            else:
                logger.warning(f"无法获取 {code} 的每手股数，使用默认值 100")
                return 100
        except Exception as e:
            logger.error(f"获取 {code} 每手股数失败: {e}")
            return 100

    def execute_order(self, code, bsp_type, price, score):
        \"\"\"执行交易订单\"\"\"
        if self.dry_run:
            logger.info(f"🎯 [模拟交易] {code} {bsp_type} @ {price:.2f} HKD (视觉评分：{score}/100)")
            logger.info(f"   💰 仓位：最大 {MAX_POSITION_RATIO*100}%")
            return True
        else:
            logger.info(f"⚡️ [实盘交易] {code} {bsp_type} @ {price:.2f} HKD, 执行下单...")
            
            # 获取最新价格
            ret, data = self.quote_ctx.get_market_snapshot([code])
            if ret != RET_OK or data.empty:
                logger.error(f"获取 {code} 最新价格失败: {data}")
                return False
            current_price = float(data.iloc[0]['last_price'])

            if code in self.current_positions:
                logger.warning(f"已经持有 {code}，跳过买入")
                return False

            # 计算可买入数量
            lot_size = self.get_lot_size(code)
            if lot_size == 0:
                logger.error(f"获取 {code} 每手股数失败，无法下单")
                return False
            
            target_invest_amount = self.available_cash * MAX_POSITION_RATIO
            if target_invest_amount < current_price * lot_size: # 至少买入一手
                logger.warning(f"可用资金 {self.available_cash:.2f} 不足买入一手 {code} (价格 {current_price:.2f}, 每手 {lot_size} 股)，跳过买入")
                return False

            buy_qty = int(target_invest_amount / current_price)
            buy_qty = (buy_qty // lot_size) * lot_size # 对齐Lot Size

            if buy_qty == 0:
                logger.warning(f"计算出买入数量为0，跳过 {code} 买入")
                return False

            logger.info(f"准备买入 {code}: 数量 {buy_qty} 股，价格 {current_price:.2f} HKD")
            
            # 执行买入订单 (增强限价盘，市价*1.01确保成交)
            ret, data = self.trd_ctx.place_order(
                price=current_price * 1.01, 
                qty=buy_qty, 
                code=code, 
                trd_side=TrdSide.BUY, 
                order_type=OrderType.ENHANCE_LIMIT, 
                trd_env=TrdEnv.REAL # Change to REAL for real trading
            )
            
            if ret == RET_OK:
                order_id = data.iloc[0]['order_id']
                logger.info(f"✅ 成功提交买入订单！ID: {order_id}, 股票: {code}, 数量: {buy_qty}, 价格: {current_price:.2f}")
                # 更新持仓和可用资金
                self.current_positions[code] = {'qty': buy_qty, 'cost_price': current_price}
                self.available_cash -= buy_qty * current_price
                return True
            else:
                logger.error(f"❌ 买入订单提交失败: {data}")
                return False
    
    def scan_all(self):
        \"\"\"扫描所有港股\"\"\"
        # 检查是否在交易时间内
        if not is_hk_market_open():
            logger.info("⏰ 当前不在港股交易时间内，跳过扫描")
            logger.info("📋 港股扫描时间：9:31, 10:01, 10:31, 11:01, 11:31, 13:01, 13:31, 14:01, 14:31, 15:01, 15:31, 15:55, 16:01")
            return
        
        config = CChanConfig({
            "bi_strict": False,
            "one_bi_zs": True,
            "bs_type": '1,1p,2,2s,3a,3b'
        })
        
        total = len(self.hk_stocks)
        logger.info(f"🔍 开始扫描 {total} 只港股")
        logger.info(f"📋 配置：视觉阈值 >= {MIN_VISUAL_SCORE} 分 | {'模拟盘' if self.dry_run else '实盘'} | 单票最大{MAX_POSITION_RATIO*100}%仓位")
        logger.info(f"🔔 发现信号将自动发送通知并执行交易")
        logger.info("-" * 80)
        
        signals_found = 0
        signals_passed = 0
        orders_executed = 0
        
        for i, code in enumerate(self.hk_stocks, 1):
            try:
                # 进度显示
                logger.info(f"[{i}/{total}] 扫描 {code}...", end=" ")
                
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
                    logger.info("无信号")
                    continue
                
                bsp = latest_bsp[0]
                signal_time = pd.to_datetime(str(bsp.klu.time))
                is_fresh = (datetime.now() - signal_time).total_seconds() < 14400  # 4 小时内
                
                if not is_fresh:
                    logger.info(f"信号过期 ({signal_time})")
                    continue
                
                # 发现新鲜信号
                signals_found += 1
                bsp_type = bsp.type2str()
                price = bsp.klu.close
                is_buy = bsp.is_buy
                logger.info(f"✨ 发现 {bsp_type} @ {price:.2f}")
                
                # 只处理买入信号
                if not is_buy:
                    logger.info("⏭️ 跳过卖出信号")
                    continue
                
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
                    logger.warning("⚠️ 图表生成失败，跳过")
                    continue
                
                # 视觉评分
                logger.info(f"👁️ [视觉分析] {code} - 正在调用 Gemini 2.5 Flash...")
                visual_result = self.visual_judge.evaluate(chart_paths)
                
                if not visual_result:
                    logger.warning("⚠️ 视觉分析失败，跳过")
                    continue
                
                score = visual_result['score']
                action = visual_result['action']
                analysis = visual_result['analysis']
                
                logger.info(f"   📊 评分：{score}/100 | 决策：{action}")
                logger.info(f"   💡 分析：{analysis}")
                
                # 记录结果
                self.results.append({
                    'code': code,
                    'type': bsp_type,
                    'price': price,
                    'score': score,
                    'action': action,
                    'analysis': analysis
                })
                
                if score >= MIN_VISUAL_SCORE and action == "BUY":
                    signals_passed += 1
                    logger.info(f"✅ 视觉通过！执行买入...")
                    
                    # 发送信号通知
                    send_hk_signal_notification(
                        code=code,
                        bsp_type=bsp_type,
                        price=price,
                        score=score,
                        analysis=analysis,
                        chart_paths=chart_paths,
                        action="BUY"
                    )
                    
                    # 执行交易
                    if self.execute_order(code, f"买入 {bsp_type}", price, score):
                        orders_executed += 1
                else:
                    logger.info(f"❌ 视觉过滤 (评分:{score})")
                
                logger.info("-" * 80)
                time.sleep(1)  # 避免 API 限流
                
            except Exception as e:
                logger.error(f"❌ 扫描失败：{e}")
                # 打印完整的错误栈以便调试
                import traceback
                traceback.print_exc()
                continue
        
        # 生成汇总报告
        self.generate_summary_report(signals_found, signals_passed, orders_executed)
    
    def generate_summary_report(self, total_signals, passed_signals, orders_executed):
        \"\"\"生成汇总报告\"\"\"
        logger.info("\n" + "=" * 80)
        logger.info("📊 港股视觉扫描汇总报告")
        logger.info("=" * 80)
        logger.info(f"   总扫描：{len(self.hk_stocks)} 只")
        logger.info(f"   发现信号：{total_signals} 个")
        logger.info(f"   视觉通过：{passed_signals} 个")
        logger.info(f"   执行订单：{orders_executed} 个")
        logger.info(f"   过滤率：{(1 - passed_signals/max(total_signals,1))*100:.1f}%")
        logger.info("=" * 80)
    
    def close(self):
        self.quote_ctx.close()
        self.trd_ctx.close()

# ==================== 主函数 ====================
if __name__ == "__main__":
    scanner = HKStockVisualScanner(dry_run=DRY_RUN)
    try:
        scanner.load_hk_stocks()
        logger.info("🚀 开始港股视觉增强扫描...")
        scanner.scan_all()
    finally:
        scanner.close()
