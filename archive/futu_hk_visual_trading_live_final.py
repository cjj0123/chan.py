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
matplotlib.use(\'Agg\')
import matplotlib.pyplot as plt
import json
import subprocess
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format=\'%(asctime)s - %(levelname)s - %(message)s\',
    handlers=[
        logging.FileHandler(\'futu_trading.log\'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 导入视觉评分模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from visual_judge import VisualJudge

# ==================== 配置 ====================
HK_WATCHLIST_GROUP = \"港股\"  # Futu 港股自选股组名称
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
    
    if (morning_start <= now.time() <= morning_end) or \\
       (afternoon_start <= now.time() <= afternoon_end):
        return True
    
    return False

def send_hk_signal_notification(code, bsp_type, price, score, analysis, chart_paths, action=\"BUY\"):
    \"\"\"发送港股交易信号通知\"\"\"\
    try:
        title = f\"🎯 港股交易信号 - {code}\"\n        content = f\"\"\"\n# {code} 交易信号\n\n**信号类型:** {bsp_type}\n**价格:** {price:.2f} HKD\n**视觉评分:** {score}/100\n**决策:** {\'✅ 执行买入\' if action == \'BUY\' else \'❌ 过滤\'}\n\n## 视觉分析\n{analysis}\n\n## 图表\n{\', \'.join(chart_paths)}\n\n---\n⚠️ 仅供参考，不构成投资建议\n\"\"\"\n        
        # 发送到备忘录
        # cmd = [\"memo\", \"create\", \"--title\", title, content]
        # result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        # if result.returncode == 0:
        #    logger.info(f\"📱 已发送通知到备忘录：{title}\")
        
        # 保存信号到文件
        signal_file = f\"{CHARTS_DIR}/signal_{code.replace(\'.\', \'_\')}_{int(time.time())}.json\"\n        signal_data = {\n            \"code\": code,\n            \"type\": bsp_type,\n            \"price\": price,\n            \"score\": score,\n            \"analysis\": analysis,\n            \"action\": action,\n            \"time\": datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\"),\n            \"charts\": chart_paths\n        }\n        with open(signal_file, \'w\', encoding=\'utf-8\') as f:\n            json.dump(signal_data, f, ensure_ascii=False, indent=2)\n        logger.info(f\"💾 信号已保存到：{signal_file}\")
        
    except Exception as e:\n        logger.error(f\"⚠️ 通知发送失败：{e}\")

# ==================== 港股视觉扫描引擎 ====================\nclass HKStockVisualScanner:\n    def __init__(self, dry_run=True):\n        self.dry_run = dry_run\n        self.quote_ctx = OpenQuoteContext(host=\'127.0.0.1\', port=11111)\n        self.trd_ctx = OpenHKTradeContext(host=\'127.0.0.1\', port=11111)\n        self.hk_stocks = []\n        self.visual_judge = VisualJudge(use_mock=False)\n        self.results = []\n        self.current_positions = self.get_current_positions()\n        self.available_cash = self.get_available_cash()\n\n        if not self.dry_run:\n            ret, data = self.trd_ctx.unlock_trade(passwd=\"\", is_unlock=True)\n            if ret != RET_OK:\n                logger.error(f\"解锁交易失败：{data}\")\n                raise Exception(\"交易解锁失败\")\n            logger.info(\"✅ 交易账户已解锁\")\n        \n    def get_available_cash(self) -> float:\n        \"\"\"获取当前可用资金\"\"\"\n        if self.dry_run:\n            return INITIAL_CAPITAL # 模拟资金\n\n        ret, data = self.trd_ctx.accinfo_query(trd_env=TrdEnv.REAL # Change to REAL for real trading\n)\n        if ret == RET_OK:\n            return float(data.iloc[0][\'available_cash\'])\n        else:\n            logger.error(f\"获取可用资金失败: {data}\")\n            return 0.0\n\n    def get_current_positions(self) -> Dict[str, Any]:\n        \"\"\"获取当前持仓\"\"\"\n        if self.dry_run:\n            return {}\n        \n        positions = {}\n        ret, data = self.trd_ctx.position_list_query(trd_env=TrdEnv.REAL # Change to REAL for real trading\n)\n        if ret == RET_OK:\n            for _, row in data.iterrows():\n                positions[row[\'code\']] = {\n                    \'qty\': float(row[\'qty\']),\n                    \'cost_price\': float(row[\'cost_price\'])\n                }\n        else:\n            logger.error(f\"获取持仓失败: {data}\")\n        return positions\n\n    def load_hk_stocks(self):\n        \"\"\"加载港股自选股\"\"\"\n        stocks_list = []\n        \n        # 先列出所有可用的自选组\n        logger.info(\"📋 正在获取 Futu 自选股列表...\")\n        ret, groups_data = self.quote_ctx.get_user_security_group()\n        if ret == RET_OK:\n            logger.info(f\"✅ 找到 {len(groups_data)} 个自选股组:\")\n            for i, group_name in enumerate(groups_data[\'group_name\'].tolist(), 1):\n                logger.info(f\"   {i}. {group_name}\")\n        \n        # 从 Futu 自选组加载港股\n        logger.info(f\"\\n📂 正在加载 \'{HK_WATCHLIST_GROUP}\' 自选股...\")\n        ret, user_stocks = self.quote_ctx.get_user_security(HK_WATCHLIST_GROUP)\n        if ret == RET_OK and len(user_stocks) > 0:\n            hk_watchlist = user_stocks[user_stocks[\'code\'].str.startswith(\'HK.\')][\'code\'].tolist()\n            stocks_list.extend(hk_watchlist)\n            logger.info(f\"✅ 已加载自选港股：{len(hk_watchlist)} 只\")\n        else:\n            logger.warning(f\"⚠️ 无法从 \'{HK_WATCHLIST_GROUP}\' 加载股票，错误码：{ret}\")\n            logger.warning(\"💡 请确认 Futu App 中存在该自选股组，并且包含股票\")\n        \n        self.hk_stocks = stocks_list\n        if stocks_list:\n            logger.info(f\"📊 准备扫描 {len(self.hk_stocks)} 只港股\")\n        else:\n            logger.error(\"❌ 未找到任何港股，请检查自选股配置\")\n    \n    def generate_charts(self, code, chan_30m, chan_5m, signal_time):\n        \"\"\"生成 30M+5M 缠论图表\"\"\"\n        safe_code = code.replace(\'.\', \'_\')\n        safe_time = signal_time.strftime(\"%Y%m%d_%H%M%S\")\n        \n        try:\n            # 生成 30M 图表\n            plot_30m = CPlotDriver(\n                chan_30m,\n                plot_config={\"plot_kline\": True, \"plot_bi\": True, \"plot_zs\": True, \"plot_bsp\": True},\n                plot_para={\"figure\": {\"w\": 14, \"h\": 8}}\n            )\n            chart_30m = f\"{CHARTS_DIR}/{safe_code}_{safe_time}_30M.png\"\n            plt.savefig(chart_30m, bbox_inches=\'tight\', dpi=100)\n            plt.close(\'all\')\n            \n            # 生成 5M 图表\n            plot_5m = CPlotDriver(\n                chan_5m,\n                plot_config={\"plot_kline\": True, \"plot_bi\": True, \"plot_zs\": True, \"plot_bsp\": True},\n                plot_para={\"figure\": {\"w\": 14, \"h\": 8}}\n            )\n            chart_5m = f\"{CHARTS_DIR}/{safe_code}_{safe_time}_5M.png\"\n            plt.savefig(chart_5m, bbox_inches=\'tight\', dpi=100)\n            plt.close(\'all\')\n            \n            return [chart_30m, chart_5m]\n        except Exception as e:\n            logger.error(f\"⚠️ 图表生成失败：{e}\")\n            return None\n    \n    def get_lot_size(self, code: str) -> int:\n        \"\"\"获取港股每手股数\"\"\"\n        return self.hk_market.get_lot_size(code)\n\n    def execute_order(self, code, bsp_type, price, score):\n        \"\"\"执行交易订单\"\"\"\n        if self.dry_run:\n            logger.info(f\"🎯 [模拟交易] {code} {bsp_type} @ {price:.2f} HKD (视觉评分：{score}/100)\")\n            logger.info(f\"   💰 仓位：最大 {MAX_POSITION_RATIO*100}%\")\n            return True\n        else:\n            logger.info(f\"⚡️ [实盘交易] {code} {bsp_type} @ {price:.2f} HKD, 执行下单...\")\n            \n            # 获取最新价格\n            ret, data = self.quote_ctx.get_market_snapshot([code])\n            if ret != RET_OK or data.empty:\n                logger.error(f\"获取 {code} 最新价格失败: {data}\")\n                return False\n            current_price = float(data.iloc[0][\'last_price\'])\n\n            if code in self.current_positions:\n                logger.warning(f\"已经持有 {code}，跳过买入\")\n                return False\n\n            # 计算可买入数量\n            lot_size = self.get_lot_size(code)\n            if lot_size == 0:\n                logger.error(f\"获取 {code} 每手股数失败，无法下单\")\n                return False\n            \n            target_invest_amount = self.available_cash * MAX_POSITION_RATIO\n            if target_invest_amount < current_price * lot_size: # 至少买入一手\n                logger.warning(f\"可用资金 {self.available_cash:.2f} 不足买入一手 {code} (价格 {current_price:.2f}, 每手 {lot_size} 股)，跳过买入\")\n                return False\n\n            buy_qty = int(target_invest_amount / current_price)\n            buy_qty = (buy_qty // lot_size) * lot_size # 对齐Lot Size\n\n            if buy_qty == 0:\n                logger.warning(f\"计算出买入数量为0，跳过 {code} 买入\")\n                return False\n\n            logger.info(f\"准备买入 {code}: 数量 {buy_qty} 股，价格 {current_price:.2f} HKD\")\n            \n            # 执行买入订单 (增强限价盘，市价*1.01确保成交)\n            ret, data = self.trd_ctx.place_order(\n                price=current_price * 1.01, \n                qty=buy_qty, \n                code=code, \n                trd_side=TrdSide.BUY, \n                order_type=OrderType.ENHANCE_LIMIT, \n                trd_env=TrdEnv.REAL # Change to REAL for real trading\n            )\n            \n            if ret == RET_OK:\n                order_id = data.iloc[0][\'order_id\']\n                logger.info(f\"✅ 成功提交买入订单！ID: {order_id}, 股票: {code}, 数量: {buy_qty}, 价格: {current_price:.2f}\")\n                # 更新持仓和可用资金\n                self.current_positions[code] = {\'qty\': buy_qty, \'cost_price\': current_price}\n                self.available_cash -= buy_qty * current_price\n                return True\n            else:\n                logger.error(f\"❌ 买入订单提交失败: {data}\")\n                return False\n    \n    def scan_all(self):\n        \"\"\"扫描所有港股\"\"\"\n        # 检查是否在交易时间内\n        if not is_hk_market_open():\n            logger.info(\"⏰ 当前不在港股交易时间内，跳过扫描\")\n            logger.info(\"📋 港股扫描时间：9:31, 10:01, 10:31, 11:01, 11:31, 13:01, 13:31, 14:01, 14:31, 15:01, 15:31, 15:55, 16:01\")\n            return\n        \n        config = CChanConfig({\n            \"bi_strict\": False,\n            \"one_bi_zs\": True,\n            \"bs_type\": \'1,1p,2,2s,3a,3b\'\n        })\n        \n        total = len(self.hk_stocks)\n        logger.info(f\"🔍 开始扫描 {total} 只港股\")\n        logger.info(f\"📋 配置：视觉阈值 >= {MIN_VISUAL_SCORE} 分 | {\'模拟盘\' if self.dry_run else \'实盘\'} | 单票最大{MAX_POSITION_RATIO*100}%仓位\")\n        logger.info(f\"🔔 发现信号将自动发送通知并执行交易\")\n        logger.info(\"-\" * 80)\n        \n        signals_found = 0\n        signals_passed = 0\n        orders_executed = 0\n        \n        for i, code in enumerate(self.hk_stocks, 1):\n            try:\n                # 进度显示\n                logger.info(f\"[{i}/{total}] 扫描 {code}...\", end=\" \")\n                \n                # 获取 30M 数据\n                chan_30m = CChan(\n                    code=code,\n                    begin_time=(datetime.now() - timedelta(days=30)).strftime(\"%Y-%m-%d\"),\n                    data_src=DATA_SRC.FUTU,\n                    lv_list=[KL_TYPE.K_30M],\n                    config=config\n                )\n                \n                # 获取最新买卖点\n                latest_bsp = chan_30m.get_latest_bsp(number=1)\n                if not latest_bsp:\n                    logger.info(\"无信号\")\n                    continue\n                \n                bsp = latest_bsp[0]\n                signal_time = pd.to_datetime(str(bsp.klu.time))\n                is_fresh = (datetime.now() - signal_time).total_seconds() < 14400  # 4 小时内\n                \n                if not is_fresh:\n                    logger.info(f\"信号过期 ({signal_time})\")\n                    continue\n                \n                # 发现新鲜信号\n                signals_found += 1\n                bsp_type = bsp.type2str()\n                price = bsp.klu.close\n                is_buy = bsp.is_buy\n                logger.info(f\"✨ 发现 {bsp_type} @ {price:.2f}\")\n                \n                # 只处理买入信号\n                if not is_buy:\n                    logger.info(\"⏭️ 跳过卖出信号\")\n                    continue\n                \n                # 获取 5M 数据用于视觉分析\n                chan_5m = CChan(\n                    code=code,\n                    begin_time=(signal_time - timedelta(days=5)).strftime(\"%Y-%m-%d\"),\n                    end_time=(signal_time + timedelta(days=1)).strftime(\"%Y-%m-%d\"),\n                    data_src=DATA_SRC.FUTU,\n                    lv_list=[KL_TYPE.K_5M],\n                    config=config\n                )\n                \n                # 生成图表\n                chart_paths = self.generate_charts(code, chan_30m, chan_5m, signal_time)\n                if not chart_paths:\n                    logger.warning(\"⚠️ 图表生成失败，跳过\")\n                    continue\n                \n                # 视觉评分\n                logger.info(f\"👁️ [视觉分析] {code} - 正在调用 Gemini 2.5 Flash...\")\n                visual_result = self.visual_judge.evaluate(chart_paths)\n                \n                if not visual_result:\n                    logger.warning(\"⚠️ 视觉分析失败，跳过\")\n                    continue\n                \n                score = visual_result[\'score\']\n                action = visual_result[\'action\']\n                analysis = visual_result[\'analysis\']\n                \n                logger.info(f\"   📊 评分：{score}/100 | 决策：{action}\")\n                logger.info(f\"   💡 分析：{analysis}\")\n                \n                # 记录结果\n                self.results.append({\n                    \'code\': code,\n                    \'type\': bsp_type,\n                    \'price\': price,\n                    \'score\': score,\n                    \'action\': action,\n                    \'analysis\': analysis\n                })\n                \n                if score >= MIN_VISUAL_SCORE and action == \"BUY\":\n                    signals_passed += 1\n                    logger.info(f\"✅ 视觉通过！执行买入...\")\n                    \n                    # 发送信号通知\n                    send_hk_signal_notification(\n                        code=code,\n                        bsp_type=bsp_type,\n                        price=price,\n                        score=score,\n                        analysis=analysis,\n                        chart_paths=chart_paths,\n                        action=\"BUY\"\n                    )\n                    \n                    # 执行交易\n                    if self.execute_order(code, f\"买入 {bsp_type}\", price, score):\n                        orders_executed += 1\n                else:\n                    logger.info(f\"❌ 视觉过滤 (评分:{score})\")\n                \n                logger.info(\"-\" * 80)\n                time.sleep(1)  # 避免 API 限流\n                \n            except Exception as e:\n                logger.error(f\"❌ 扫描失败：{e}\")\n                # 打印完整的错误栈以便调试\n                import traceback\n                traceback.print_exc()\n                continue\n        \n        # 生成汇总报告\n        self.generate_summary_report(signals_found, signals_passed, orders_executed)\n    \n    def generate_summary_report(self, total_signals, passed_signals, orders_executed):\n        \"\"\"生成汇总报告\"\"\"\n        logger.info(\"\\n\" + \"=\" * 80)\n        logger.info(\"📊 港股视觉扫描汇总报告\")\n        logger.info(\"=\" * 80)\n        logger.info(f\"   总扫描：{len(self.hk_stocks)} 只\")\n        logger.info(f\"   发现信号：{total_signals} 个\")\n        logger.info(f\"   视觉通过：{passed_signals} 个\")\n        logger.info(f\"   执行订单：{orders_executed} 个\")\n        logger.info(f\"   过滤率：{(1 - passed_signals/max(total_signals,1))*100:.1f}%\")\n        logger.info(\"=\" * 80)\n    \n    def close(self):\n        self.quote_ctx.close()\n        self.trd_ctx.close()\n\n# ==================== 主函数 ====================\nif __name__ == \"__main__\":\n    scanner = HKStockVisualScanner(dry_run=DRY_RUN)\n    try:\n        scanner.load_hk_stocks()\n        logger.info(\"🚀 开始港股视觉增强扫描...\")\n        scanner.scan_all()\n    finally:\n        scanner.close()\n