#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股视觉扫描专用脚本 - 仅扫描和评分，不执行买入
结果发送到 Apple 备忘录
"""

import time as time_module
import os
import sys
from datetime import datetime, timedelta, time
import pandas as pd
from futu import *
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_SRC
from Plot.PlotDriver import CPlotDriver
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64
import subprocess
import json

# 导入视觉评分模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from visual_judge import VisualJudge

# ==================== 配置 ====================
CN_WATCHLIST_GROUP = "沪深"  # Futu 沪深自选股组名称
HK_WATCHLIST_GROUP = "港股"  # Futu 港股自选股组名称
SCAN_PERIOD = KL_TYPE.K_30M
MIN_VISUAL_SCORE = 6  # 视觉评分阈值
CHARTS_DIR = "./charts_cn_scan"
os.makedirs(CHARTS_DIR, exist_ok=True)

def send_signal_notification(code, bsp_type, price, score, analysis, chart_paths):
    """发送交易信号通知"""
    try:
        # 生成通知内容
        title = f"🎯 A 股交易信号 - {code}"
        content = f"""
# {code} 交易信号

**信号类型:** {bsp_type}
**价格:** {price:.2f} 元
**视觉评分:** {score}/10
**决策:** {'✅ 通过' if score >= MIN_VISUAL_SCORE else '❌ 过滤'}

## 视觉分析
{analysis}

## 图表
30M+5M 图表已生成：{', '.join(chart_paths)}

---
⚠️ 仅供参考，不构成投资建议
"""
        
        # 尝试发送到 Apple 备忘录
        cmd = ["memo", "create", "--title", title, content]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print(f"📱 已发送通知到备忘录：{title}")
        else:
            print(f"⚠️ 备忘录发送失败：{result.stderr}")
        
        # 同时保存信号到文件
        signal_file = f"./signal_{code.replace('.', '_')}_{int(time_module.time())}.json"
        signal_data = {
            "code": code,
            "type": bsp_type,
            "price": price,
            "score": score,
            "analysis": analysis,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "charts": chart_paths
        }
        with open(signal_file, 'w', encoding='utf-8') as f:
            json.dump(signal_data, f, ensure_ascii=False, indent=2)
        print(f"💾 信号已保存到：{signal_file}")
        
    except Exception as e:
        print(f"⚠️ 通知发送失败：{e}")

# A 股节假日（2026 年示例，需要根据实际更新）
CN_HOLIDAYS_2026 = [
    '2026-01-01',  # 元旦
    '2026-01-28',  # 除夕
    '2026-01-29',  # 春节
    '2026-01-30',  # 春节
    '2026-01-31',  # 春节
    '2026-02-01',  # 春节
    '2026-02-02',  # 春节
    '2026-04-04',  # 清明节
    '2026-04-05',  # 清明节
    '2026-05-01',  # 劳动节
    '2026-05-02',  # 劳动节
    '2026-05-03',  # 劳动节
    '2026-05-04',  # 劳动节
    '2026-05-05',  # 劳动节
    '2026-06-19',  # 端午节
    '2026-06-20',  # 端午节
    '2026-10-01',  # 国庆节
    '2026-10-02',  # 国庆节
    '2026-10-03',  # 国庆节
    '2026-10-04',  # 国庆节
    '2026-10-05',  # 国庆节
    '2026-10-06',  # 国庆节
    '2026-10-07',  # 国庆节
    '2026-10-08',  # 国庆节
]

# A 股交易时间检查
def is_cn_market_open():
    """检查是否在 A 股交易时间内"""
    from datetime import datetime, time
    now = datetime.now()
    
    # 周末不交易
    if now.weekday() >= 5:
        return False
    
    # 检查节假日
    date_str = now.strftime('%Y-%m-%d')
    if date_str in CN_HOLIDAYS_2026:
        return False
    
    # 交易时间：
    # 集合竞价：9:15-9:25
    # 早盘：9:30-11:30
    # 午盘：13:00-15:00
    # 扫描时间：9:26(集合竞价后), 9:31, 10:01, 10:31, 11:01, 11:31(13:00 执行), 13:01, 13:31, 14:01, 14:31, 15:01(最后一次)
    morning_end = time(11, 35)  # 11:31 扫描允许到 11:35
    afternoon_end = time(15, 5)  # 15:01 扫描允许到 15:05
    auction_time = time(9, 26)  # 集合竞价后扫描时间
    
    # 集合竞价后扫描窗口 (9:26-9:30)
    if time(9, 26) <= now.time() <= time(9, 30):
        return True
    # 早盘扫描窗口
    if time(9, 30) <= now.time() <= morning_end:
        return True
    # 午盘扫描窗口
    if time(12, 55) <= now.time() <= afternoon_end:
        return True
    
    return False

def get_scan_session():
    """获取当前扫描时段"""
    from datetime import datetime, time
    now = datetime.now()
    
    if time(9, 26) <= now.time() <= time(9, 30):
        return "集合竞价"
    if time(9, 30) <= now.time() <= time(11, 35):
        return "早盘"
    if time(12, 55) <= now.time() <= time(15, 5):
        return "午盘"
    return None

# ==================== A 股扫描引擎 ====================
class CNStockVisualScanner:
    def __init__(self):
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        self.cn_stocks = []
        self.visual_judge = VisualJudge(use_mock=False)
        self.results = []
        
    def load_cn_stocks(self):
        """加载 A 股自选股"""
        stocks_list = []
        
        # 先列出所有可用的自选组
        print("📋 正在获取 Futu 自选股列表...")
        ret, groups_data = self.quote_ctx.get_user_security_group()
        if ret == RET_OK:
            print(f"✅ 找到 {len(groups_data)} 个自选股组:")
            for i, group_name in enumerate(groups_data['group_name'].tolist(), 1):
                print(f"   {i}. {group_name}")
        
        # 从 Futu 自选组加载
        print(f"\n📂 正在加载 '{CN_WATCHLIST_GROUP}' 自选股...")
        ret, user_stocks = self.quote_ctx.get_user_security(CN_WATCHLIST_GROUP)
        if ret == RET_OK and len(user_stocks) > 0:
            cn_watchlist = user_stocks[
                user_stocks['code'].str.startswith('SH.') | 
                user_stocks['code'].str.startswith('SZ.')
            ]['code'].tolist()
            stocks_list.extend(cn_watchlist)
            print(f"✅ 已加载自选 A 股：{len(cn_watchlist)} 只")
        else:
            print(f"⚠️ 无法从 '{CN_WATCHLIST_GROUP}' 加载股票，错误码：{ret}")
            print("💡 请确认 Futu App 中存在该自选股组，并且包含股票")
        
        self.cn_stocks = stocks_list
        if stocks_list:
            print(f"📊 准备扫描 {len(self.cn_stocks)} 只 A 股")
        else:
            print("❌ 未找到任何 A 股，请检查自选股配置")
    
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
    
    def visual_analysis(self, code, chart_paths):
        """调用 Gemini 视觉评分"""
        print(f"👁️ [视觉分析] {code} - 正在调用 Gemini 2.5 Flash...")
        
        result = self.visual_judge.evaluate(chart_paths)
        
        if result:
            score = result['score']
            action = result['action']
            analysis = result['analysis']
            
            print(f"   📊 评分：{score}/10 | 决策：{action}")
            print(f"   💡 分析：{analysis}")
            
            return {
                'score': score,
                'action': action,
                'analysis': analysis,
                'pass': score >= MIN_VISUAL_SCORE and action == "BUY"
            }
        else:
            print(f"   ⚠️ 视觉分析失败")
            return None
    
    def send_to_memo(self, title, content, image_paths=None):
        """发送到 Apple 备忘录"""
        try:
            # 使用 memo CLI 创建备忘录
            cmd = ["memo", "create", "--title", title]
            
            # 如果有图片，添加到命令
            if image_paths:
                for img_path in image_paths[:2]:  # 最多 2 张图
                    if os.path.exists(img_path):
                        cmd.extend(["--attachment", img_path])
            
            # 添加内容
            cmd.append(content)
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ 已发送到备忘录：{title}")
                return True
            else:
                print(f"⚠️ 备忘录发送失败：{result.stderr}")
                return False
        except Exception as e:
            print(f"⚠️ 备忘录发送异常：{e}")
            return False
    
    def scan_all(self):
        """扫描所有 A 股"""
        # 检查是否在交易时间内
        session = get_scan_session()
        if not session:
            print("⏰ 当前不在 A 股交易时间内，跳过扫描")
            print("📋 A 股扫描时间:")
            print("   集合竞价：9:26 扫描 (9:15-9:25 竞价，9:26 分析，9:30 执行)")
            print("   早盘：9:31, 10:01, 10:31, 11:01, 11:31(13:00 执行)")
            print("   午盘：13:01, 13:31, 14:01, 14:31, 15:01(最后一次)")
            return
        
        config = CChanConfig({
            "bi_strict": False,
            "one_bi_zs": True,
            "bs_type": '1,1p,2,2s,3a,3b'
        })
        
        total = len(self.cn_stocks)
        print(f"🔍 开始扫描 {total} 只 A 股 [{session}]")
        print(f"📋 配置：视觉阈值 >= {MIN_VISUAL_SCORE} 分 | 仅扫描不交易")
        print(f"🔔 发现信号将自动发送通知")
        print("-" * 80)
        
        signals_found = 0
        signals_passed = 0
        
        for i, code in enumerate(self.cn_stocks, 1):
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
                bsp_type = bsp.type2str()
                price = bsp.klu.close
                print(f"✨ 发现 {bsp_type} @ {price:.2f}")
                
                # 获取 5M 数据
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
                    print("⚠️ 图表生成失败，跳过")
                    continue
                
                # 视觉评分
                visual_result = self.visual_analysis(code, chart_paths)
                if not visual_result:
                    continue
                
                # 记录结果
                self.results.append({
                    'code': code,
                    'type': bsp_type,
                    'price': price,
                    'time': signal_time,
                    'score': visual_result['score'],
                    'action': visual_result['action'],
                    'analysis': visual_result['analysis'],
                    'pass': visual_result['pass'],
                    'charts': chart_paths
                })
                
                if visual_result['pass']:
                    signals_passed += 1
                    print(f"✅ 视觉通过！发送通知...")
                    
                    # 发送信号通知
                    send_signal_notification(
                        code=code,
                        bsp_type=bsp_type,
                        price=price,
                        score=visual_result['score'],
                        analysis=visual_result['analysis'],
                        chart_paths=chart_paths
                    )
                else:
                    print(f"❌ 视觉过滤 (评分:{visual_result['score']})")
                
                print("-" * 80)
                time.sleep(1)  # 避免 API 限流
                
            except Exception as e:
                print(f"❌ 扫描失败：{e}")
                continue
        
        # 生成汇总报告
        self.generate_summary_report(signals_found, signals_passed)
    
    def generate_summary_report(self, total_signals, passed_signals):
        """生成汇总报告并发送到备忘录"""
        print("\n" + "=" * 80)
        print("📊 A 股视觉扫描汇总报告")
        print("=" * 80)
        print(f"   总扫描：{len(self.cn_stocks)} 只")
        print(f"   发现信号：{total_signals} 个")
        print(f"   视觉通过：{passed_signals} 个")
        print(f"   过滤率：{(1 - passed_signals/max(total_signals,1))*100:.1f}%")
        print("=" * 80)
        
        # 生成汇总内容
        summary = f"""
# A 股视觉扫描汇总

**扫描时间:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**扫描标的:** {len(self.cn_stocks)} 只 A 股
**视觉模型:** Gemini 2.5 Flash
**评分阈值:** >= {MIN_VISUAL_SCORE} 分

## 统计结果
- 发现信号：{total_signals} 个
- 视觉通过：{passed_signals} 个
- 过滤率：{(1 - passed_signals/max(total_signals,1))*100:.1f}%

## 通过信号详情
"""
        
        if self.results:
            for r in self.results:
                if r['pass']:
                    summary += f"\n### {r['code']} {r['type']}"
                    summary += f"\n- 价格：{r['price']:.2f} 元"
                    summary += f"\n- 评分：{r['score']}/10"
                    summary += f"\n- 分析：{r['analysis']}"
        else:
            summary += "\n无通过信号"
        
        summary += f"\n\n---\n⚠️ 仅供参考，不构成投资建议"
        
        # 发送汇总到备忘录
        memo_title = f"📊 A 股视觉扫描汇总 - {datetime.now().strftime('%m-%d %H:%M')}"
        self.send_to_memo(memo_title, summary)
        
        print(f"\n✅ 汇总报告已发送到备忘录")
    
    def close(self):
        self.quote_ctx.close()

# ==================== 主函数 ====================
if __name__ == "__main__":
    scanner = CNStockVisualScanner()
    try:
        scanner.load_cn_stocks()
        print("🚀 开始 A 股视觉扫描 (仅评分不交易)...")
        scanner.scan_all()
    finally:
        scanner.close()
